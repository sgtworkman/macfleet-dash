"""Read aggregate Hermes counters through explicitly opted-in existing SSH routes.

No installs, prompts, credentials, model calls or remote writes. Computer views
stay separate: migrated histories are not added into a fabricated fleet total.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

from token_usage import OUTPUT, counter, label


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def project_usage(value):
    """Whitelist remote aggregates; never forward arbitrary SSH output."""
    if not isinstance(value, dict) or value.get('schema') != 'macfleet.tokens.v1' or value.get('status') not in ('available', 'partial', 'unavailable'):
        raise ValueError('Usage schema unverified')
    at = value.get('observedAt')
    if not isinstance(at, str) or len(at) > 40:
        raise ValueError('Usage time unverified')
    datetime.fromisoformat(at.replace('Z', '+00:00'))
    rows = value.get('groups')
    if not isinstance(rows, list) or len(rows) > 2048:
        raise ValueError('Usage groups unverified')
    if (value['status'] == 'unavailable') == bool(rows):
        raise ValueError('Usage availability contradicts retained rows')
    groups = []
    for row in rows:
        if not isinstance(row, dict) or row.get('category') not in ('local', 'cloud', 'unknown') or type(row.get('recordCount')) is not int or not 0 < row['recordCount'] <= 100000:
            raise ValueError('Usage row unverified')
        result = {key: label(row.get(key)) for key in ('model', 'provider', 'agentProfile')}
        result.update(category=row['category'], recordCount=row['recordCount'], targetName=label(row['targetName']) if row.get('targetName') else None)
        for field in OUTPUT:
            raw = row.get(field)
            if raw is not None and counter(raw) is None:
                raise ValueError('Usage counter unverified')
            result[field] = raw
        for field in ('firstSeen', 'lastSeen'):
            raw = row.get(field)
            if raw is not None:
                if not isinstance(raw, str) or len(raw) > 40:
                    raise ValueError('Usage record time unverified')
                datetime.fromisoformat(raw.replace('Z', '+00:00'))
            result[field] = raw
        groups.append(result)
    totals = {}
    for category in ('local', 'cloud', 'unknown'):
        selected = [row for row in groups if row['category'] == category]
        expected = {'recordCount': sum(row['recordCount'] for row in selected)}
        expected.update({field: sum(row[field] for row in selected) if selected and all(row[field] is not None for row in selected) else None for field in OUTPUT})
        if value.get('totals', {}).get(category) != expected:
            raise ValueError('Usage totals do not reconcile')
        totals[category] = expected
    sources = value.get('sources')
    if not isinstance(sources, list) or len(sources) > 128:
        raise ValueError('Usage profile coverage unverified')
    safe_sources = []
    for row in sources:
        if (not isinstance(row, dict) or row.get('status') not in
                ('available', 'unavailable', 'no-row/unverified', 'duplicate alias · not counted',
                 'usage schema unavailable', 'usage exceeds bounded read · not counted', 'usage read unavailable')
                or counter(row.get('records')) is None):
            raise ValueError('Usage profile status unverified')
        safe_sources.append({'profile': label(row.get('profile')), 'status': row['status'], 'records': row['records']})
    starts = [row['firstSeen'] for row in groups if row['firstSeen']]
    ends = [row['lastSeen'] for row in groups if row['lastSeen']]
    return {'schema': 'macfleet.tokens.v1', 'status': value['status'], 'observedAt': at,
            'groups': groups, 'totals': totals, 'sources': safe_sources,
            'coverage': {'sourcesChecked': len(safe_sources), 'sourcesAvailable': sum(row['status'] == 'available' for row in safe_sources), 'unclassifiedRecords': totals['unknown']['recordCount'], 'start': min(starts) if starts else None, 'end': max(ends) if ends else None},
            'scope': 'Retained Hermes counters read on this computer, grouped by saved profile. Not proof of execution origin, all agents, billing, daily usage or current model routing.'}


def read_remote(host_id, entry, targets, run=subprocess.run):
    result = {'host': host_id, 'name': label(entry.get('name') or host_id), 'status': 'unavailable', 'receivedAt': stamp(), 'usage': None, 'reason': 'Existing SSH usage read unavailable'}
    try:
        alias = entry.get('host')
        if entry.get('method') != 'ssh' or not isinstance(alias, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@-]{0,127}', alias):
            raise ValueError('Existing explicit SSH alias required')
        source = Path(__file__).with_name('token_usage.py').read_text(encoding='utf-8')
        source += '\nimport json\nprint(json.dumps(read_usage(target_names=json.loads(' + repr(json.dumps(targets)) + '))))\n'
        command = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=3', alias, 'python3', '-B', '-']
        completed = run(command, input=source, capture_output=True, text=True, timeout=6)
        if completed.returncode or len(completed.stdout.encode('utf-8')) > 2 * 1024 * 1024:
            raise ValueError('Usage read failed or exceeds bound')
        usage = project_usage(json.loads(completed.stdout))
        result.update(status=usage['status'], usage=usage, reason=None if usage['status'] != 'unavailable' else 'No readable retained Hermes counters')
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired):
        pass
    result['receivedAt'] = stamp()
    return result


def add_computers(payload, config, targets, run=subprocess.run):
    hosts = config.get('hosts')
    if not isinstance(hosts, dict) or len(hosts) > 512 or any(not isinstance(entry, dict) for entry in hosts.values()):
        raise ValueError('Registered usage inventory unverified')
    selected = [(key, entry) for key, entry in hosts.items() if isinstance(entry, dict) and entry.get('usage') is True]
    if len(selected) > 4 or any(entry.get('method') != 'ssh' or not isinstance(key, str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,62}', key) for key, entry in selected):
        raise ValueError('Usage source bound exceeded')
    local_id = next((key for key, entry in hosts.items() if isinstance(entry, dict) and entry.get('method') == 'local'), 'localhost')
    local = dict(payload)
    local['scope'] = 'Retained Hermes counters read on this computer, grouped by saved profile. Not proof of execution origin, all agents, billing, daily usage or current model routing.'
    local_entry = hosts.get(local_id, {})
    computers = [{'host': local_id, 'name': label(local_entry.get('name') or local_id), 'status': local['status'], 'receivedAt': payload['observedAt'], 'usage': local, 'reason': None if local['status'] != 'unavailable' else 'No readable retained Hermes counters'}]
    with ThreadPoolExecutor(max_workers=4) as pool:
        computers.extend(pool.map(lambda pair: read_remote(*pair, targets, run), selected))
    known = {row['host'] for row in computers}
    for key, entry in hosts.items():
        if key not in known:
            computers.append({'host': key, 'name': label(entry.get('name') or key), 'status': 'not-configured', 'receivedAt': None, 'usage': None, 'reason': 'No opted-in existing SSH aggregate source; coverage unverified'})
    return {**payload, 'computers': computers, 'scope': local['scope'], 'computerScope': 'Select one source computer at a time. Histories may be migrated/copied, so computer totals are never combined. Profile labels are not proof of a running agent. Missing collectors remain unverified.'}
