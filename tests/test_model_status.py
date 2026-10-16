import copy
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('model_status', Path(__file__).resolve().parents[1] / 'collector/model_status.py')
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)
NOW = '2026-10-16T04:30:00Z'
URL = 'http://100.64.0.5:18895/v1/models'
ENTRY = {'model_url': URL, 'ts_ip': '100.64.0.5'}
MODEL = {'data': [{'id': 'demo-vlm', 'owned_by': 'llamacpp', 'meta': {'n_ctx': 16384, 'n_ctx_train': 262144, 'n_params': 35000000000, 'ftype': 'Q4_K - Medium'}}]}
PROPS = {'model_alias': 'demo-vlm', 'model_path': '/private/models/demo-vlm-Q4_K_M.gguf', 'default_generation_settings': {'n_ctx': 8192}}


class ModelStatusTests(unittest.TestCase):
    def read(self, value=MODEL, props=PROPS):
        return Mock(side_effect=[copy.deepcopy(value), copy.deepcopy(props)])

    def test_exact_identity_and_props_are_projected_without_private_paths_or_urls(self):
        read = self.read()
        result = models.read_model('demo', ENTRY, read, lambda: NOW)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['modelId'], 'demo-vlm')
        self.assertEqual(result['artifact'], 'demo-vlm-Q4_K_M.gguf')
        self.assertEqual(result['quantization'], 'Q4_K - Medium')
        self.assertEqual(result['contextTokens'], 8192)
        self.assertEqual(result['parameterCount'], 35000000000)
        self.assertEqual(result['observedAt'], NOW)
        self.assertEqual([call.args[0] for call in read.call_args_list], [URL, 'http://100.64.0.5:18895/props'])
        for private in ['/private', '100.64', 'http://', 'chat/completions', '262144']:
            self.assertNotIn(private, json.dumps(result))

    def test_model_change_between_reads_is_not_mixed_into_a_current_identity(self):
        result = models.read_model('demo', ENTRY, self.read(props={**PROPS, 'model_alias': 'other-model'}), lambda: NOW)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['modelId'])
        self.assertIsNone(result['contextTokens'])
        self.assertIsNone(result['artifact'])

    def test_generic_catalog_and_multiple_models_never_pick_first_as_active(self):
        for value, state in [({'data': [{'id': 'catalog-model'}]}, 'catalog'), ({'data': [{'id': 'one'}, {'id': 'two'}]}, 'multiple')]:
            read = Mock(return_value=value)
            result = models.read_model('demo', ENTRY, read, lambda: NOW)
            self.assertEqual(result['status'], state)
            self.assertIsNone(result['modelId'])
            self.assertEqual(read.call_count, 1)

    def test_invalid_empty_duplicate_and_unbounded_rows_are_unavailable(self):
        for value in [{}, {'data': []}, {'data': None}, {'data': [{'id': 'x'}, {'id': 'x'}]}, {'data': [{'id': 'bad\nlabel'}]}, {'data': [{'id': str(i)} for i in range(33)]}]:
            result = models.read_model('demo', ENTRY, Mock(return_value=value), lambda: NOW)
            self.assertEqual(result['status'], 'unavailable')
            self.assertIsNone(result['modelId'])

    def test_optional_props_failure_preserves_identity_not_invented_metadata(self):
        value = {'data': [{'id': 'demo-vlm', 'owned_by': 'llamacpp', 'meta': {'n_ctx_train': 262144, 'n_ctx': True, 'n_params': -3}}]}
        result = models.read_model('demo', ENTRY, Mock(side_effect=[value, OSError('private endpoint error')]), lambda: NOW)
        self.assertEqual(result['status'], 'available')
        self.assertIsNone(result['contextTokens'])
        self.assertIsNone(result['parameterCount'])
        self.assertIsNone(result['artifact'])
        self.assertEqual(result['source'], 'GET /v1/models')

    def test_only_exact_explicit_private_urls_with_matching_registered_ip_are_read(self):
        invalid = ['https://user:SECRET@100.64.0.5:18895/v1/models', 'http://8.8.8.8:18895/v1/models', 'http://localhost:18895/v1/models', 'http://169.254.169.254:80/v1/models', 'http://0.0.0.0:18895/v1/models', 'file:///v1/models', URL+'?key=SECRET', URL+'#fragment', URL.replace('/v1/models', '/chat/completions'), URL.replace('100.64.0.5', '100.64.0.6')]
        for url in invalid:
            read = Mock()
            result = models.read_model('demo', {**ENTRY, 'model_url': url}, read, lambda: NOW)
            self.assertEqual(result['status'], 'unavailable')
            read.assert_not_called()
            self.assertNotIn('SECRET', json.dumps(result))
        for url in ['http://127.0.0.1:8000/v1/models', 'https://192.168.1.5:8443/v1/models', 'http://[::1]:8000/v1/models']:
            self.assertEqual(models.checked_url(url), url)

    def test_one_failed_endpoint_does_not_erase_the_other_identity_or_claim_health(self):
        def read(url):
            if '100.64.0.6' in url:
                raise OSError('PRIVATE URL AND ERROR')
            return copy.deepcopy(PROPS if url.endswith('/props') else MODEL)
        value = models.read_models({'hosts': {'demo': ENTRY, 'failed': {'model_url': URL.replace('100.64.0.5', '100.64.0.6')}}}, read, lambda: NOW)
        self.assertEqual([row['status'] for row in value['hosts']], ['available', 'unavailable'])
        self.assertNotIn('PRIVATE', json.dumps(value))
        self.assertNotIn('cpuUsedPct', json.dumps(value))
        self.assertNotIn('onlineCount', value)

    def test_unconfigured_installation_has_no_invented_model_or_computer(self):
        read = Mock()
        result = models.read_models({'hosts': {'my-computer': {'method': 'local'}}}, read, lambda: NOW)
        self.assertEqual(result['hosts'], [])
        read.assert_not_called()

    def test_registered_identity_and_fanout_are_bounded(self):
        for hosts in [{'../bad': ENTRY}, {str(i): ENTRY for i in range(9)}]:
            with self.assertRaises(ValueError):
                models.read_models({'hosts': hosts}, Mock(), lambda: NOW)

    def test_network_reader_sends_only_get_and_bounds_the_body(self):
        response = io.BytesIO(json.dumps(MODEL).encode())
        opener = SimpleNamespace(open=Mock(return_value=response))
        with patch.object(models, 'build_opener', return_value=opener):
            self.assertEqual(models.fetch_json(URL), MODEL)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertIsNone(request.data)
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 2)
        with patch.object(models, 'build_opener', return_value=SimpleNamespace(open=Mock(return_value=io.BytesIO(b'x' * (models.MAX_BYTES+1))))):
            with self.assertRaises(ValueError):
                models.fetch_json(URL)
        with self.assertRaises(ValueError):
            models.NoRedirect().redirect_request(None, None, None, None, None, None)


if __name__ == '__main__':
    unittest.main()
