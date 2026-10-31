#!/usr/bin/env python3
"""Inspect an actual public source archive without extracting or running it.

Reject private runtime files, unsafe members and incomplete viewer packages.
This is a packaging check, not a substitute for secret scanning or browser QA.
"""
import argparse
from pathlib import Path, PurePosixPath
import re
import tarfile

PRIVATE_NAMES = {
    'macfleet.toml', 'macfleet.json', 'windows-fleet.json', 'tailnet-fleet.json',
    'fleet-registry.json', 'fleet-locations.json', 'token-usage.json',
    'tailnet-windows.json', 'activity.json', 'model-status.json', 'sparkdash.json',
}
REQUIRED = {
    'README.md', 'LICENSE', 'CHANGELOG.md', 'viewer/index.html',
    'viewer/fleet-app.mjs', 'viewer/fleet-model.mjs',
    'viewer/fleet-locations.mjs', 'viewer/fleet-workspace.mjs',
    'viewer/fleet-pages.mjs', 'collector/macfleet.py',
    'viewer/fleet-model-status.mjs', 'collector/model_status.py',
    'viewer/fleet-usage.mjs', 'collector/fleet_usage.py',
    'viewer/fleet-sparkdash.mjs', 'collector/sparkdash.py',
    'viewer/fleet-read.mjs',
}


def check_archive(path):
    if Path(path).stat().st_size > 20 * 1024 * 1024:
        raise ValueError('Archive exceeds the source package size limit')
    files = set()
    root = None
    total = 0
    with tarfile.open(path, 'r:gz') as archive:
        for index, member in enumerate(archive):
            if index >= 1000:
                raise ValueError('Archive contains too many entries')
            name = member.name
            parts = PurePosixPath(name).parts
            if not parts or name.startswith('/') or '\\' in name or '..' in parts or any(c in name for c in '\x00\r\n'):
                raise ValueError('Unsafe archive path')
            if not re.fullmatch(r'(?:workman-fleet|macfleet-dash)-v\d+\.\d+\.\d+', parts[0]):
                raise ValueError('Archive must have one versioned application folder')
            if root is None:
                root = parts[0]
            if parts[0] != root:
                raise ValueError('Archive mixes application folders')
            if not member.isfile() and not member.isdir():
                raise ValueError('Archive links and special files are not supported')
            relative = '/'.join(parts[1:])
            if any(part in {'state', '.git', '__pycache__', 'secrets', 'credentials'} or part.startswith('.env') for part in parts[1:]):
                raise ValueError('Private state or environment directory in public archive')
            if parts[-1] in PRIVATE_NAMES or relative in {'viewer/data.json', 'viewer/windows.json'} or parts[-1].endswith(('.pem', '.key', '.pyc')):
                raise ValueError('Private configuration or runtime file in public archive: ' + relative)
            if member.isfile():
                if relative in files:
                    raise ValueError('Duplicate file in archive')
                files.add(relative)
                total += member.size
                if member.size > 10 * 1024 * 1024 or total > 25 * 1024 * 1024:
                    raise ValueError('Archive expanded size exceeds source limits')
        missing = REQUIRED - files
        if missing:
            raise ValueError('Public source is incomplete: ' + ', '.join(sorted(missing)))
    return {'root': root, 'files': len(files), 'expandedBytes': total}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_archive(args.archive)
    except (OSError, ValueError, tarfile.TarError) as error:
        parser.exit(2, 'Public archive check failed: ' + str(error) + '\n')
    print('Public archive verified: {files} source files; private runtime files excluded ({root}).'.format(**result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
