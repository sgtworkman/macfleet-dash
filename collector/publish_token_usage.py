"""Publish a private aggregate snapshot for the existing loopback static viewer.
Called by WCC's existing refresh; no new daemon or remote health probe.
Optional configured model endpoints receive metadata-only GET requests.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit
from token_usage import read_usage
from model_status import read_models

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
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--viewer-port',type=int,default=8791)
    parser.add_argument('--config',type=Path)
    args=parser.parse_args()
    if not 1024<=args.viewer_port<=65535:
        raise SystemExit('Existing unprivileged loopback viewer port required')
    # Check the existing owner/bind; do not publish on a public/LAN listener.
    result=subprocess.run(['/usr/sbin/lsof','-nP','-iTCP:'+str(args.viewer_port),'-sTCP:LISTEN','-Fn'],capture_output=True,text=True,timeout=5)
    bindings=[line[1:] for line in result.stdout.splitlines() if line.startswith('n')]
    if result.returncode or not bindings or any(binding not in ('127.0.0.1:'+str(args.viewer_port),'[::1]:'+str(args.viewer_port)) for binding in bindings):
        raise SystemExit('Token snapshot not published: existing loopback viewer unverified')
    import macfleet
    config_path=args.config or next((path for path in (ROOT/'macfleet.toml',ROOT/'macfleet.json') if path.is_file()),None)
    if config_path is None:
        raise SystemExit('Create your own macfleet.toml or macfleet.json first')
    config=macfleet.load_config(str(config_path))
    targets={'localhost':'Cockpit (this Mac)','127.0.0.1':'Cockpit (this Mac)'}
    for key,entry in macfleet._host_entries(config):
        name=entry.get('name') or key
        if entry.get('ts_ip'):targets[entry['ts_ip']]=name
        if entry.get('model_url'):
            host=urlsplit(entry['model_url']).hostname
            if host:targets[host]=name
    payload=read_usage(target_names=targets)
    publish_snapshot(ROOT/'viewer/token-usage.json',payload)
    models=read_models(config)
    publish_snapshot(ROOT/'viewer/model-status.json',models)
    print(json.dumps({'status':payload['status'],'observedAt':payload['observedAt'],'groups':len(payload['groups']),'modelEndpoints':len(models['hosts'])}))

if __name__=='__main__':main()
