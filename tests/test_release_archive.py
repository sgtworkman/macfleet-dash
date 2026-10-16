import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('release_archive', Path(__file__).resolve().parents[1] / 'collector/check_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ArchivePrivacyTests(unittest.TestCase):
    def make_archive(self, directory, extra=(), omit=()):
        path = Path(directory) / 'source.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name in sorted(release.REQUIRED - set(omit)):
                info = tarfile.TarInfo('macfleet-dash-v0.9.3/' + name)
                info.size = 7
                archive.addfile(info, io.BytesIO(b'source\n'))
            for name, kind in extra:
                info = tarfile.TarInfo(name)
                if kind == 'link':
                    info.type = tarfile.SYMTYPE
                    info.linkname = '/private/operator/config'
                    archive.addfile(info)
                else:
                    info.size = 2
                    archive.addfile(info, io.BytesIO(b'{}'))
        return path

    def test_real_archive_inventory_not_gitignore_is_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(release.check_archive(self.make_archive(directory))['files'], len(release.REQUIRED))
            for private in ['viewer/data.json', 'viewer/windows.json', 'viewer/fleet-registry.json', 'macfleet.toml', 'state/events.json', 'fleet-locations.json', 'viewer/activity.json', '.env.local']:
                with self.subTest(private=private), self.assertRaises(ValueError):
                    release.check_archive(self.make_archive(directory, [('macfleet-dash-v0.9.3/' + private, 'file')]))

    def test_links_traversal_extra_roots_duplicates_and_missing_source_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            for member, kind in [('macfleet-dash-v0.9.3/viewer/link', 'link'), ('macfleet-dash-v0.9.3/../escape', 'file'), ('/absolute', 'file'), ('macfleet-dash-v0.9.2/README.md', 'file'), ('macfleet-dash-v0.9.3/README.md', 'file')]:
                with self.subTest(member=member), self.assertRaises(ValueError):
                    release.check_archive(self.make_archive(directory, [(member, kind)]))
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                release.check_archive(self.make_archive(directory, omit=['viewer/fleet-workspace.mjs']))


if __name__ == '__main__':
    unittest.main()
