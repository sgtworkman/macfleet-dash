import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('operations', Path(__file__).resolve().parents[1]/'collector/operations.py')
operations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(operations)


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.now = 1800000000
        self.row = {'host': 'computer-a', 'name': 'Computer A', 'status': 'available',
                    'observedAt': operations.iso(self.now), 'diskFreeGb': 100,
                    'ramGb': 16, 'memUsedGb': 4, 'site': 'Office'}
        self.engine = operations.Operations(self.root/'operations.sqlite3', hold_seconds=60)

    def test_alert_holds_recovers_and_survives_restart_without_duplicate_events(self):
        row = dict(self.row, diskFreeGb=5)
        first = self.engine.evaluate([row], self.now)
        self.assertEqual(first['alerts'][0]['state'], 'pending')
        self.assertEqual(first['events'], [])
        fired = self.engine.evaluate([row], self.now+61)
        self.assertEqual(fired['alerts'][0]['state'], 'firing')
        self.assertEqual([e['kind'] for e in fired['events']], ['alert.firing'])
        restarted = operations.Operations(self.root/'operations.sqlite3', hold_seconds=60)
        repeated = restarted.evaluate([row], self.now+90)
        self.assertEqual(len(repeated['events']), 1)
        clearing = restarted.evaluate([self.row], self.now+120)
        self.assertEqual(clearing['alerts'][0]['state'], 'firing')
        cleared = restarted.evaluate([self.row], self.now+181)
        self.assertEqual(cleared['alerts'], [])
        self.assertEqual(cleared['events'][0]['kind'], 'alert.resolved')

    def test_missing_resource_read_does_not_resolve_a_known_fault(self):
        low = dict(self.row, diskFreeGb=5)
        self.engine.evaluate([low], self.now)
        self.engine.evaluate([low], self.now+61)
        missing = dict(self.row, status='unavailable')
        result = self.engine.evaluate([missing], self.now+120)
        disk = next(a for a in result['alerts'] if a['rule'] == 'disk')
        self.assertEqual(disk['state'], 'firing')
        self.assertEqual(disk['evidenceState'], 'unavailable')
        self.assertFalse(any(e['kind'] == 'alert.resolved' for e in result['events']))

    def test_successful_host_with_missing_metric_does_not_clear_resource_fault(self):
        low = dict(self.row, diskFreeGb=5)
        self.engine.evaluate([low], self.now)
        self.engine.evaluate([low], self.now+61)
        missing = dict(self.row, diskFreeGb=None)
        self.engine.evaluate([missing], self.now+120)
        result = self.engine.evaluate([missing], self.now+181)
        self.assertTrue(any(a['rule'] == 'disk' and a['state'] == 'firing' for a in result['alerts']))

    def test_service_fault_is_held_until_its_own_running_evidence_returns(self):
        bad = dict(self.row, services=[{'name': 'test.service', 'state': 'available', 'status': 'Stopped'}])
        self.engine.evaluate([bad], self.now)
        self.engine.evaluate([bad], self.now+61)
        self.engine.evaluate([self.row], self.now+120)
        still = self.engine.evaluate([self.row], self.now+181)
        self.assertTrue(any(a['rule']=='service-test.service' for a in still['alerts']))
        good = dict(self.row, services=[{'name':'test.service','state':'available','status':'Running'}])
        self.engine.evaluate([good], self.now+190)
        self.assertEqual(self.engine.evaluate([good], self.now+251)['alerts'], [])

    def test_history_deduplicates_device_timestamps_and_energy_excludes_missing_gaps(self):
        one = dict(self.row, power={'observedAt':operations.iso(self.now),'cpuW':40,'gpuW':60})
        self.engine.evaluate([one],self.now)
        self.engine.evaluate([one],self.now+30)
        two = dict(one, observedAt=operations.iso(self.now+300),power={'observedAt':operations.iso(self.now+300),'cpuW':40,'gpuW':60})
        self.engine.evaluate([two],self.now+300)
        gap = dict(two,observedAt=operations.iso(self.now+1500),power={'observedAt':operations.iso(self.now+1500),'cpuW':40,'gpuW':60})
        self.engine.evaluate([gap],self.now+1500)
        history=self.engine.history('computer-a',30,self.now+1500)
        self.assertEqual(sum(r['count'] for r in history['rows']),3)
        energy=self.engine.energy([self.row],1,self.now+1500)['rows'][0]
        self.assertAlmostEqual(energy['kwh'],100*300/3600000)
        self.assertEqual(energy['coveredSeconds'],300)
        self.assertIsNone(energy['costEstimate'])
        self.assertIn('components only',energy['basis'])

    def test_rechecking_never_refreshes_sample_time_or_counts_pending_as_reporting(self):
        pending = {'host': 'spare', 'status': 'not-enrolled', 'enrollment': 'not-enrolled'}
        pilot = {'host': 'pilot', 'status': 'available', 'enrollment': 'pilot'}
        original = self.row['observedAt']
        result = self.engine.evaluate([self.row, pending, pilot], self.now+601)
        self.assertEqual(self.row['observedAt'], original)
        self.assertEqual(result['counts'], {'registered': 3, 'monitored': 1, 'responding': 0, 'pending': 2})
        self.assertEqual([a['rule'] for a in result['alerts']], ['report'])

    def test_off_hours_suppresses_new_availability_alerts_without_guessing_hours(self):
        row = dict(self.row, status='unavailable', expectedHours={'timeZone': 'UTC', 'days': {day: [] for day in ['mon','tue','wed','thu','fri','sat','sun']}})
        self.assertEqual(operations.conditions(row, self.now), [])
        row.pop('expectedHours')
        self.assertEqual(operations.conditions(row, self.now)[0]['rule'], 'report')

    def test_source_merge_keeps_one_native_owner_and_rejects_conflicts(self):
        viewer = self.root/'viewer'
        viewer.mkdir()
        (viewer/'data.json').write_text(json.dumps({'app': 'macfleet-dash', 'schema': 1, 'hosts': [self.row]}))
        pending = {'host': 'windows-a', 'hostname': 'PC-A', 'platform': 'windows', 'status': 'not-enrolled', 'enrollment': 'not-enrolled'}
        pushed = {**pending, 'status': 'available', 'enrollment': 'enrolled', 'source': 'windows-tailnet', 'authenticatedNodeId': 'nConfirmed', 'observedAt': self.row['observedAt']}
        (viewer/'windows.json').write_text(json.dumps({'schema': 'macfleet.windows.v1', 'hosts': [pending]}))
        (viewer/'tailnet-windows.json').write_text(json.dumps({'schema': 'macfleet.windows.v1', 'hosts': [pushed]}))
        rows = operations.load_fleet(self.root)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['enrollment'], 'enrolled')
        unknown = {'host': 'unfinished-linux', 'hostname': None, 'platform': 'unknown',
                   'status': 'not-enrolled', 'enrollment': 'not-enrolled'}
        (viewer/'windows.json').write_text(json.dumps({'schema': 'macfleet.windows.v1', 'hosts': [pending, unknown]}))
        combined = operations.load_fleet(self.root)
        self.assertEqual(len(combined), 3)
        self.assertEqual(combined[-1]['enrollment'], 'not-enrolled')
        pending.update(status='available', enrollment='enrolled')
        (viewer/'windows.json').write_text(json.dumps({'schema': 'macfleet.windows.v1', 'hosts': [pending]}))
        with self.assertRaisesRegex(ValueError, 'Conflicting telemetry'):
            operations.load_fleet(self.root)

    def test_failed_runtime_read_preserves_original_receipt_and_exposes_failure(self):
        viewer = self.root/'viewer'
        viewer.mkdir()
        source = viewer/'data.json'
        source.write_text(json.dumps({'app': 'macfleet-dash', 'schema': 1, 'hosts': [self.row]}))
        runtime = operations.Runtime(self.root)
        runtime.cycle()
        original = runtime.snapshot()['observedAt']
        source.write_text('{}')
        runtime.cycle()
        self.assertEqual(runtime.snapshot()['observedAt'], original)
        self.assertEqual(runtime.status()['error'], 'ValueError')
        self.assertEqual(runtime.fleet()['hosts'][0]['observedAt'], self.row['observedAt'])


if __name__ == '__main__':
    unittest.main()
