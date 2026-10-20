import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('refresh_collector',Path(__file__).resolve().parents[1]/'collector/macfleet.py')
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)

class ConfigurationRefreshTests(unittest.TestCase):
    def test_existing_owner_reads_saved_configuration_on_each_normal_cycle(self):
        old={'hosts':{'old':{'method':'local'}}};new={'hosts':{'new':{'method':'local'}}}
        with tempfile.TemporaryDirectory() as directory, patch.object(collector,'load_config',side_effect=[old,new,ValueError('invalid config')]), patch.object(collector,'collect',return_value={'schema':1}) as collect, patch.object(collector,'write_state') as write, patch.object(collector,'print_table'), patch.object(collector,'serve_viewer') as serve:
            collector.main(['--config','private.json','--state',str(Path(directory)/'state.json'),'--serve','8780','--live'])
            refresher=serve.call_args.args[3]
            refresher();self.assertEqual(collect.call_args.args[0],new)
            writes=write.call_count
            with self.assertRaises(ValueError):refresher()
            self.assertEqual(write.call_count,writes)
            self.assertEqual(collect.call_count,2)

if __name__=='__main__':unittest.main()
