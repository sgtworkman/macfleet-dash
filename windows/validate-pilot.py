"""Validate captured pilot JSON; never install or enroll a Windows host."""
import argparse
from datetime import datetime, timezone
import json
import math
import re
from pathlib import Path

def metric(value):
    return value is None or isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and value>=0

def sample_time(text):
    match=re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,7}))?(Z|[+-]\d{2}:\d{2})',text)
    if not match:raise ValueError('Timestamp format unverified')
    fraction='.'+match[2].ljust(6,'0')[:6] if match[2] else ''
    return datetime.fromisoformat(match[1]+fraction+match[3].replace('Z','+00:00'))

def validate_structure(sample,expected_host):
    """Validate identity/metrics only; this does not validate clock or freshness."""
    if not isinstance(sample,dict) or sample.get('schema')!='workman.windows-fleet-pilot.v1':raise ValueError('Unrecognized pilot schema')
    if str(sample.get('host','')).casefold()!=expected_host.casefold():raise ValueError('Host identity mismatch')
    if sample.get('units')!='GiB' or sample.get('status') not in ('available','partial','unavailable'):raise ValueError('Units or sample state unverified')
    try:
        # .NET's round-trip format uses seven fractional digits. Python 3.9
        # accepts at most microseconds; preserve the source text in the receipt.
        at=sample_time(sample['observedAt'])
    except (KeyError,ValueError,TypeError):raise ValueError('Sample timestamp unverified')
    for field in ('cpuUsedPct','ramGb','memUsedGb','uptimeDays','gpuUtilPct','temperatureC','powerW'):
        if field not in sample or not metric(sample[field]):raise ValueError('Invalid or missing metric: '+field)
    cpu=sample['cpuUsedPct']
    if cpu is not None and cpu>100:raise ValueError('CPU outside 0–100')
    total,used=sample['ramGb'],sample['memUsedGb']
    if (total is None)!=(used is None) or total is not None and (total<=0 or used>total):raise ValueError('Memory capacity does not reconcile')
    disks=sample.get('disks')
    if not isinstance(disks,list):raise ValueError('Disk rows unverified')
    for disk in disks:
        if not isinstance(disk,dict) or disk.get('status') not in ('available','unavailable'):raise ValueError('Disk state unverified')
        values=[disk.get(k) for k in ('totalGb','usedGb','freeGb')]
        if disk['status']=='unavailable':
            if values!=[None,None,None]:raise ValueError('Unavailable disk carries numeric values')
        elif any(v is None or not metric(v) for v in values) or values[0]<=0 or abs(values[1]+values[2]-values[0])>0.002:raise ValueError('Disk capacity does not reconcile')
    if sample['status']=='available' and (cpu is None or total is None or sample['uptimeDays'] is None or not disks or any(d['status']!='available' for d in disks)):raise ValueError('Available header conflicts with data rows')
    networks=sample.get('network')
    if not isinstance(networks,list) or sample.get('networkState') not in ('available','partial','unavailable'):raise ValueError('Network rows unverified')
    for adapter in networks:
        if not isinstance(adapter,dict) or any(k not in adapter or not metric(adapter[k]) for k in ('receivedBytes','sentBytes')):raise ValueError('Network counters unverified')
    if sample['networkState']=='available' and (not networks or any(a[k] is None for a in networks for k in ('receivedBytes','sentBytes'))):raise ValueError('Available network header conflicts with rows')
    if sample['status']=='available' and sample['networkState']!='available':raise ValueError('Available sample conflicts with network state')
    return at

def validate(sample,expected_host,now=None):
    at=validate_structure(sample,expected_host)
    now=now or datetime.now(timezone.utc)
    if at.tzinfo is None or (at-now).total_seconds()>90:raise ValueError('Sample clock unverified')
    return {'status':'sample-validated','host':sample['host'],'observedAt':sample['observedAt'],'sampleState':sample['status'],'stale':(now-at).total_seconds()>600,'scope':'JSON identity, metric and arithmetic validation only; not installation, live-host or persistence proof'}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--expected-host',required=True);parser.add_argument('sample');args=parser.parse_args();path=Path(args.sample)
    if path.stat().st_size>1024*1024:raise ValueError('Sample exceeds 1 MiB')
    print(json.dumps(validate(json.loads(path.read_text(encoding='utf-8-sig')),args.expected_host)))
if __name__=='__main__':
    try:main()
    except (ValueError,OSError,json.JSONDecodeError) as error:raise SystemExit(str(error))
