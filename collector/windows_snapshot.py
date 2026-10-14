"""Read existing private WinRM endpoints; publish no credentials or remote paths.

Optional pywinrm client is needed only for this bridge. Nothing is installed on
Windows: the reviewed native collector executes in memory using encrypted NTLM.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import importlib.util
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('windows_pilot',ROOT/'windows/validate-pilot.py')
pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)
SCHEMA='macfleet.windows.v1'

def utc():return datetime.now(timezone.utc)
def iso(at):return at.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')

def checked_config(value):
    if not isinstance(value,dict) or value.get('schema')!='macfleet.windows.config.v1' or not isinstance(value.get('hosts'),list):
        raise ValueError('Windows configuration schema unverified')
    seen=set();native_names=set()
    for host in value['hosts']:
        if not isinstance(host,dict) or not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,62}',str(host.get('id',''))) or host['id'] in seen:raise ValueError('Windows host identity unverified or duplicated')
        seen.add(host['id'])
        if host.get('kind') not in ('server','range','computer') or not isinstance(host.get('site'),str) or not isinstance(host.get('enabled'),bool):raise ValueError('Host classification/enrollment unverified')
        if host['enabled']:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}',str(host.get('expectedComputerName',''))):raise ValueError('Expected computer name unverified')
            native_name=host['expectedComputerName'].casefold()
            if native_name in native_names:raise ValueError('Duplicate monitored Windows computer')
            native_names.add(native_name)
            url=urlsplit(str(host.get('endpoint','')))
            if url.username or url.password or url.query or url.fragment or url.path!='/wsman':raise ValueError('Unsupported or credential-bearing endpoint')
            try:address=ipaddress.ip_address(url.hostname)
            except ValueError:raise ValueError('Use an exact private endpoint address')
            if not address.is_private or address.is_loopback or address.is_multicast or address.is_unspecified or url.scheme not in ('http','https') or url.port not in (5985,5986):raise ValueError('WinRM endpoint is not a private supported address')
        elif not isinstance(host.get('pendingReason'),str):raise ValueError('Pending host reason missing')
    return value

def bootstrap(script,expected_name):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}',expected_name):raise ValueError('Unsafe target identity')
    encoded=base64.b64encode(gzip.compress(script.encode('utf-8'),compresslevel=9)).decode('ascii')
    # CompressionMode.Decompress is enum value 0. Its short spelling keeps
    # longer exact Windows computer names below the native command bound.
    command="$m=[IO.MemoryStream]::new([Convert]::FromBase64String('"+encoded+"'));$r=[IO.StreamReader]::new([IO.Compression.GZipStream]::new($m,[IO.Compression.CompressionMode]0));& ([ScriptBlock]::Create($r.ReadToEnd())) -ExpectedComputerName '"+expected_name+"'"
    # WinRM's cmd host has an 8191-character command-line limit. Execute the
    # same reviewed script in memory, not a shortened/less strict collector.
    if len(base64.b64encode(command.encode('utf-16-le')))+100>=8192:raise ValueError('Collector exceeds the supported encoded command bound')
    return command

def base_row(host):
    return {'host':host['id'],'name':host.get('name') or host.get('expectedComputerName') or host['id'],'hostname':host.get('expectedComputerName'),'kind':host['kind'],'site':host['site'],'platform':'windows' if host['enabled'] else host.get('platform','windows'),'source':'windows-winrm' if host['enabled'] else 'registry','enrollment':'enrolled' if host['enabled'] else 'not-enrolled','expectedHours':host.get('expectedHours')}

def project_sample(sample,host,received_at,previous=None):
    source_at=pilot.validate_structure(sample,host['expectedComputerName'])
    row=base_row(host)
    skew=(source_at-received_at).total_seconds()
    row.update({'status':'available','sampleState':sample['status'],'observedAt':iso(received_at),'receivedAt':iso(received_at),'sourceObservedAt':sample['observedAt'],'freshnessBasis':'cockpit receipt of this authenticated poll','clockSkewSeconds':round(skew,1),'clockState':'skewed' if abs(skew)>90 else 'verified','os':sample.get('os'),'ramGb':sample['ramGb'],'memUsedGb':sample['memUsedGb'],'cpuUsedPct':sample['cpuUsedPct'],'uptimeDays':sample['uptimeDays'],'gpuUtilPct':sample['gpuUtilPct'],'swapUsedGb':None,'power':None,'backup':None,'disks':sample['disks'],'services':sample.get('services',[]),'network':[],'networkState':sample['networkState'],'note':host.get('note')})
    drives=sample['disks']
    names=[d.get('drive') for d in drives]
    if any(not isinstance(n,str) or not re.fullmatch(r'[A-Za-z]:',n) for n in names) or len(set(n.casefold() for n in names))!=len(names):raise ValueError('Disk identities unverified or duplicated')
    known=bool(drives) and all(d['status']=='available' for d in drives)
    row.update({key:round(sum(d[field] for d in drives),3) if known else None for key,field in [('diskTotalGb','totalGb'),('diskFreeGb','freeGb'),('diskUsedGb','usedGb')]})
    old={a['name']:a for a in (previous or {}).get('network',[]) if isinstance(a,dict) and isinstance(a.get('name'),str)}
    elapsed=None
    if previous and previous.get('receivedAt'):
        try:elapsed=(received_at-pilot.sample_time(previous['receivedAt'])).total_seconds()
        except (ValueError,TypeError):pass
    if previous and pilot.metric(previous.get('uptimeDays')) and previous.get('uptimeDays') is not None and sample['uptimeDays'] is not None and sample['uptimeDays']<previous['uptimeDays']:elapsed=None
    adapters=set()
    for adapter in sample['network']:
        name=adapter.get('name')
        if not isinstance(name,str) or not name or name in adapters:raise ValueError('Adapter identity unverified or duplicated')
        adapters.add(name);current=dict(adapter)
        for field,rate in [('receivedBytes','rxMBps'),('sentBytes','txMBps')]:
            before=old.get(name,{}).get(field);after=adapter[field]
            current[rate]=round((after-before)/elapsed/1e6,3) if elapsed and elapsed>=1 and pilot.metric(before) and before is not None and after is not None and after>=before else None
        row['network'].append(current)
    # Per-adapter counters/rates are never added together; virtual adapters
    # can represent the same traffic as physical adapters.
    row['netRxMbps']=None;row['netTxMbps']=None
    return row

def poll_one(host,credentials,script,previous,session_factory,now=utc):
    row=base_row(host)
    if not host['enabled']:
        row.update({'status':'not-enrolled','observedAt':None,'pendingReason':host['pendingReason']})
        return row
    try:
        session=session_factory(host['endpoint'],auth=credentials,transport='ntlm',message_encryption='always',operation_timeout_sec=15,read_timeout_sec=20,proxy=None)
        response=session.run_ps(bootstrap(script,host['expectedComputerName']))
        if response.status_code!=0:raise ValueError('Native collector did not complete')
        if len(response.std_out)>1024*1024:raise ValueError('Native response exceeds size bound')
        sample=json.loads(response.std_out.decode('utf-8-sig'))
        return project_sample(sample,host,now(),previous)
    except Exception as error:
        # Retain actual last successful readings/timestamps. An auth/schema
        # failure is not proof that Windows is powered off; report No answer.
        retained={k:v for k,v in (previous or {}).items() if k not in ('host','name','hostname','kind','site','enrollment','source','platform','status','lastAttemptAt','probeError')}
        codes=sorted({int(code) for code in re.findall(r'\[Errno (-?\d+)\]',str(error))})
        row.update(retained);row.update({'status':'unavailable','lastAttemptAt':iso(now()),'probeError':type(error).__name__,'probeErrno':codes})
        return row

def collect(config,credentials,previous=None,session_factory=None,now=utc):
    checked_config(config)
    if session_factory is None:
        import winrm
        session_factory=winrm.Session
    old={r['host']:r for r in (previous or {}).get('hosts',[]) if isinstance(r,dict) and isinstance(r.get('host'),str)}
    changed={host['id'] for host in config['hosts'] if host['enabled'] and host['id'] in old and str(old[host['id']].get('hostname','')).casefold()!=host['expectedComputerName'].casefold()}
    script=(ROOT/'windows/collect-fleet.ps1').read_text(encoding='utf-8')
    def read(host):
        previous_host=old.get(host['id'])
        if host['id'] in changed:previous_host=None
        return poll_one(host,credentials,script,previous_host,session_factory,now)
    with ThreadPoolExecutor(max_workers=2) as pool:rows=list(pool.map(read,config['hosts']))
    prior_history=(previous or {}).get('history')
    if changed and isinstance(prior_history,dict):prior_history={period:{key:points for key,points in prior_history.get(period,{}).items() if key not in changed} for period in ('hosts','week')}
    return {'schema':SCHEMA,'bridgeVersion':'0.1.0','observedAt':iso(now()),'hosts':rows,'history':update_history(prior_history,rows,now()),'scope':'Existing private WinRM endpoints only; read-only local CIM collection. Source clock and receipt freshness are separate. Pending hosts are not monitored.'}

def update_history(previous,rows,now):
    previous=previous if isinstance(previous,dict) else {}
    result={'hosts':{},'week':{}}
    for row in rows:
        key=row['host']
        for period,hours,limit in [('hosts',24,300),('week',168,2100)]:
            points=list(previous.get(period,{}).get(key,[]))
            if row['status']=='available':points.append([row['receivedAt'],row['cpuUsedPct'],row['gpuUtilPct'],row['memUsedGb'],None,None,None])
            kept={}
            for point in points:
                try:age=(now-pilot.sample_time(point[0])).total_seconds()
                except (ValueError,TypeError,IndexError):continue
                if 0<=age<=hours*3600:kept[point[0]]=point
            result[period][key]=[kept[k] for k in sorted(kept)][-limit:]
    return result

def atomic_json(output,value):
    output=Path(output);temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output.parent,prefix='.windows-fleet-',delete=False) as stream:
            temporary=Path(stream.name);json.dump(value,stream,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        os.chmod(temporary,0o600);os.replace(temporary,output)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--credentials-file',required=True);parser.add_argument('--output',default=str(ROOT/'viewer/windows.json'))
    args=parser.parse_args()
    config=checked_config(json.loads(Path(args.config).read_text(encoding='utf-8')))
    credentials_path=Path(args.credentials_file)
    if credentials_path.stat().st_mode & 0o077 or credentials_path.stat().st_uid!=os.getuid():raise ValueError('Credential file must be owner-only')
    # Existing operator-selected dotenv file only. Values never enter output,
    # exceptions, arguments, receipts, snapshots or source-control files.
    from dotenv import dotenv_values
    env=dotenv_values(credentials_path)
    credentials=(env.get('WORKMAN_WINDOWS_SERVER_USERNAME'),env.get('WORKMAN_WINDOWS_SERVER_PASSWORD'))
    if not all(credentials):raise ValueError('Required Windows inventory credentials are unavailable')
    listener=subprocess.run(['/usr/sbin/lsof','-nP','-iTCP:8791','-sTCP:LISTEN','-Fn'],capture_output=True,text=True,timeout=5)
    binds=[line[1:] for line in listener.stdout.splitlines() if line.startswith('n')]
    if listener.returncode or not binds or any(x not in ('127.0.0.1:8791','[::1]:8791') for x in binds):raise ValueError('Existing loopback viewer binding unverified')
    output=Path(args.output)
    # This client-side bridge has one publisher, even if a diagnostic command
    # overlaps its scheduled run. The original health collector is unaffected.
    import fcntl
    with open(ROOT/'state/windows-bridge.lock','a') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('Windows publisher already running')
        try:previous=json.loads(output.read_text(encoding='utf-8'))
        except (FileNotFoundError,json.JSONDecodeError):previous=None
        value=collect(config,credentials,previous)
        atomic_json(output,value)
    print(json.dumps({'status':'snapshot-published','observedAt':value['observedAt'],'responding':sum(r['status']=='available' for r in value['hosts']),'monitored':sum(r['enrollment']=='enrolled' for r in value['hosts']),'pending':sum(r['enrollment']=='not-enrolled' for r in value['hosts'])}))

if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Windows snapshot not published: '+type(error).__name__)
