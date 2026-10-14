"""Ingest-only Windows telemetry, bound to one verified Tailscale IPv4 address.

No dashboard, remote administration, credentials, proxy headers or public bind.
Each peer must match both an exact address and its current Tailscale stable ID.
This publisher owns tailnet-windows.json only; it never races the WinRM writer.
"""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location('windows_bridge', ROOT/'collector/windows_snapshot.py')
bridge = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bridge)
SCHEMA = 'macfleet.tailnet.config.v1'
NETWORK = ipaddress.ip_network('100.64.0.0/10')
MAX_BYTES = 128 * 1024


def tailnet_ip(value):
    try:
        address = ipaddress.ip_address(value)
    except (ValueError, TypeError):
        raise ValueError('Exact Tailscale IPv4 address required')
    if address not in NETWORK:
        raise ValueError('Address is outside the private Tailscale IPv4 range')
    return str(address)


def checked_config(config):
    if not isinstance(config, dict) or config.get('schema') != SCHEMA:
        raise ValueError('Tailnet configuration schema unverified')
    tailnet_ip(config.get('bindAddress'))
    if type(config.get('port')) is not int or not 1024 <= config['port'] <= 65535 or config['port'] == 8791:
        raise ValueError('Dedicated unprivileged ingest port required')
    if not re.fullmatch(r'n[A-Za-z0-9]{4,62}', str(config.get('collectorNodeId', ''))):
        raise ValueError('Collector stable identity unverified')
    hosts = config.get('hosts')
    if not isinstance(hosts, list):
        raise ValueError('Confirmed peer list required')
    ids, names, nodes, addresses = set(), set(), set(), set()
    for host in hosts:
        if not isinstance(host, dict) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,62}', str(host.get('id', ''))):
            raise ValueError('Host ID unverified')
        name = host.get('expectedComputerName', '')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}', name):
            raise ValueError('Native identity unverified')
        node = host.get('nodeId', '')
        if not re.fullmatch(r'n[A-Za-z0-9]{4,62}', node) or node == config['collectorNodeId']:
            raise ValueError('Peer stable identity unverified')
        address = tailnet_ip(host.get('address'))
        if address == config['bindAddress'] or host.get('kind') not in ('server', 'range', 'computer') or not isinstance(host.get('site'), str):
            raise ValueError('Peer classification/address unverified')
        if any(value in seen for value, seen in ((host['id'], ids), (name.casefold(), names), (node, nodes), (address, addresses))):
            raise ValueError('Duplicate physical peer or native identity')
        ids.add(host['id']); names.add(name.casefold()); nodes.add(node); addresses.add(address)
        services = host.get('services', [])
        if type(host.get('automaticVerified', False)) is not bool or host.get('purpose', 'other') not in ('ccw', 'pos', '4473', 'other'):
            raise ValueError('Monitoring verification/purpose unverified')
        if not isinstance(services, list) or len(services) > 32 or any(not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', s) for s in services):
            raise ValueError('Exact service allowlist required')
    return config


def whois(address, executable, via=None):
    address = tailnet_ip(address)
    command = [executable, 'whois', '--json', address]
    if via:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}', via):
            raise ValueError('Use an existing exact SSH alias for identity lookup')
        command = ['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=5', via, ' '.join(shlex.quote(part) for part in command)]
    result = subprocess.run(command, capture_output=True, timeout=10 if via else 5, check=True)
    if len(result.stdout) > MAX_BYTES:
        raise ValueError('Peer response exceeds size bound')
    node = json.loads(result.stdout).get('Node', {})
    # Return only identity fields, never profile, endpoints or account data.
    return {'id': node.get('StableID'), 'addresses': node.get('Addresses', [])}


def assert_peer(host, identity):
    if not isinstance(identity, dict) or identity.get('id') != host['nodeId'] or host['address']+'/32' not in identity.get('addresses', []):
        raise ValueError('Authenticated Tailscale peer mismatch')


def reviewed_sample(value, host):
    """Project reviewed fields only. Extra JSON can never become a file exfil path."""
    bridge.pilot.validate_structure(value, host['expectedComputerName'])
    for key in ('disks', 'network', 'services'):
        if not isinstance(value.get(key), list) or len(value[key]) > 64:
            raise ValueError('Native row bound exceeded')
    if value.get('os') is not None and (not isinstance(value['os'], str) or len(value['os']) > 256):
        raise ValueError('OS label unverified')
    projected = {key: value[key] for key in ('schema', 'host', 'status', 'units', 'observedAt', 'cpuUsedPct', 'ramGb', 'memUsedGb', 'uptimeDays', 'gpuUtilPct', 'temperatureC', 'powerW', 'networkState')}
    projected['os'] = value.get('os')
    projected['disks'] = [{key: row.get(key) for key in ('drive', 'status', 'totalGb', 'usedGb', 'freeGb')} for row in value['disks']]
    projected['network'] = []
    for row in value['network']:
        if not isinstance(row.get('name'), str) or not 0 < len(row['name']) <= 128 or any(ord(c) < 32 for c in row['name']):
            raise ValueError('Adapter name unverified')
        projected['network'].append({key: row[key] for key in ('name', 'receivedBytes', 'sentBytes')})
    projected['services'] = []
    seen = set()
    for row in value['services']:
        if not isinstance(row, dict) or row.get('name') not in host.get('services', []) or row['name'] in seen or row.get('state') not in ('available', 'unavailable'):
            raise ValueError('Unapproved service row')
        if row.get('status') not in ('Running', 'Stopped', 'Paused', 'StartPending', 'StopPending', 'ContinuePending', 'PausePending', None) or (row['state'] == 'unavailable' and row.get('status') is not None) or (row['state'] == 'available' and row.get('status') is None):
            raise ValueError('Service state unverified')
        seen.add(row['name'])
        projected['services'].append({key: row.get(key) for key in ('name', 'state', 'status')})
    if seen != set(host.get('services', [])):
        raise ValueError('Selected service rows missing')
    return projected


class Receiver:
    def __init__(self, config, output, identity_lookup, now=bridge.utc, config_reader=None):
        self.config = checked_config(config)
        self.listener_identity = tuple(self.config[key] for key in ('bindAddress', 'port', 'collectorNodeId'))
        self.output = Path(output)
        self.identity_lookup = identity_lookup
        self.now = now
        self.config_reader = config_reader

    def refresh_config(self):
        if self.config_reader:
            config = checked_config(self.config_reader())
            if tuple(config[key] for key in ('bindAddress', 'port', 'collectorNodeId')) != self.listener_identity:
                raise ValueError('Listener identity changed; restart explicitly')
            self.config = config

    def read(self):
        try:
            value = json.loads(self.output.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {'schema': bridge.SCHEMA, 'hosts': [], 'history': {}}
        if value.get('schema') != bridge.SCHEMA or not isinstance(value.get('hosts'), list):
            raise ValueError('Previous snapshot unverified; preserved')
        return value

    def accept(self, address, host_id, sample):
        host = next((h for h in self.config['hosts'] if h['address'] == address and h['id'] == host_id), None)
        if host is None:
            raise PermissionError('Peer not approved')
        assert_peer(host, self.identity_lookup(address))
        sample = reviewed_sample(sample, host)
        previous = self.read()
        approved = {h['id']: h for h in self.config['hosts']}
        retained = {row['host']: row for row in previous['hosts'] if row.get('host') in approved and row.get('authenticatedNodeId') == approved[row['host']]['nodeId'] and str(row.get('hostname', '')).casefold() == approved[row['host']]['expectedComputerName'].casefold()}
        old = retained.get(host_id)
        if old and bridge.pilot.sample_time(sample['observedAt']) <= bridge.pilot.sample_time(old['sourceObservedAt']):
            raise ValueError('Repeated or out-of-order source sample')
        at = self.now()
        if old and at <= bridge.pilot.sample_time(old['receivedAt']):
            raise ValueError('Receiver clock moved backwards')
        row = bridge.project_sample(sample, dict(host, enabled=True), at, old)
        row.update(source='windows-tailnet', freshnessBasis='cockpit receipt of authenticated Tailscale push', authenticatedNodeId=host['nodeId'], purpose=host.get('purpose', 'other'), enrollment='enrolled' if host.get('automaticVerified') else 'pilot')
        retained[host_id] = row
        history = previous.get('history', {})
        history = {period: {key: points for key, points in history.get(period, {}).items() if key in retained} for period in ('hosts', 'week')}
        rows = list(retained.values())
        value = {'schema': bridge.SCHEMA, 'receiverVersion': '0.1.0', 'observedAt': bridge.iso(at), 'hosts': rows, 'history': bridge.update_history(history, rows, at), 'scope': 'Identity-pinned private Windows telemetry only. Receipt and source clock are distinct; retained timestamps never become a new sample.'}
        bridge.atomic_json(self.output, value)
        return row


def handler_for(receiver):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'MacFleetIngest'

        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self, *args):
            pass  # Never log request bodies, headers or peer/account details.

        def do_POST(self):
            try:
                receiver.refresh_config()
                if self.headers.get('Transfer-Encoding') or self.headers.get_content_type() != 'application/json':
                    raise ValueError('Unsupported framing')
                length = self.headers.get('Content-Length', '')
                if not length.isdecimal() or not 0 < int(length) <= MAX_BYTES:
                    raise ValueError('Invalid content length')
                match = re.fullmatch(r'/v1/samples/([a-z0-9][a-z0-9.-]{0,62})', self.path)
                if not match:
                    self.send_error(404); return
                address = self.client_address[0]
                if not any(h['address'] == address and h['id'] == match[1] for h in receiver.config['hosts']):
                    raise PermissionError('Peer not approved')
                body = self.rfile.read(int(length))
                if len(body) != int(length):
                    raise ValueError('Incomplete payload')
                receiver.accept(address, match[1], json.loads(body))
                self.send_response(202)
                self.send_header('Content-Length', '0')
                self.end_headers()
            except PermissionError:
                self.send_error(403, 'Peer not approved')
            except Exception:
                self.send_error(422, 'Sample not accepted')
            self.close_connection = True

        def do_GET(self):
            self.send_error(404)  # No telemetry read route, dashboard or file serving.

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', default=str(ROOT/'viewer/tailnet-windows.json'))
    parser.add_argument('--tailscale', default='/usr/local/bin/tailscale')
    parser.add_argument('--identity-via', help='Existing trusted SSH alias if the local background Tailscale CLI is unavailable')
    args = parser.parse_args()
    path = Path(args.config)
    if path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid():
        raise ValueError('Receiver configuration must be owner-only')
    def read_config():
        if path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid():
            raise ValueError('Receiver configuration must remain owner-only')
        return json.loads(path.read_text(encoding='utf-8'))
    config = checked_config(read_config())
    identity = lambda address: whois(address, args.tailscale, args.identity_via)
    assert_peer({'nodeId': config['collectorNodeId'], 'address': config['bindAddress']}, identity(config['bindAddress']))
    import fcntl
    with open(ROOT/'state/tailnet-receiver.lock', 'a') as lock:
        os.chmod(lock.name, 0o600)
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        receiver = Receiver(config, args.output, identity, config_reader=read_config)
        # Plain HTTP exists only inside WireGuard, on this exact verified IP.
        # No proxy or forwarded-identity headers are trusted.
        server = HTTPServer((config['bindAddress'], config['port']), handler_for(receiver))
        print('MacFleet private ingest started', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit('Private ingest unavailable: '+type(error).__name__)
