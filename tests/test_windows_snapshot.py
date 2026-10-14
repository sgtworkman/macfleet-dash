import base64
import copy
from datetime import datetime,timezone,timedelta
import gzip
import importlib.util
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bridge',ROOT/'collector/windows_snapshot.py')
bridge=importlib.util.module_from_spec(spec);spec.loader.exec_module(bridge)
NOW=datetime(2026,10,14,18,tzinfo=timezone.utc)
HOST={'id':'fixture-server','name':'Fixture server','expectedComputerName':'FIXTURE-PC','endpoint':'http://192.168.56.10:5985/wsman','kind':'server','site':'Unassigned','enabled':True}
def sample():return {'schema':'workman.windows-fleet-pilot.v1','host':'FIXTURE-PC','status':'available','units':'GiB','observedAt':NOW.isoformat(),'os':'Microsoft Windows Server','cpuUsedPct':4,'ramGb':16,'memUsedGb':8,'uptimeDays':2,'disks':[{'drive':'C:','status':'available','totalGb':100,'usedGb':70,'freeGb':30},{'drive':'E:','status':'available','totalGb':500,'usedGb':100,'freeGb':400}],'networkState':'available','network':[{'name':'NIC','receivedBytes':1000,'sentBytes':500}],'services':[],'gpuUtilPct':None,'temperatureC':None,'powerW':None}
class BridgeTests(unittest.TestCase):
    def test_config_rejects_duplicate_hosts_public_urls_credentials_and_unsafe_names(self):
        config={'schema':'macfleet.windows.config.v1','hosts':[HOST]}
        self.assertEqual(bridge.checked_config(config),config)
        for update in [{'endpoint':'http://8.8.8.8:5985/wsman'},{'endpoint':'http://user:secret@192.168.56.10:5985/wsman'},{'expectedComputerName':"BAD'; exit"},{'kind':'guessed'}]:
            with self.assertRaises(ValueError):bridge.checked_config({'schema':config['schema'],'hosts':[dict(HOST,**update)]})
        with self.assertRaises(ValueError):bridge.checked_config({'schema':config['schema'],'hosts':[HOST,HOST]})
        with self.assertRaises(ValueError):bridge.checked_config({'schema':config['schema'],'hosts':[HOST,dict(HOST,id='other-alias',expectedComputerName='fixture-pc')]})
    def test_exact_collector_runs_in_memory_with_bounded_encoded_command(self):
        script=(ROOT/'windows/collect-fleet.ps1').read_text();command=bridge.bootstrap(script,'FIXTURE-PC')
        payload=re.search("FromBase64String\\('([^']+)'\\)",command)[1]
        self.assertEqual(gzip.decompress(base64.b64decode(payload)).decode(),script)
        self.assertLess(len(base64.b64encode(command.encode('utf-16-le')))+100,8192)
        self.assertNotIn('::new(,',command)
        for disallowed in ['Set-ExecutionPolicy','Invoke-WebRequest','WriteAllText','Start-Service','schtasks']:self.assertNotIn(disallowed,command)
    def test_disk_totals_reconcile_and_adapter_counters_are_not_summed(self):
        row=bridge.project_sample(sample(),HOST,NOW)
        self.assertEqual(row['diskTotalGb'],600);self.assertEqual(row['diskFreeGb'],430);self.assertEqual(row['diskUsedGb'],170)
        self.assertIsNone(row['netRxMbps']);self.assertIsNone(row['network'][0]['rxMBps'])
        newer=sample();newer['network'][0]['receivedBytes']=2001000
        row2=bridge.project_sample(newer,HOST,NOW+timedelta(seconds=2),row)
        self.assertEqual(row2['network'][0]['rxMBps'],1)
        newer['network'][0]['receivedBytes']=1
        self.assertIsNone(bridge.project_sample(newer,HOST,NOW+timedelta(seconds=2),row)['network'][0]['rxMBps'])
        newer['network'][0]['receivedBytes']=2001000;newer['uptimeDays']=0.1
        self.assertIsNone(bridge.project_sample(newer,HOST,NOW+timedelta(seconds=2),row)['network'][0]['rxMBps'])
    def test_bad_host_clock_is_preserved_and_flagged_not_relabelled_as_valid(self):
        data=sample();data['observedAt']=(NOW+timedelta(minutes=30)).isoformat()
        with self.assertRaises(ValueError):bridge.pilot.validate(data,'FIXTURE-PC',now=NOW)
        row=bridge.project_sample(data,HOST,NOW)
        self.assertEqual(row['clockState'],'skewed');self.assertEqual(row['clockSkewSeconds'],1800)
        self.assertEqual(row['sourceObservedAt'],data['observedAt']);self.assertEqual(row['receivedAt'],bridge.iso(NOW))
        self.assertIn('authenticated poll',row['freshnessBasis'])
    def test_partial_disks_do_not_become_a_whole_machine_total(self):
        data=sample();data['status']='partial';data['disks'][1]={'drive':'E:','status':'unavailable','totalGb':None,'usedGb':None,'freeGb':None}
        row=bridge.project_sample(data,HOST,NOW);self.assertIsNone(row['diskFreeGb'])
        data['disks'][1]=copy.deepcopy(data['disks'][0])
        with self.assertRaises(ValueError):bridge.project_sample(data,HOST,NOW)
    def test_pending_hosts_never_connect_or_create_usage(self):
        host=dict(HOST,enabled=False,pendingReason='Approved access pending')
        def forbidden(*args,**kwargs):raise AssertionError('Pending host was contacted')
        row=bridge.poll_one(host,('not-a-credential','not-a-credential'),'',None,forbidden,now=lambda:NOW)
        self.assertEqual(row['status'],'not-enrolled');self.assertIsNone(row['observedAt']);self.assertNotIn('cpuUsedPct',row)
    def test_failed_poll_retains_original_metrics_and_timestamps_not_a_fresh_success(self):
        previous=bridge.project_sample(sample(),HOST,NOW)
        def failure(*args,**kwargs):raise RuntimeError('Sensitive provider output must not be copied')
        row=bridge.poll_one(HOST,('not-a-credential','not-a-credential'),'',previous,failure,now=lambda:NOW+timedelta(minutes=5))
        self.assertEqual(row['status'],'unavailable');self.assertEqual(row['observedAt'],previous['observedAt'])
        self.assertEqual(row['probeError'],'RuntimeError');self.assertNotIn('Sensitive',json.dumps(row))
    def test_session_requires_encryption_and_never_exports_endpoint_or_credentials(self):
        calls=[]
        class Session:
            def __init__(self,*args,**kwargs):calls.append((args,kwargs))
            def run_ps(self,command):return type('Response',(),{'status_code':0,'std_out':json.dumps(sample()).encode(),'std_err':b''})()
        row=bridge.poll_one(HOST,('not-a-credential','not-a-credential'),(ROOT/'windows/collect-fleet.ps1').read_text(),None,Session,now=lambda:NOW)
        self.assertEqual(row['status'],'available');self.assertEqual(calls[0][1]['message_encryption'],'always')
        self.assertEqual(calls[0][1]['transport'],'ntlm');self.assertNotIn('endpoint',row);self.assertNotIn('not-a-credential',json.dumps(row))
    def test_changed_target_identity_does_not_inherit_another_machines_metrics(self):
        previous=bridge.project_sample(sample(),HOST,NOW)
        def failure(*args,**kwargs):raise RuntimeError('Unreachable')
        target=dict(HOST,expectedComputerName='OTHER-PC')
        result=bridge.collect({'schema':'macfleet.windows.config.v1','hosts':[target]},('not-a-credential','not-a-credential'),{'hosts':[previous],'history':bridge.update_history(None,[previous],NOW)},failure,now=lambda:NOW)
        row=result['hosts'][0]
        self.assertEqual(row['hostname'],'OTHER-PC');self.assertNotIn('receivedAt',row);self.assertNotIn('cpuUsedPct',row)
        self.assertEqual(result['history']['hosts']['fixture-server'],[]);self.assertEqual(result['history']['week']['fixture-server'],[])
    def test_unavailable_hours_stay_missing_and_history_is_bounded(self):
        row=bridge.project_sample(sample(),HOST,NOW)
        history=bridge.update_history(None,[row],NOW)
        history2=bridge.update_history(history,[dict(row,status='unavailable')],NOW+timedelta(minutes=5))
        self.assertEqual(history2['hosts']['fixture-server'],history['hosts']['fixture-server'])
        self.assertEqual(bridge.update_history(history,[dict(row,status='unavailable')],NOW+timedelta(days=8))['week']['fixture-server'],[])

if __name__=='__main__':unittest.main()
