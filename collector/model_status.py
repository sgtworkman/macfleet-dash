"""Bounded, read-only model metadata for explicitly configured private endpoints.

No completions, model loading, credentials, redirects or network discovery.
The existing snapshot publisher calls this; it does not create a scheduler.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCHEMA = 'macfleet.models.v1'
MAX_BYTES = 131072
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in (
    '127.0.0.0/8', '10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16',
    '100.64.0.0/10', '::1/128', 'fc00::/7',
))


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def text(value, limit=200):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit and not re.search(r'[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]', value)


def positive_integer(value):
    return value if type(value) is int and 0 < value <= 10**13 else None


def checked_url(value, expected_ip=None):
    if not isinstance(value, str) or len(value) > 512:
        raise ValueError('Exact private model URL required')
    url = urlsplit(value)
    address = ipaddress.ip_address(url.hostname or '')
    if (url.scheme not in ('http', 'https') or url.username is not None or
            url.password is not None or url.query or url.fragment or
            url.path != '/v1/models' or not url.port or
            not any(address.version == network.version and address in network for network in PRIVATE_NETWORKS)):
        raise ValueError('Exact private model URL required')
    if expected_ip is not None and address != ipaddress.ip_address(expected_ip):
        raise ValueError('Model endpoint does not match this registered computer')
    return value


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Model redirects are not followed')


def fetch_json(url):
    # Do not forward machine proxy credentials or accept a redirect elsewhere.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(url, headers={'User-Agent': 'macfleet-model-status/0.9.4', 'Cache-Control': 'no-cache'}, method='GET')
    with opener.open(request, timeout=2) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Model metadata exceeds size bound')
    value = json.loads(raw.decode('utf-8'))
    if not isinstance(value, dict):
        raise ValueError('Model metadata must be an object')
    return value


def read_model(host, entry, read=fetch_json, now=timestamp):
    result = {'host': host, 'status': 'unavailable', 'observedAt': now(),
              'modelId': None, 'models': [], 'artifact': None, 'engine': None,
              'quantization': None, 'contextTokens': None, 'parameterCount': None,
              'source': 'GET /v1/models', 'reason': 'Model endpoint unavailable'}
    try:
        url = checked_url(entry.get('model_url'), entry.get('ts_ip'))
        value = read(url)
        rows = value.get('data')
        if not isinstance(rows, list) or not 0 < len(rows) <= 32 or any(not isinstance(row, dict) or not text(row.get('id')) for row in rows):
            raise ValueError('Model rows unverified')
        ids = [row['id'] for row in rows]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate model identities')
        if len(ids) > 1:
            result.update(status='multiple', models=ids, reason='Multiple models reported; no single active model inferred', observedAt=now())
            return result
        row, model = rows[0], ids[0]
        # Generic API catalogs are not proof of which model is loaded. The
        # supported loaded-model identity/metadata contract is llama.cpp.
        if row.get('owned_by') != 'llamacpp':
            result.update(status='catalog', models=ids, reason='Model catalog reported; loaded model not verified', observedAt=now())
            return result
        meta = row.get('meta') if isinstance(row.get('meta'), dict) else {}
        result.update(modelId=model, models=ids, engine='llama.cpp',
                      contextTokens=positive_integer(meta.get('n_ctx')),
                      parameterCount=positive_integer(meta.get('n_params')),
                      quantization=meta.get('ftype') if text(meta.get('ftype'), 80) else None)
        props_url = urlunsplit(urlsplit(url)._replace(path='/props'))
        try:
            props = read(props_url)
            if not isinstance(props, dict):
                raise ValueError('Optional model properties unverified')
        except (OSError, ValueError, TimeoutError):
            props = None  # Identity remains known; optional details stay unknown.
        if props is not None:
            if props.get('model_alias') != model:
                raise ValueError('Model changed during identity check')
            path = props.get('model_path')
            artifact = re.split(r'[/\\]', path)[-1] if isinstance(path, str) else None
            result['artifact'] = artifact if text(artifact) and artifact not in ('.', '..') else None
            settings = props.get('default_generation_settings')
            if isinstance(settings, dict) and positive_integer(settings.get('n_ctx')):
                result['contextTokens'] = settings['n_ctx']
            result['source'] += ' + /props'
        result.update(status='available', reason=None, observedAt=now())
        return result
    except (OSError, ValueError, TypeError, TimeoutError):
        # Never expose URLs, response bodies, full paths or exception text.
        result.update(status='unavailable', modelId=None, models=[], artifact=None,
                      engine=None, quantization=None, contextTokens=None,
                      parameterCount=None, observedAt=now())
        return result


def read_models(config, read=fetch_json, now=timestamp):
    hosts = config.get('hosts')
    if not isinstance(hosts, dict) or len(hosts) > 512:
        raise ValueError('Registered model computer identities unverified')
    entries = [(host, entry) for host, entry in hosts.items() if isinstance(entry, dict) and entry.get('model_url')]
    if len(entries) > 8 or any(not isinstance(host, str) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,62}', host) for host, _ in entries):
        raise ValueError('Registered model endpoint bound exceeded')
    with ThreadPoolExecutor(max_workers=min(4, len(entries)) or 1) as pool:
        rows = list(pool.map(lambda pair: read_model(*pair, read=read, now=now), entries))
    return {'schema': SCHEMA, 'observedAt': now(), 'hosts': rows,
            'scope': 'Configured private endpoint metadata only; no prompts, model changes, usage or performance inference'}
