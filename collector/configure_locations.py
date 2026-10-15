"""Apply location labels to a private viewer registry, without probing or restarting.

Only hosts[ID].site is changed. Existing identity, enrollment, pending inventory
and other metadata are preserved. A previous registry is backed up privately.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HOST_ID = re.compile(r'[a-z0-9][a-z0-9.-]{0,62}')


def location_name(value):
    if not isinstance(value, str):
        raise ValueError('Location must be text')
    label = value.strip() or 'Unassigned'
    if len(label) > 80 or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0x202a <= ord(c) <= 0x202e or 0x2066 <= ord(c) <= 0x2069 for c in label):
        raise ValueError('Location must be at most 80 characters without control characters')
    if label == 'all':
        raise ValueError('The name all is reserved for the location filter')
    return label


def checked_locations(value):
    if not isinstance(value, dict) or value.get('schema') != 'macfleet.locations.v1' or not isinstance(value.get('locations'), dict) or set(value) - {'schema', 'locations'}:
        raise ValueError('Invalid location settings format')
    if len(value['locations']) > 512 or any(not isinstance(key, str) or not HOST_ID.fullmatch(key) for key in value['locations']):
        raise ValueError('Invalid location computer IDs')
    return {key: location_name(label) for key, label in value['locations'].items()}


def merge_locations(registry, locations):
    if not isinstance(registry, dict) or registry.get('schema') != 'macfleet.registry.v1' or not isinstance(registry.get('hosts', {}), dict):
        raise ValueError('Existing registry format is unverified; preserved')
    result = dict(registry)
    result['hosts'] = {key: dict(row) if isinstance(row, dict) else row for key, row in registry.get('hosts', {}).items()}
    for key, label in checked_locations({'schema': 'macfleet.locations.v1', 'locations': locations}).items():
        row = result['hosts'].get(key, {})
        if not isinstance(row, dict):
            raise ValueError('Existing host metadata is unverified; preserved')
        result['hosts'][key] = dict(row, site=label)
    return result


def apply_locations(path, locations, backup_dir):
    path, backup_dir = Path(path), Path(backup_dir)
    if path.is_symlink():
        raise ValueError('Registry must be a regular file, not a symbolic link')
    previous = path.read_bytes() if path.exists() else None
    if previous is not None and len(previous) > 1024 * 1024:
        raise ValueError('Existing registry exceeds the size limit; preserved')
    registry = json.loads(previous) if previous is not None else {'schema': 'macfleet.registry.v1', 'hosts': {}}
    merged = merge_locations(registry, locations)
    encoded = (json.dumps(merged, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode('utf-8')
    if merged == registry:
        return None, False
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    backup = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.macfleet-locations-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if previous is not None:
            backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            with tempfile.NamedTemporaryFile(dir=backup_dir, prefix='registry-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'), suffix='.json', delete=False) as stream:
                backup = Path(stream.name)
                stream.write(previous)
                stream.flush()
                os.fsync(stream.fileno())
        # Never overwrite another owner's change made while this command ran.
        if path.is_symlink() or (path.read_bytes() if path.exists() else None) != previous:
            raise ValueError('Registry changed while editing; preserved. Run the command again.')
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        return backup, True
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', type=Path, default=ROOT / 'viewer/fleet-registry.json')
    parser.add_argument('--backup-dir', type=Path, default=ROOT / 'state/location-backups')
    parser.add_argument('--set', nargs=2, action='append', default=[], metavar=('HOST_ID', 'LOCATION'))
    parser.add_argument('--import', dest='import_path', type=Path, help='Location JSON downloaded from the Locations screen')
    args = parser.parse_args(argv)
    try:
        locations = {}
        if args.import_path:
            if args.import_path.stat().st_size > 131072:
                raise ValueError('Location settings exceed the size limit')
            locations.update(checked_locations(json.loads(args.import_path.read_text(encoding='utf-8'))))
        for key, label in args.set:
            locations.update(checked_locations({'schema': 'macfleet.locations.v1', 'locations': {key: label}}))
        if not locations:
            parser.error('Provide --set HOST_ID LOCATION or --import FILE')
        backup, changed = apply_locations(args.registry, locations, args.backup_dir)
    except (OSError, ValueError) as error:
        parser.exit(2, 'Locations not applied: ' + str(error) + '\n')
    print(('Saved ' if changed else 'Already set: ') + str(len(locations)) + ' location labels. Refresh the viewer; no restart or new probe is needed.')
    if backup:
        print('Previous private registry backup: ' + str(backup))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
