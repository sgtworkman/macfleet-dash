from datetime import datetime,timezone,timedelta
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('pilot',ROOT/'windows/validate-pilot.py');pilot=importlib.util.module_from_spec(spec);spec.loader.exec_module(pilot)
NOW=datetime.now(timezone.utc)
def sample():
    return {'schema':'workman.windows-fleet-pilot.v1','host':'FIXTURE-PC','status':'available','units':'GiB','observedAt':NOW.isoformat(),'cpuUsedPct':0,'ramGb':16,'memUsedGb':8,'uptimeDays':1,'disks':[{'drive':'C:','status':'available','totalGb':100,'usedGb':70,'freeGb':30}],'networkState':'available','network':[{'name':'Fixture','receivedBytes':0,'sentBytes':0}],'gpuUtilPct':None,'temperatureC':None,'powerW':None}
class PilotTests(unittest.TestCase):
    def test_real_powershell_roundtrip_timestamp_precision_on_python39(self):
        d=sample();d['observedAt']='2026-10-14T07:30:00.1234567+00:00'
        at=datetime(2026,10,14,7,30,1,tzinfo=timezone.utc)
        result=pilot.validate(d,'FIXTURE-PC',at)
        self.assertEqual(result['observedAt'],d['observedAt']);self.assertFalse(result['stale'])
        d['observedAt']='2026-10-14T07:30:00.12345678+00:00'
        with self.assertRaises(ValueError):pilot.validate(d,'FIXTURE-PC',at)
    def test_sample_reconciles_zero_is_real_and_scope_is_not_enrollment(self):
        d=pilot.validate(sample(),'fixture-pc',NOW);self.assertEqual(d['status'],'sample-validated');self.assertIn('not installation',d['scope'])
    def test_identity_schema_clock_and_capacity_failures_are_rejected(self):
        for change in ({'host':'WRONG'},{'schema':'x'},{'cpuUsedPct':101},{'memUsedGb':20},{'cpuUsedPct':False},{'ramGb':'16'},{'observedAt':(NOW+timedelta(hours=1)).isoformat()}):
            d=sample();d.update(change)
            with self.assertRaises(ValueError):pilot.validate(d,'FIXTURE-PC',NOW)
        d=sample();d['disks'][0]['usedGb']=2
        with self.assertRaises(ValueError):pilot.validate(d,'FIXTURE-PC',NOW)
    def test_nulls_preserved_but_available_headers_cannot_cover_missing_rows(self):
        d=sample();d.update(status='partial',cpuUsedPct=None);self.assertEqual(pilot.validate(d,'FIXTURE-PC',NOW)['sampleState'],'partial');d['status']='available'
        with self.assertRaises(ValueError):pilot.validate(d,'FIXTURE-PC',NOW)
        d=sample();d['network'][0]['receivedBytes']=None
        with self.assertRaises(ValueError):pilot.validate(d,'FIXTURE-PC',NOW)
    def test_stale_sample_is_labeled_not_current(self):
        d=sample();d['observedAt']=(NOW-timedelta(hours=1)).isoformat();self.assertTrue(pilot.validate(d,'FIXTURE-PC',NOW)['stale'])
    def test_prepared_script_is_local_read_only_with_identity_guard_first(self):
        script=(ROOT/'windows/collect-fleet.ps1').read_text();self.assertLess(script.index('Target identity mismatch'),script.index('$pilotOs = Read-LocalCim'))
        for verb in ('Set-CimInstance','Invoke-CimMethod','New-CimSession','New-NetFirewallRule','Register-ScheduledTask','Set-ExecutionPolicy','Invoke-WebRequest','Start-Service','Stop-Service','Restart-Computer','Get-Process','Get-Content','Out-File'):self.assertNotIn(verb,script)
        self.assertNotRegex(script,r'-ComputerName\b|-Credential\b|-CimSession\b');self.assertIn('gpuUtilPct=$null',script);self.assertIn("backupState='not collected'",script)
if __name__=='__main__':unittest.main(verbosity=2)
