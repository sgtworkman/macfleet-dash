"""Optional aggregate-only reads of an existing private SparkDash installation.

Only cached metrics, token ledgers and history are read. No engine polling,
prompts, benchmark jobs, settings writes, prices, credentials or discovery.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
import os
import re
import socket
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCHEMA = 'macfleet.sparkdash.v1'
HISTORY_RANGES = ('1h', '6h', '24h', '7d', '30d')
TOKEN_RANGES = {'1h': '1h', '6h': '6h', '24h': 'today'}
MEASURES = ('gpuUtil', 'gpuTemp', 'gpuPower', 'memUsedMB', 'memFreeMB',
            'cpuUtil', 'cpuTemp', 'ramUsedMB', 'netRx', 'netTx')
LLM_MEASURES = ('genTps', 'prefillTps', 'kvUsage')
COUNTERS = ('promptTokens', 'completionTokens', 'cachedTokens')
ENDPOINT_NUMBERS = ('generationTps', 'prefillTps', 'cachedPrefillTps',
                    'uncachedPrefillTps', 'slotsActive', 'slotsTotal',
                    'requestsRunning', 'requestsWaiting', 'kvCacheUsage')
NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
    '100.64.0.0/10', '::1/128', 'fc00::/7'))
ID = re.compile(r'[a-z0-9][a-z0-9.-]{0,62}\Z')


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def text(value, limit=200):
    return (isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and not re.search(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]', value))


def numeric(value, maximum=10**15):
    return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum


def integer(value, maximum=2**53-1):
    return type(value) is int and 0 <= value <= maximum


def private_ip(value):
    address = ipaddress.ip_address(value)
    return any(address.version == net.version and address in net for net in NETWORKS)


def checked_base(value, resolve=socket.getaddrinfo):
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError('Private SparkDash origin required')
    url = urlsplit(value)
    if (url.scheme not in ('http', 'https') or not url.hostname or
            url.username is not None or url.password is not None or
            url.path not in ('', '/') or url.query or url.fragment):
        raise ValueError('Private SparkDash origin required')
    try:
        if not private_ip(url.hostname):
            raise ValueError('Private address required')
    except ValueError:
        # Exact configured MagicDNS origin only; no public hostname discovery.
        if url.scheme != 'https' or not re.fullmatch(r'[a-z0-9-]+\.[a-z0-9-]+\.ts\.net', url.hostname):
            raise ValueError('Private IP or HTTPS MagicDNS origin required')
        addresses = resolve(url.hostname, url.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not private_ip(row[4][0]) for row in addresses):
            raise ValueError('MagicDNS must resolve only to private addresses')
    if url.port is None and url.scheme != 'https':
        raise ValueError('Explicit HTTP port required')
    return value.rstrip('/')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('SparkDash redirects are not followed')


def fetch_text(url, token=None):
    opener = build_opener(ProxyHandler({}), NoRedirect())
    headers = {'User-Agent': 'workman-fleet-sparkdash/0.12.0', 'Cache-Control': 'no-cache'}
    if token:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', '::1', 'localhost'):
            raise ValueError('Bearer reads require HTTPS or loopback')
        headers['Authorization'] = 'Bearer '+token
    request = Request(url, headers=headers, method='GET')
    with opener.open(request, timeout=1.5) as response:
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('SparkDash response exceeds size bound')
    return raw.decode('utf-8')


def fetch_json(url, token=None):
    value = json.loads(fetch_text(url, token))
    if not isinstance(value, dict):
        raise ValueError('SparkDash response must be an object')
    return value


def project_health(value):
    metrics = value.get('metrics') or {}
    gpu = metrics.get('gpu') or {}
    ram = metrics.get('unifiedMemory') or {}
    raw = value.get('health')
    findings = None
    if isinstance(raw, list) and len(raw) <= 64:
        findings = []
        for item in raw:
            if (not isinstance(item, dict) or not isinstance(item.get('id'), str) or not ID.fullmatch(item['id'])
                    or item.get('severity') not in ('warn', 'critical') or not text(item.get('title'))):
                raise ValueError('SparkDash finding unverified')
            findings.append({k: item[k] for k in ('id', 'severity', 'title')})
    roce = metrics.get('roce') or {}
    ports = []
    for port in roce.get('devices', [])[:32]:
        if not isinstance(port, dict) or not text(port.get('name'), 80):
            continue
        ports.append({'name': port['name'], 'active': port.get('active') if type(port.get('active')) is bool else None,
                      'everActive': port.get('everActive') if type(port.get('everActive')) is bool else None,
                      'rateGbps': port.get('rateGbps') if numeric(port.get('rateGbps'), 10000) else None,
                      'lossStreak': port.get('loss', {}).get('streak') if integer(port.get('loss', {}).get('streak')) else None})
    power = gpu.get('power') or {}
    return {'findings': findings,
            'gpuTempC': gpu.get('temperature') if numeric(gpu.get('temperature'), 200) else None,
            'gpuPowerW': power.get('draw') if numeric(power.get('draw'), 10000) else None,
            'systemPowerW': power.get('systemDraw') if numeric(power.get('systemDraw'), 10000) else None,
            'headroomMB': ram.get('available') if numeric(ram.get('available')) else None,
            'thermalThrottle': gpu.get('throttle', {}).get('thermal') if type(gpu.get('throttle', {}).get('thermal')) is bool else None,
            'roceSampledAt': roce.get('sampledAt') if integer(roce.get('sampledAt')) else None,
            'rocePorts': ports}


def project_collectors(raw, units):
    """Read only documented provenance rows; labels and other metrics stay out."""
    result = {key: {} for key in units}
    pattern = re.compile(r'^sparkdash_collector_last_success_timestamp_seconds\{([^}]+)\} ([0-9.eE+-]+)$')
    for line in raw.splitlines():
        match = pattern.fullmatch(line)
        if not match:
            continue
        labels = dict(re.findall(r'([a-z_]+)="([^"\\]*)"', match[1]))
        unit, collector = labels.get('unit'), labels.get('collector')
        if unit not in result or not collector or not ID.fullmatch(collector.lower()):
            continue
        value = float(match[2])
        if not numeric(value, 10**12) or value <= 0 or collector in result[unit]:
            raise ValueError('SparkDash provenance unverified')
        result[unit][collector] = datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')
    return result


def project_metrics(value, unit_id, entry, hosts):
    if value.get('id') != unit_id or type(value.get('online')) is not bool:
        raise ValueError('SparkDash unit identity unverified')
    host = entry.get('host')
    if host is not None:
        expected = hosts[host].get('ts_ip') or entry.get('expected_address')
        if not expected or value.get('lanIp') != expected:
            raise ValueError('SparkDash to Workman Fleet identity mismatch')
    endpoints = value.get('metrics', {}).get('llm')
    if not isinstance(endpoints, list) or len(endpoints) > 16:
        raise ValueError('SparkDash endpoint rows unverified')
    rows, ports = [], set()
    for endpoint in endpoints:
        if (not isinstance(endpoint, dict) or not integer(endpoint.get('port'), 65535)
                or endpoint['port'] == 0 or endpoint['port'] in ports
                or type(endpoint.get('available')) is not bool):
            raise ValueError('SparkDash endpoint identity unverified')
        ports.add(endpoint['port'])
        row = {'port': endpoint['port'], 'available': endpoint['available']}
        for key in ('backend', 'modelId', 'generationTpsSource'):
            raw = endpoint.get(key)
            row[key] = raw if text(raw) else None
        for key in ENDPOINT_NUMBERS:
            raw = endpoint.get(key)
            maximum = 1 if key == 'kvCacheUsage' else 10**15
            row[key] = raw if numeric(raw, maximum) else None
            if key in ('slotsActive', 'slotsTotal', 'requestsRunning', 'requestsWaiting') and not integer(raw):
                row[key] = None
        for key in ('decodeActive', 'prefillActive'):
            row[key] = endpoint.get(key) if type(endpoint.get(key)) is bool else None
        if row['slotsTotal'] == 0:
            row['slotsTotal'] = None  # Zero is not a reported engine capacity.
        rows.append(row)
    return {'id': unit_id, 'host': host, 'name': entry.get('name') or
            (value['name'] if text(value.get('name')) else unit_id),
            'online': value['online'], 'worker': value.get('workerNode') is True,
            'endpoints': rows, 'systemHealth': project_health(value)}


def project_totals(value, source_range, unit_ids):
    if value.get('range') != source_range or not isinstance(value.get('series'), list) or len(value['series']) > 512:
        raise ValueError('SparkDash token range unverified')
    rows, seen = [], set()
    for series in value['series']:
        if not isinstance(series, dict):
            raise ValueError('SparkDash token series unverified')
        if series.get('sparkId') not in unit_ids:
            continue
        port, models = series.get('port'), series.get('models')
        if (not integer(port, 65535) or not port or not isinstance(models, list)
                or len(models) > 256 or not integer(series.get('updatedAt'))):
            raise ValueError('SparkDash token identity unverified')
        sums = {key: 0 for key in COUNTERS}
        for model in models:
            if not isinstance(model, dict) or not text(model.get('modelId')):
                raise ValueError('SparkDash token model unverified')
            key = (series['sparkId'], port, model['modelId'])
            if key in seen:
                raise ValueError('Duplicate SparkDash token identity')
            seen.add(key)
            row = {'unit': key[0], 'port': port, 'model': key[2],
                   'sourceUpdatedAt': series['updatedAt']}
            for field in COUNTERS:
                raw = model.get(field)
                if raw is not None and not integer(raw):
                    raise ValueError('SparkDash token counter unverified')
                row[field] = raw
                sums[field] = sums[field] + raw if raw is not None and sums[field] is not None else None
            if row['cachedTokens'] is not None and row['promptTokens'] is not None and row['cachedTokens'] > row['promptTokens']:
                raise ValueError('Cached tokens exceed prompt tokens')
            rows.append(row)
            if len(rows) > 4096:
                raise ValueError('SparkDash token row bound exceeded')
        totals = series.get('totals')
        if not isinstance(totals, dict) or any(totals.get(key) != sums[key] for key in COUNTERS):
            raise ValueError('SparkDash per-model totals do not reconcile')
    return {'rows': rows}


def project_points(points, measures):
    if not isinstance(points, list) or len(points) > 600:
        raise ValueError('SparkDash history point bound exceeded')
    result, previous = [], -1
    for point in points:
        if not isinstance(point, dict) or not integer(point.get('t')) or point['t'] <= previous:
            raise ValueError('SparkDash history times unverified')
        previous = point['t']
        row = {'t': previous}
        for field in measures:
            stat = point.get(field)
            if stat is None:
                continue  # A missing metric remains a gap, never a zero.
            if (not isinstance(stat, dict) or not numeric(stat.get('avg'))
                    or not numeric(stat.get('max')) or stat['avg'] > stat['max']):
                raise ValueError('SparkDash history statistics unverified')
            row[field] = {'avg': stat['avg'], 'max': stat['max']}
            if stat.get('min') is not None:
                if not numeric(stat['min']) or stat['min'] > stat['avg']:
                    raise ValueError('SparkDash history minimum unverified')
                row[field]['min'] = stat['min']
        result.append(row)
    return result


def project_history(value, selected_range):
    if value.get('enabled') is False:
        return {'enabled': False, 'range': selected_range, 'points': [], 'llm': []}
    if (value.get('enabled') is not True or value.get('range') != selected_range
            or not integer(value.get('stepMs')) or not value['stepMs']
            or not integer(value.get('from')) or not integer(value.get('to'))
            or value['from'] >= value['to'] or not isinstance(value.get('llm'), list)
            or len(value['llm']) > 16):
        raise ValueError('SparkDash history range unverified')
    points = project_points(value.get('points'), MEASURES)
    llm, ports = [], set()
    for entry in value['llm']:
        if not isinstance(entry, dict) or not integer(entry.get('port'), 65535) or not entry['port'] or entry['port'] in ports:
            raise ValueError('SparkDash history endpoint identity unverified')
        ports.add(entry['port'])
        llm.append({'port': entry['port'], 'points': project_points(entry.get('points'), LLM_MEASURES)})
    return {'enabled': True, 'range': selected_range, 'stepMs': value['stepMs'],
            'from': value['from'], 'to': value['to'], 'points': points, 'llm': llm}


def read_sparkdash(config, previous=None, read=None, now=stamp, resolve=socket.getaddrinfo, read_text=None):
    at = now()
    result = {'schema': SCHEMA, 'observedAt': at, 'status': 'not-configured',
              'sourceId': None, 'units': [], 'totals': {}, 'reason': None}
    settings = config.get('sparkdash')
    if not settings:
        return result
    if not isinstance(settings, dict):
        result.update(status='unavailable', reason='SparkDash configuration unverified')
        return result
    if settings.get('enabled') is not True:
        return result
    result.update(status='unavailable', reason='SparkDash configuration or private source unverified')
    try:
        base = checked_base(settings.get('url'), resolve)
        token = None
        if settings.get('token_env') is not None:
            variable = settings['token_env']
            if not isinstance(variable, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,99}', variable):
                raise ValueError('Bearer environment reference unverified')
            token = os.environ.get(variable)
            if not token or len(token) > 8192 or re.search(r'[\x00-\x20\x7f]', token):
                raise ValueError('Bearer credential unavailable')
        read = read or (lambda url: fetch_json(url, token))
        read_text = read_text or (lambda url: fetch_text(url, token))
        units = settings.get('units')
        hosts = config.get('hosts', {})
        if (not isinstance(units, dict) or not 1 <= len(units) <= 4 or
                any(not isinstance(key, str) or not ID.fullmatch(key) or not isinstance(entry, dict)
                    or entry.get('name') is not None and not text(entry['name'])
                    or entry.get('host') is not None and entry['host'] not in hosts
                    for key, entry in units.items())):
            raise ValueError('Explicit SparkDash units required')
        mapped = [entry['host'] for entry in units.values() if entry.get('host')]
        if len(mapped) != len(set(mapped)):
            raise ValueError('Duplicate Workman Fleet mapping')
        source_id = hashlib.sha256(json.dumps([base, units], sort_keys=True).encode()).hexdigest()
        result['sourceId'] = source_id
        prior = previous if isinstance(previous, dict) and previous.get('schema') == SCHEMA and previous.get('sourceId') == source_id else {}
        prior_units = {row['id']: row for row in prior.get('units', []) if isinstance(row, dict) and row.get('id') in units}

        def task(kind, identity, path, project, old):
            attempted = now()
            try:
                value = project(read(base + path))
                value.update(status='available', observedAt=now(), lastAttemptAt=attempted, reason=None)
            except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
                value = dict(old or {})
                value.update(status='unavailable', observedAt=value.get('observedAt'),
                             lastAttemptAt=attempted, reason='Private SparkDash read failed or returned invalid data')
            return kind, identity, value

        jobs = []
        for unit_id, entry in units.items():
            old = prior_units.get(unit_id, {})
            jobs.append(('unit', unit_id, '/api/sparks/' + unit_id + '/metrics',
                         lambda value, key=unit_id, item=entry: project_metrics(value, key, item, hosts),
                         {k: v for k, v in old.items() if k != 'history'}))
            for selected in HISTORY_RANGES:
                jobs.append(('history', (unit_id, selected), '/api/sparks/' + unit_id + '/history?range=' + selected,
                             lambda value, key=selected: project_history(value, key), old.get('history', {}).get(selected)))
        for selected, source_range in TOKEN_RANGES.items():
            jobs.append(('total', selected, '/api/llm-token-totals?range=' + source_range,
                         lambda value, key=source_range: project_totals(value, key, units), prior.get('totals', {}).get(selected)))
        unit_rows = {key: {'id': key, 'host': entry.get('host'), 'name': entry.get('name') or key,
                           'online': None, 'worker': None, 'endpoints': [], 'history': {}}
                     for key, entry in units.items()}
        states = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            for kind, identity, value in pool.map(lambda args: task(*args), jobs):
                states.append(value['status'])
                if kind == 'unit':
                    unit_rows[identity].update(value)
                elif kind == 'history':
                    unit_rows[identity[0]]['history'][identity[1]] = value
                else:
                    result['totals'][identity] = value
        if settings.get('collector_timestamps') is True:
            attempted = now()
            try:
                collectors = project_collectors(read_text(base+'/metrics'), units)
                provenance = {'status': 'available', 'observedAt': now(), 'lastAttemptAt': attempted, 'reason': None}
            except (OSError, ValueError, TypeError, OverflowError):
                collectors = {}
                provenance = {'status': 'unavailable', 'observedAt': None, 'lastAttemptAt': attempted, 'reason': 'Collector provenance is unavailable'}
            states.append(provenance['status'])
            for key, unit in unit_rows.items():
                unit['provenance'] = {**provenance, 'collectors': collectors.get(key, {})}
        result.update(units=list(unit_rows.values()),
                      status='available' if all(state == 'available' for state in states) else
                      'partial' if 'available' in states else 'unavailable', reason=None)
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        pass
    return result
