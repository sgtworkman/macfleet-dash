"""Publish a private aggregate snapshot for the existing loopback static viewer.
Called by WCC's already-running local refresh, not a new daemon or remote probe.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit
from token_usage import read_usage

ROOT=Path(__file__).resolve().parents[1]
def publish_snapshot(output,payload):
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,prefix='.token-usage-',delete=False) as stream:
            temporary=Path(stream.name)
            json.dump(payload,stream,allow_nan=False)
            stream.flush();os.fsync(stream.fileno())
        os.chmod(temporary,0o600)
        os.replace(temporary,output)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()

def main():
    # Check the existing owner/bind; do not publish on a public/LAN listener.
    result=subprocess.run(['/usr/sbin/lsof','-nP','-iTCP:8791','-sTCP:LISTEN','-Fn'],capture_output=True,text=True,timeout=5)
    bindings=[line[1:] for line in result.stdout.splitlines() if line.startswith('n')]
    if result.returncode or not bindings or any(binding not in ('127.0.0.1:8791','[::1]:8791') for binding in bindings):
        raise SystemExit('Token snapshot not published: existing loopback viewer unverified')
    import macfleet
    config=macfleet.load_config(str(ROOT/'macfleet.toml'))
    targets={'localhost':'Cockpit (this Mac)','127.0.0.1':'Cockpit (this Mac)'}
    for key,entry in macfleet._host_entries(config):
        name=entry.get('name') or key
        if entry.get('ts_ip'):targets[entry['ts_ip']]=name
        if entry.get('model_url'):
            host=urlsplit(entry['model_url']).hostname
            if host:targets[host]=name
    payload=read_usage(target_names=targets)
    publish_snapshot(ROOT/'viewer/token-usage.json',payload)
    print(json.dumps({'status':payload['status'],'observedAt':payload['observedAt'],'groups':len(payload['groups'])}))

if __name__=='__main__':main()
