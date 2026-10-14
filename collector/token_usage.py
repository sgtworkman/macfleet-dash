"""Aggregate-only projection of retained Hermes usage; no messages/config reads.
Read-only SQLite connections. Session counters are not daily totals or invoices.
"""
import ipaddress
from contextlib import closing
import math
from pathlib import Path
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

FIELDS = ('api_call_count', 'input_tokens', 'output_tokens', 'cache_read_tokens', 'cache_write_tokens', 'reasoning_tokens')
OUTPUT = ('apiCalls', 'inputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens', 'reasoningTokens')
CLOUD_DOMAINS = ('chatgpt.com', 'openai.com', 'anthropic.com', 'api.z.ai', 'api.deepseek.com', 'api.minimax.io', 'api.kimi.com', 'generativelanguage.googleapis.com', 'openrouter.ai', 'integrate.api.nvidia.com')

def numeric(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None

def label(value, fallback='Not recorded'):
    text = str(value or '').strip()
    return text if re.fullmatch(r'[A-Za-z0-9_.:/ @()+-]{1,160}', text) else fallback

def counter(value):
    parsed = numeric(value)
    return int(parsed) if parsed is not None and parsed == int(parsed) and parsed <= 9007199254740991 else None

def classify(base_url):
    """Use the recorded endpoint, never a model-name or pricing guess."""
    try:
        host = (urlsplit(base_url or '').hostname or '').lower()
    except ValueError:
        return 'unknown', None
    if not host:
        return 'unknown', None
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip in ipaddress.ip_network('100.64.0.0/10'):
            return 'local', host
    except ValueError:
        pass
    if host == 'localhost' or host.endswith(('.local', '.ts.net')):
        return 'local', host
    if any(host == domain or host.endswith('.' + domain) for domain in CLOUD_DOMAINS):
        return 'cloud', host
    return 'unknown', host

def iso(value, now):
    stamp = numeric(value)
    if stamp is None or stamp <= 0 or stamp > now + 90:
        return None
    try:
        return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except (OverflowError, ValueError, OSError):
        return None

def read_usage(hermes_dir=None, target_names=None, now=None):
    root = Path(hermes_dir) if hermes_dir is not None else Path.home() / '.hermes'
    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    targets = target_names or {}
    paths = [('default', root / 'state.db')]
    if (root / 'profiles').is_dir():
        paths += [(p.parent.name, p) for p in sorted((root / 'profiles').glob('*/state.db'))]
    sources, records, physical = [], {}, set()
    duplicates, invalid = 0, 0
    for profile, path in paths:
        source = {'profile': label(profile), 'status': 'unavailable', 'records': 0}
        sources.append(source)
        try:
            resolved = path.resolve(strict=True)
            stat = resolved.stat()
            identity = (stat.st_dev, stat.st_ino)
            if identity in physical:
                source['status'] = 'duplicate alias · not counted'
                continue
            physical.add(identity)
            with closing(sqlite3.connect(resolved.as_uri() + '?mode=ro', uri=True, timeout=0.5)) as connection:
                connection.execute('PRAGMA query_only=ON')
                columns = {r[1] for r in connection.execute('PRAGMA table_info(session_model_usage)')}
                required = {'session_id', 'model', 'billing_provider', 'billing_base_url', 'billing_mode', 'first_seen', 'last_seen', *FIELDS}
                if not required.issubset(columns):
                    source['status'] = 'usage schema unavailable'
                    continue
                task = 'task' if 'task' in columns else "'' AS task"
                rows = connection.execute('SELECT session_id,model,billing_provider,billing_base_url,billing_mode,' + task + ',' + ','.join(FIELDS) + ',first_seen,last_seen FROM session_model_usage LIMIT 100001').fetchall()
                if len(rows) > 100000:
                    source['status'] = 'usage exceeds bounded read · not counted'
                    continue
            source.update(status='available' if rows else 'no-row/unverified', records=len(rows))
            for row in rows:
                key = tuple(row[:6])
                if key in records:
                    duplicates += 1
                    rank = lambda r: (numeric(r[-1]) or -1, sum(numeric(v) or 0 for v in r[6:12]))
                    if rank(row) <= rank(records[key]):
                        continue
                records[key] = row
        except (OSError, sqlite3.Error, ValueError):
            source['status'] = 'usage read unavailable'
    groups = {}
    for row in records.values():
        _, model, provider, endpoint, mode, _ = row[:6]
        category, host = classify(endpoint)
        key = (category, label(provider), label(model), host)
        if key not in groups:
            groups[key] = {'category': category, 'provider': label(provider), 'model': label(model), 'targetName': label(targets[host]) if host in targets else None, 'recordCount': 0, 'firstSeen': None, 'lastSeen': None, **{name: 0 for name in OUTPUT}}
        group = groups[key]
        group['recordCount'] += 1
        for output_name, value in zip(OUTPUT, row[6:12]):
            parsed = counter(value)
            if parsed is None:
                group[output_name] = None
                invalid += 1
            elif group[output_name] is not None:
                group[output_name] += parsed
        first, last = iso(row[-2], now), iso(row[-1], now)
        if first and (not group['firstSeen'] or first < group['firstSeen']):
            group['firstSeen'] = first
        if last and (not group['lastSeen'] or last > group['lastSeen']):
            group['lastSeen'] = last
    rows = sorted(groups.values(), key=lambda g: (g['category'], g['provider'], g['model']))
    totals = {}
    for category in ('local', 'cloud', 'unknown'):
        selected = [g for g in rows if g['category'] == category]
        total = {'recordCount': sum(g['recordCount'] for g in selected)}
        for field in OUTPUT:
            total[field] = sum(g[field] for g in selected) if selected and all(g[field] is not None for g in selected) else None
        totals[category] = total
    available = sum(s['status'] == 'available' for s in sources)
    failed = any(s['status'] not in ('available', 'duplicate alias · not counted') for s in sources)
    starts = [g['firstSeen'] for g in rows if g['firstSeen']]
    ends = [g['lastSeen'] for g in rows if g['lastSeen']]
    return {'schema': 'macfleet.tokens.v1', 'observedAt': datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z'), 'status': 'unavailable' if not rows else 'partial' if failed or invalid or totals['unknown']['recordCount'] else 'available', 'clientHost': 'localhost', 'groups': rows, 'totals': totals, 'sources': sources, 'coverage': {'sourcesChecked': len(sources), 'sourcesAvailable': available, 'duplicatesRemoved': duplicates, 'unclassifiedRecords': totals['unknown']['recordCount'], 'start': min(starts) if starts else None, 'end': max(ends) if ends else None}, 'scope': 'Retained Hermes session/model counters on this cockpit only. Other computers, Codex desktop, non-Hermes traffic and provider billing are not covered. No per-day allocation is inferred.'}
