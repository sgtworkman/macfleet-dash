"""Run a pinned official Gitleaks CLI with isolated temporary files and full history."""
import argparse
import hashlib
import io
import os
from pathlib import Path
import platform
import subprocess
import tarfile
import tempfile
import urllib.request

VERSION = '8.30.1'
# GitHub release asset SHA256 digests from gitleaks/gitleaks v8.30.1.
DIGESTS = {
    ('darwin', 'arm64'): 'b40ab0ae55c505963e365f271a8d3846efbc170aa17f2607f13df610a9aeb6a5',
    ('darwin', 'x64'): 'dfe101a4db2255fc85120ac7f3d25e4342c3c20cf749f2c20a18081af1952709',
    ('linux', 'arm64'): 'e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080',
    ('linux', 'x64'): '551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb',
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed', type=Path)
    parser.add_argument('--report', type=Path, default=Path('results.sarif'))
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='fleet-gitleaks-', dir=os.environ.get('RUNNER_TEMP')) as directory:
        binary = args.installed
        if binary is None:
            system = platform.system().lower()
            architecture = {'aarch64':'arm64', 'arm64':'arm64', 'x86_64':'x64', 'amd64':'x64'}.get(platform.machine().lower())
            digest = DIGESTS.get((system, architecture))
            if not digest:
                raise RuntimeError('No verified scanner build for this host')
            name = 'gitleaks_'+VERSION+'_'+system+'_'+architecture+'.tar.gz'
            url = 'https://github.com/gitleaks/gitleaks/releases/download/v'+VERSION+'/'+name
            with urllib.request.urlopen(url, timeout=60) as response:
                data = response.read(30*1024*1024+1)
            if len(data)>30*1024*1024 or hashlib.sha256(data).hexdigest()!=digest:
                raise RuntimeError('Scanner archive verification failed')
            with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
                members = [m for m in archive if m.name == 'gitleaks']
                if len(members)!=1 or not members[0].isfile() or members[0].size>80*1024*1024:
                    raise RuntimeError('Scanner binary identity unverified')
                binary = Path(directory)/'gitleaks'
                binary.write_bytes(archive.extractfile(members[0]).read())
                binary.chmod(0o700)
        if subprocess.check_output([str(binary),'version'], text=True).strip()!=VERSION:
            raise RuntimeError('Scanner version does not match pin')
        return subprocess.call([str(binary),'detect','--source','.','--redact=100','--exit-code=2',
                                '--report-format=sarif','--report-path='+str(args.report),'--no-banner'])


if __name__ == '__main__':
    raise SystemExit(main())
