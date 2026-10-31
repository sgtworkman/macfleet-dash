"""Private server-owned fleet observations and alert transitions.

Consumes existing snapshots only. No probing, credentials, process enumeration,
remote commands, or additional device collector is introduced.
"""
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time

SCHEMA = 'workman.fleet.operations.v1'
STALE_SECONDS = 600
ID = re.compile(r'[a-z0-9][a-z0-9.-]{0,62}\Z')


def timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result.timestamp() if result.tzinfo else None
    except (AttributeError, TypeError, ValueError):
        return None


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def text(value, maximum=240):
    return isinstance(value, str) and len(value) <= maximum and not any(ord(c) < 32 for c in value)


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def read_json(path, optional=False):
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('Snapshot size unverified')
        value = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        if optional:
            return None
        raise ValueError('Required snapshot unavailable')
    if not isinstance(value, dict):
        raise ValueError('Snapshot shape unverified')
    return value


def checked_rows(source, windows=False):
    if windows:
        valid = source.get('schema') == 'macfleet.windows.v1'
    else:
        valid = source.get('app') == 'macfleet-dash' and source.get('schema') == 1
    rows = source.get('hosts')
    if not valid or not isinstance(rows, list) or len(rows) > 512:
        raise ValueError('Fleet source schema unverified')
    seen, names = set(), set()
    for row in rows:
        host = row.get('host') if isinstance(row, dict) else None
        if not isinstance(host, str) or not ID.fullmatch(host) or host in seen:
            raise ValueError('Fleet identity unverified or duplicated')
        if row.get('status') not in ('available', 'unavailable', 'not-enrolled'):
            raise ValueError('Fleet reading status unverified')
        seen.add(host)
        if windows:
            if row.get('platform') not in ('windows', 'unknown') or row.get('enrollment') not in ('enrolled', 'pilot', 'not-enrolled'):
                raise ValueError('Windows enrollment unverified')
            name = row.get('hostname')
            if row['enrollment'] != 'not-enrolled':
                if not text(name, 64) or not name or name.casefold() in names:
                    raise ValueError('Windows native identity unverified or duplicated')
                names.add(name.casefold())
    return rows


def load_fleet(root):
    """Apply the same unique-source ownership contract as the existing viewer."""
    root = Path(root)
    viewer = root/'viewer'
    base = read_json(viewer/'data.json')
    rows = {row['host']: dict(row) for row in checked_rows(base)}
    windows = read_json(viewer/'windows.json', optional=not (root/'windows-fleet.json').exists())
    pushed = read_json(viewer/'tailnet-windows.json', optional=not (root/'tailnet-fleet.json').exists())
    win = {row['host']: dict(row) for row in checked_rows(windows, True)} if windows else {}
    if pushed:
        for row in checked_rows(pushed, True):
            old = win.get(row['host'])
            if row.get('source') != 'windows-tailnet' or row.get('enrollment') not in ('enrolled', 'pilot') or not row.get('authenticatedNodeId'):
                raise ValueError('Private source identity unverified')
            if old and (old['enrollment'] != 'not-enrolled' or old.get('hostname') and old['hostname'].casefold() != row['hostname'].casefold()):
                raise ValueError('Conflicting telemetry owners or native identity')
            win[row['host']] = dict(row)
    native = set()
    for row in win.values():
        if row['enrollment'] != 'not-enrolled':
            name = row['hostname'].casefold()
            if name in native:
                raise ValueError('Duplicate physical Windows computer')
            native.add(name)
    for row in win.values():
        if row['host'] in rows or row['enrollment'] == 'not-enrolled' and (row.get('hostname') or '').casefold() in native:
            raise ValueError('Competing fleet identity')
        rows[row['host']] = row
    registry = read_json(viewer/'fleet-registry.json', optional=True)
    if registry:
        if registry.get('schema') != 'macfleet.registry.v1' or not isinstance(registry.get('hosts'), dict):
            raise ValueError('Registry schema unverified')
        pending = registry.get('pendingHosts', [])
        if not isinstance(pending, list) or len(pending) > 512:
            raise ValueError('Pending inventory unverified')
        pending_ids = set()
        for item in pending:
            host = item.get('host') if isinstance(item, dict) else None
            if not isinstance(host, str) or not ID.fullmatch(host) or host in pending_ids or not text(item.get('pendingReason'), 1200):
                raise ValueError('Pending identity unverified')
            pending_ids.add(host)
            if host in rows:
                if item.get('hostname') and rows[host].get('hostname') and item['hostname'].casefold() != rows[host]['hostname'].casefold():
                    raise ValueError('Pending native identity conflict')
                continue
            rows[host] = {**item, 'enrollment': 'not-enrolled', 'status': 'not-enrolled', 'observedAt': None, 'source': 'registry'}
        for host, row in rows.items():
            metadata = registry['hosts'].get(host, {})
            for key, limit in [('site', 80), ('role', 120), ('kind', 30), ('purpose', 30)]:
                if text(metadata.get(key), limit):
                    row[key] = metadata[key]
            if isinstance(metadata.get('expectedHours'), (dict, str)):
                row['expectedHours'] = metadata['expectedHours']
    spark = read_json(viewer/'sparkdash.json', optional=True)
    if spark and spark.get('schema') == 'macfleet.sparkdash.v1' and isinstance(spark.get('units'), list):
        for unit in spark['units']:
            host = unit.get('host') if isinstance(unit, dict) else None
            if host in rows:
                rows[host]['sparkHealth'] = {'status':unit.get('status'), 'observedAt':unit.get('observedAt'),
                                             'system':unit.get('systemHealth'), 'provenance':unit.get('provenance')}
    return list(rows.values())


def freshness(row, now):
    if row.get('enrollment') in ('not-enrolled', 'pilot'):
        return row['enrollment']
    if row.get('status') != 'available':
        return 'unavailable'
    at = timestamp(row.get('observedAt'))
    if at is None or at > now + 90:
        return 'unverified'
    return 'stale' if now - at > STALE_SECONDS else 'current'


def expected_now(row, now):
    hours = row.get('expectedHours')
    if hours == 'always':
        return True
    if not isinstance(hours, dict):
        return None
    try:
        from zoneinfo import ZoneInfo
        local = datetime.fromtimestamp(now, ZoneInfo(hours['timeZone']))
        periods = hours['days'].get(local.strftime('%a').lower())
        if not isinstance(periods, list):
            return None
        valid = re.compile(r'(?:[01]\d|2[0-3]):[0-5]\d\Z')
        if any(not valid.fullmatch(p.get('start', '')) or not valid.fullmatch(p.get('end', '')) or p['start'] >= p['end'] for p in periods):
            return None
        clock = local.strftime('%H:%M')
        return any(p['start'] <= clock < p['end'] for p in periods)
    except (KeyError, TypeError, ValueError):
        return None


SPARK_DOMAINS = {'thermal':'gpu', 'low-power':'gpu', 'memory':'memory', 'xid':'gpu',
                 'oom':'gpu', 'concurrency':'llm', 'link-speed':'network', 'roce-link':'roce', 'roce-loss':'roce'}


def spark_current(row, rule, now):
    health = row.get('sparkHealth') or {}
    provenance = health.get('provenance') or {}
    observed = timestamp(health.get('observedAt'))
    at = timestamp(provenance.get('collectors', {}).get(SPARK_DOMAINS.get(rule)))
    return (health.get('status') == 'available' and provenance.get('status') == 'available'
            and observed is not None and at is not None and 0 <= now-observed <= STALE_SECONDS
            and 0 <= now-at <= STALE_SECONDS)


def conditions(row, now):
    state = freshness(row, now)
    if state in ('not-enrolled', 'pilot'):
        return []
    result = []
    def add(rule, message, severity='medium'):
        result.append({'id': row['host']+':'+rule, 'host': row['host'], 'name': row.get('name') or row['host'], 'rule': rule, 'severity': severity, 'text': message, 'readingAt': row.get('observedAt')})
    if state != 'current':
        if expected_now(row, now) is not False:
            add('report', 'Monitoring has no current successful report. Power state is unverified.', 'high')
        return result
    drives = row.get('disks')
    if isinstance(drives, list):
        for drive in drives:
            if number(drive.get('freeGb')) and drive['freeGb'] < 20:
                add('disk-'+str(drive.get('drive', 'unknown')), 'Low storage on '+str(drive.get('drive', 'unknown'))+': '+str(drive['freeGb'])+' GiB available.')
    elif number(row.get('diskFreeGb')) and row['diskFreeGb'] < 20:
        add('disk', 'Low storage: '+str(row['diskFreeGb'])+' GB available.')
    if number(row.get('swapUsedGb')) and row['swapUsedGb'] > 8:
        add('swap', 'High swap: '+str(row['swapUsedGb'])+' GB in use.')
    if number(row.get('memUsedGb')) and number(row.get('ramGb')) and row['ramGb'] > 0 and row['memUsedGb']/row['ramGb'] >= 0.95:
        add('memory', 'Reported memory use is at least 95%; memory pressure is unverified.')
    if row.get('clockState') == 'skewed':
        add('clock', 'The computer clock differs from the authenticated receipt clock.')
    if row.get('sampleState') in ('partial', 'unavailable'):
        add('readings', 'The computer answered but some resource readings are unavailable.')
    for service in row.get('services', []):
        if service.get('state') != 'available' or service.get('status') != 'Running':
            name = str(service.get('name', 'Unknown service'))
            add('service-'+name, 'Selected service '+name+' is not confirmed running.', 'high')
    health = row.get('sparkHealth') or {}
    for finding in (health.get('system') or {}).get('findings') or []:
        rule = finding.get('id')
        if rule in SPARK_DOMAINS and spark_current(row, rule, now) and text(finding.get('title')):
            add('spark-'+rule, 'SparkDash: '+finding['title'], 'high' if finding.get('severity') == 'critical' else 'medium')
    return result


def can_clear(rule, row, now):
    """A successful host reply does not establish that every metric was read."""
    if rule.startswith('spark-'):
        return isinstance((row.get('sparkHealth', {}).get('system') or {}).get('findings'), list) and spark_current(row, rule[6:], now)
    if rule == 'report':
        return True
    if rule == 'disk':
        return number(row.get('diskFreeGb'))
    if rule.startswith('disk-'):
        return any(isinstance(d, dict) and 'disk-'+str(d.get('drive')) == rule and number(d.get('freeGb')) for d in row.get('disks', []))
    if rule == 'swap':
        return number(row.get('swapUsedGb'))
    if rule == 'memory':
        return number(row.get('memUsedGb')) and number(row.get('ramGb')) and row['ramGb'] > 0
    if rule == 'clock':
        return row.get('clockState') == 'verified'
    if rule == 'readings':
        return row.get('sampleState') == 'complete'
    if rule.startswith('service-'):
        return any('service-'+s.get('name', '') == rule and s.get('state') == 'available' and s.get('status') == 'Running' for s in row.get('services', []))
    return False


class Operations:
    def __init__(self, database, hold_seconds=120):
        self.path = Path(database)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.hold = max(0, hold_seconds)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS hosts(host TEXT PRIMARY KEY, state TEXT, site TEXT);
                CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY, host TEXT, rule TEXT,
                    payload TEXT, pending REAL, firing REAL, clearing REAL);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, at TEXT NOT NULL,
                    host TEXT NOT NULL, kind TEXT NOT NULL, message TEXT NOT NULL);
            ''')
        os.chmod(self.path, 0o600)

    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=2)
        db.row_factory = sqlite3.Row
        return db

    def evaluate(self, rows, now):
        if len({r['host'] for r in rows}) != len(rows):
            raise ValueError('Duplicate host in observation')
        by_host = {r['host']: r for r in rows}
        desired = {a['id']: a for row in rows for a in conditions(row, now)}
        at = iso(now)
        with self.connect() as db:
            def event(host, kind, message):
                db.execute('INSERT INTO events(at,host,kind,message) VALUES(?,?,?,?)', (at, host, kind, message))
            for row in rows:
                state, site = freshness(row, now), row.get('site') or 'Unassigned'
                old = db.execute('SELECT * FROM hosts WHERE host=?', (row['host'],)).fetchone()
                if old and old['state'] != state:
                    event(row['host'], 'connection', 'Monitoring changed from '+old['state']+' to '+state+'.')
                if old and old['site'] != site:
                    event(row['host'], 'location', 'Shared location changed to '+site+'.')
                db.execute('INSERT OR REPLACE INTO hosts VALUES(?,?,?)', (row['host'], state, site))
            old_alerts = {r['id']: dict(r) for r in db.execute('SELECT * FROM alerts')}
            for key, alert in desired.items():
                old = old_alerts.get(key)
                since = old['pending'] if old else now
                firing = old['firing'] if old else None
                if firing is None and now - since >= self.hold:
                    firing = now
                    event(alert['host'], 'alert.firing', alert['text'])
                db.execute('INSERT OR REPLACE INTO alerts VALUES(?,?,?,?,?,?,?)',
                           (key, alert['host'], alert['rule'], json.dumps(alert), since, firing, None))
            for key, old in old_alerts.items():
                if key in desired:
                    continue
                row = by_host.get(old['host'])
                # An unavailable source is never evidence that its resource or
                # service fault cleared. Keep the original alert until measured.
                if row is None or freshness(row, now) != 'current':
                    continue
                if not can_clear(old['rule'], row, now):
                    continue
                if old['firing'] is None:
                    db.execute('DELETE FROM alerts WHERE id=?', (key,))
                    continue
                since = old['clearing'] if old['clearing'] is not None else now
                if now - since >= max(30, self.hold):
                    event(old['host'], 'alert.resolved', 'Current readings cleared: '+json.loads(old['payload'])['text'])
                    db.execute('DELETE FROM alerts WHERE id=?', (key,))
                else:
                    db.execute('UPDATE alerts SET clearing=? WHERE id=?', (since, key))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 10000)')
            alerts = []
            for stored in db.execute('SELECT * FROM alerts ORDER BY pending,id'):
                alert = json.loads(stored['payload'])
                source = by_host.get(stored['host'])
                alert.update(state='firing' if stored['firing'] is not None else 'pending', since=iso(stored['pending']), firingAt=iso(stored['firing']) if stored['firing'] is not None else None, evidenceState=freshness(source, now) if source else 'unverified', suppressed=bool(source and freshness(source, now) != 'current' and expected_now(source, now) is False))
                alerts.append(alert)
            events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 200')]
        enrolled = [r for r in rows if r.get('enrollment') not in ('pilot', 'not-enrolled')]
        current = [r for r in enrolled if freshness(r, now) == 'current']
        return {'schema': SCHEMA, 'observedAt': at, 'status': 'available', 'counts': {'registered': len(rows), 'monitored': len(enrolled), 'responding': len(current), 'pending': len(rows)-len(enrolled)}, 'alerts': alerts, 'events': events, 'scope': 'Server observations since this installation started; sample times are not refreshed by evaluation.'}


def producer_health(root, now):
    producers = []
    for filename, name, required in [('data.json', 'Mac / Linux collector', True),
                                      ('windows.json', 'Windows WinRM bridge', (root/'windows-fleet.json').exists()),
                                      ('tailnet-windows.json', 'Authenticated Windows receiver', (root/'tailnet-fleet.json').exists()),
                                      ('sparkdash.json', 'SparkDash connector', False),
                                      ('model-status.json', 'Model metadata publisher', False),
                                      ('token-usage.json', 'Usage publisher', False)]:
        try:
            data = read_json(root/'viewer'/filename, optional=not required)
            if data is None:
                continue
            at = data.get('observedAt')
            t = timestamp(at)
            state = 'unverified' if t is None or t > now+90 else 'stale' if now-t > STALE_SECONDS else data.get('status', 'unverified')
            producers.append({'name': name, 'state': state, 'observedAt': at, 'reason': 'Device freshness is checked separately.'})
        except (OSError, ValueError, TypeError):
            producers.append({'name': name, 'state': 'unavailable', 'observedAt': None, 'reason': 'No readable source receipt.'})
    return producers


def atomic_json(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.fleet-operations-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


class Runtime:
    """One thread owned by the existing viewer service; reads existing writers."""
    def __init__(self, root, interval=30):
        self.root = Path(root)
        self.interval = max(5, interval)
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.latest = None
        self.rows = []
        self.health = {'lastAttemptAt': None, 'lastSuccessAt': None, 'error': None}
        self.operations = Operations(self.root/'state/fleet-operations.sqlite3')
        self.thread = threading.Thread(target=self.run, daemon=True, name='fleet-operations')

    def cycle(self):
        now = time.time()
        with self.lock:
            self.health['lastAttemptAt'] = iso(now)
        try:
            rows = load_fleet(self.root)
            result = self.operations.evaluate(rows, now)
            result["producers"] = producer_health(self.root, now)
            atomic_json(self.root/'viewer/operations.json', result)
            with self.lock:
                self.latest, self.rows = result, rows
                self.health.update(lastSuccessAt=result['observedAt'], error=None)
        except Exception as error:
            with self.lock:
                self.health['error'] = type(error).__name__

    def run(self):
        while not self.stop.is_set():
            self.cycle()
            self.stop.wait(self.interval)

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=3)

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.latest)) if self.latest is not None else None

    def status(self):
        with self.lock:
            return dict(self.health)

    def fleet(self):
        with self.lock:
            if self.latest is None:
                return None
            return {'app': 'macfleet-dash', 'productName': 'Workman Fleet', 'schema': 1,
                    'observedAt': self.latest['observedAt'], 'hosts': json.loads(json.dumps(self.rows)),
                    'operations': json.loads(json.dumps(self.latest)), 'runtime': dict(self.health)}
