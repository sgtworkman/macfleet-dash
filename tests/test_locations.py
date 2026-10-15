import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('locations', Path(__file__).resolve().parents[1] / 'collector/configure_locations.py')
locations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(locations)


class LocationTests(unittest.TestCase):
    def test_only_sites_change_and_input_is_not_mutated(self):
        registry = {'schema': 'macfleet.registry.v1', 'hosts': {'desktop': {'kind': 'server', 'site': 'Old', 'purpose': 'other'}}, 'pendingHosts': [{'host': 'unknown', 'pendingReason': 'Identity unverified'}], 'source': 'Existing inventory'}
        result = locations.merge_locations(registry, {'desktop': 'Home', 'new-host': 'Office'})
        self.assertEqual(result['hosts']['desktop'], {'kind': 'server', 'site': 'Home', 'purpose': 'other'})
        self.assertEqual(result['pendingHosts'], registry['pendingHosts'])
        self.assertEqual(result['source'], registry['source'])
        self.assertEqual(registry['hosts']['desktop']['site'], 'Old')

    def test_bad_input_never_becomes_an_access_or_identity_setting(self):
        for labels in [{'../escape': 'Home'}, {'pc': {'enabled': True}}, {'pc': 'x' * 81}, {'pc': 'A\nB'}, {'pc': 'all'}]:
            with self.assertRaises(ValueError):
                locations.checked_locations({'schema': 'macfleet.locations.v1', 'locations': labels})
        with self.assertRaises(ValueError):
            locations.checked_locations({'schema': 'macfleet.locations.v1', 'locations': {'pc': 'Home'}, 'enabled': True})

    def test_atomic_save_retains_a_private_exact_backup_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'viewer/registry.json'
            path.parent.mkdir()
            before = b'{"schema":"macfleet.registry.v1","hosts":{"pc":{"kind":"server"}},"pendingHosts":[]}\n'
            path.write_bytes(before)
            backup, changed = locations.apply_locations(path, {'pc': 'Home'}, Path(directory) / 'backups')
            self.assertTrue(changed)
            self.assertEqual(backup.read_bytes(), before)
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['hosts']['pc'], {'kind': 'server', 'site': 'Home'})
            self.assertEqual(locations.apply_locations(path, {'pc': 'Home'}, Path(directory) / 'backups'), (None, False))

    def test_missing_registry_can_be_created_without_inventing_enrollment(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'viewer/registry.json'
            backup, changed = locations.apply_locations(path, {'pc': 'Home'}, Path(directory) / 'backups')
            self.assertTrue(changed)
            self.assertIsNone(backup)
            self.assertEqual(json.loads(path.read_text()), {'schema': 'macfleet.registry.v1', 'hosts': {'pc': {'site': 'Home'}}})

    def test_invalid_registry_and_symlink_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'registry.json'
            path.write_text('{invalid')
            with self.assertRaises(ValueError):
                locations.apply_locations(path, {'pc': 'Home'}, Path(directory) / 'backups')
            self.assertEqual(path.read_text(), '{invalid')
            link = Path(directory) / 'linked.json'
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                locations.apply_locations(link, {'pc': 'Home'}, Path(directory) / 'backups')

    def test_concurrent_registry_change_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'registry.json'
            path.write_text('{"schema":"macfleet.registry.v1","hosts":{}}')
            original = locations.os.fsync
            def changed_after_write(fd):
                original(fd)
                path.write_text('{"schema":"macfleet.registry.v1","hosts":{},"otherOwner":"retained"}')
            with patch.object(locations.os, 'fsync', side_effect=changed_after_write):
                with self.assertRaisesRegex(ValueError, 'changed while editing'):
                    locations.apply_locations(path, {'pc': 'Home'}, Path(directory) / 'backups')
            self.assertEqual(json.loads(path.read_text())['otherOwner'], 'retained')
            self.assertFalse(list(path.parent.glob('.macfleet-locations-*')))


if __name__ == '__main__':
    unittest.main()
