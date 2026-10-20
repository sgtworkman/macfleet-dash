import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'collector'))
import fleet_usage
from token_usage import read_usage
from test_token_usage import database, row, NOW


class FleetUsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        database(self.root / 'state.db', [row()])
        database(self.root / 'profiles' / 'demo-agent' / 'state.db', [row('second', tokens=200)])
        self.usage = read_usage(self.root, now=NOW)
        self.entry = {'method': 'ssh', 'host': 'demo-existing-alias', 'name': 'Demo computer', 'usage': True}
    def tearDown(self):
        self.temp.cleanup()
    def test_profile_provenance_is_retained_without_session_ids_or_prompts(self):
        self.assertEqual({group['agentProfile'] for group in self.usage['groups']}, {'default', 'demo-agent'})
        self.assertEqual(self.usage['totals']['local']['inputTokens'], 300)
        projected = fleet_usage.project_usage({**self.usage, 'secret': 'PRIVATE', 'groups': [{**r, 'prompt': 'PRIVATE'} for r in self.usage['groups']]})
        self.assertNotIn('PRIVATE', json.dumps(projected))
        self.assertNotIn('private-session', json.dumps(projected))
        self.assertEqual(projected['totals'], self.usage['totals'])
    def test_migrated_profiles_count_once_and_keep_selected_provenance(self):
        database(self.root / 'profiles' / 'migrated' / 'state.db', [row(tokens=150, last=NOW)])
        value = read_usage(self.root, now=NOW)
        self.assertEqual(value['totals']['local']['inputTokens'], 350)
        self.assertEqual({group['agentProfile'] for group in value['groups']}, {'migrated', 'demo-agent'})
    def test_remote_read_is_stdin_only_read_only_and_existing_host_key_checked(self):
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.usage)))
        result = fleet_usage.read_remote('demo', self.entry, {}, run)
        self.assertEqual(result['status'], 'available')
        args = run.call_args.args[0]
        self.assertIn('StrictHostKeyChecking=yes', args)
        self.assertIn('BatchMode=yes', args)
        self.assertEqual(args[-4:], ['demo-existing-alias', 'python3', '-B', '-'])
        self.assertEqual(run.call_args.kwargs['timeout'], 6)
        self.assertIn("mode=ro", run.call_args.kwargs['input'])
        self.assertNotIn('PRIVATE', json.dumps(result))
    def test_failed_forced_command_timeout_and_invalid_routes_are_unverified(self):
        for run in [Mock(side_effect=subprocess.TimeoutExpired('ssh', 6)), Mock(return_value=SimpleNamespace(returncode=1, stdout='PRIVATE')), Mock(return_value=SimpleNamespace(returncode=0, stdout='not usage'))]:
            result = fleet_usage.read_remote('demo', self.entry, {}, run)
            self.assertEqual(result['status'], 'unavailable');self.assertIsNone(result['usage'])
            self.assertNotIn('PRIVATE', json.dumps(result))
        for alias in ['-Fmalicious', 'demo; printenv', 'user@host $(cmd)']:
            run = Mock();result = fleet_usage.read_remote('demo', {**self.entry, 'host': alias}, {}, run)
            run.assert_not_called();self.assertIsNone(result['usage'])
    def test_computers_are_separate_and_unconfigured_hosts_are_not_zero(self):
        config = {'hosts': {'local': {'method': 'local'}, 'demo': self.entry, 'unconfigured': {'method': 'http'}}}
        run = Mock(return_value=SimpleNamespace(returncode=0, stdout=json.dumps(self.usage)))
        value = fleet_usage.add_computers(self.usage, config, {}, run)
        self.assertEqual(value['totals'], self.usage['totals'])
        self.assertEqual(len(value['computers']), 3)
        self.assertEqual(value['computers'][2]['status'], 'not-configured')
        self.assertIsNone(value['computers'][2]['usage'])
        self.assertNotIn('computers', value['computers'][0]['usage'])
        for hosts in [{str(i): self.entry for i in range(5)}, {'local': {'method': 'local', 'usage': True}}]:
            with self.assertRaises(ValueError):fleet_usage.add_computers(self.usage, {'hosts': hosts}, {}, run)
    def test_missing_counters_and_bad_totals_are_not_accepted_as_zero(self):
        for mutate in [lambda value: value['groups'][0].update(inputTokens=True), lambda value: value['totals']['local'].update(inputTokens=0), lambda value: value.update(observedAt='no time')]:
            value = copy.deepcopy(self.usage);mutate(value)
            with self.assertRaises(ValueError):fleet_usage.project_usage(value)

    def test_exact_reader_status_vocabulary_preserves_partial_profile_coverage(self):
        for status in ('usage schema unavailable', 'usage exceeds bounded read · not counted',
                       'usage read unavailable', 'duplicate alias · not counted', 'no-row/unverified'):
            value = copy.deepcopy(self.usage)
            value['status'] = 'partial'
            value['sources'].append({'profile':'missing-profile','status':status,'records':0})
            projected = fleet_usage.project_usage(value)
            self.assertEqual(projected['sources'][-1]['status'],status)
            self.assertEqual(projected['totals'],self.usage['totals'])
        with tempfile.TemporaryDirectory() as directory:
            empty=fleet_usage.project_usage(read_usage(Path(directory),now=NOW))
            self.assertEqual(empty['status'],'unavailable')
            self.assertEqual(empty['groups'],[])

    def test_unrecognized_status_or_contradictory_availability_stays_unverified(self):
        for mutate in (lambda value:value['sources'][0].update(status='provider (1 credentials): ok'),
                       lambda value:value['sources'][0].update(records=None),
                       lambda value:value.update(status='unavailable')):
            value=copy.deepcopy(self.usage);mutate(value)
            with self.assertRaises(ValueError):fleet_usage.project_usage(value)


if __name__ == '__main__':unittest.main()
