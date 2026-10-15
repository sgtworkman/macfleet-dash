import importlib.util
from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

spec=importlib.util.spec_from_file_location('guard_bridge',Path(__file__).resolve().parents[1]/'collector/windows_snapshot.py')
bridge=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)

class LoopbackGuardTests(unittest.TestCase):
    def test_timeout_replays_the_same_strict_scan_once(self):
        scan=Mock(side_effect=[subprocess.TimeoutExpired('lsof',5),SimpleNamespace(returncode=0,stdout='p123\nn127.0.0.1:8791\n')])
        bridge.verify_loopback_viewer(scan)
        self.assertEqual(scan.call_count,2)
        self.assertEqual(scan.call_args_list[0],scan.call_args_list[1])
        self.assertEqual(scan.call_args.kwargs['timeout'],5)

    def test_repeated_timeout_stays_unverified(self):
        scan=Mock(side_effect=subprocess.TimeoutExpired('lsof',5))
        with self.assertRaises(subprocess.TimeoutExpired):bridge.verify_loopback_viewer(scan)
        self.assertEqual(scan.call_count,2)

    def test_bad_or_empty_results_are_never_retried_into_success(self):
        for result in [SimpleNamespace(returncode=1,stdout=''),SimpleNamespace(returncode=0,stdout=''),SimpleNamespace(returncode=0,stdout='p123\nn0.0.0.0:8791\n'),SimpleNamespace(returncode=0,stdout='p123\nn127.0.0.1:8791\nn*:8791\n')]:
            scan=Mock(return_value=result)
            with self.assertRaises(ValueError):bridge.verify_loopback_viewer(scan)
            self.assertEqual(scan.call_count,1)

    def test_both_loopback_families_remain_supported(self):
        scan=Mock(return_value=SimpleNamespace(returncode=0,stdout='p123\nn127.0.0.1:8791\nn[::1]:8791\n'))
        bridge.verify_loopback_viewer(scan)
        self.assertEqual(scan.call_count,1)

if __name__=='__main__':unittest.main()
