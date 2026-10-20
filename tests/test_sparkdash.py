from copy import deepcopy
import json
from pathlib import Path
import socket
import sys
import unittest
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'collector'))
import sparkdash as spark
import macfleet

NOW = '2026-10-20T05:30:00Z'
LATER = '2026-10-20T05:35:00Z'
MS = 1792474200000


def config():
    return {'hosts': {'demo': {'ts_ip': '100.64.0.11'}}, 'sparkdash': {
        'enabled': True, 'url': 'http://127.0.0.1:3000',
        'units': {'engine-a': {'host': 'demo', 'name': 'Demo AI'}}}}


def metrics():
    return {'id': 'engine-a', 'name': 'Demo', 'online': True, 'lanIp': '100.64.0.11',
            'workerNode': False, 'ssh': {'password': 'PRIVATE PASSWORD'},
            'metrics': {'llm': [{'port': 8888, 'available': True, 'backend': 'tensorfold',
                'modelId': 'Demo model', 'modelPath': '/private/models/SECRET',
                'generationTps': 25.5, 'prefillTps': None, 'slotsActive': 1,
                'slotsTotal': 3, 'requestsRunning': 1, 'requestsWaiting': None,
                'decodeActive': True, 'prefillActive': False}]}}


def history(selected):
    return {'enabled': True, 'range': selected, 'stepMs': 60000, 'from': MS-3600000,
            'to': MS, 'points': [{'t': MS-120000, 'gpuUtil': {'avg': 50, 'max': 90}},
                                {'t': MS-60000, 'memFreeMB': {'avg': 5000, 'max': 5100, 'min': 4900}}],
            'llm': [{'port': 8888, 'points': [{'t': MS-60000, 'genTps': {'avg': 25, 'max': 30}}]}]}


def totals(selected):
    counts = {'promptTokens': 100, 'completionTokens': 20, 'cachedTokens': 40}
    return {'range': selected, 'series': [{'sparkId': 'engine-a', 'port': 8888,
            'updatedAt': MS, 'totals': counts,
            'models': [{'modelId': 'Demo model', **counts}]}]}


def read(url):
    path = urlsplit(url)
    if path.path.endswith('/metrics'):
        return metrics()
    if path.path.endswith('/history'):
        return history(parse_qs(path.query)['range'][0])
    if path.path == '/api/llm-token-totals':
        return totals(parse_qs(path.query)['range'][0])
    raise AssertionError('Unexpected route: '+path.path)


class SparkdashTests(unittest.TestCase):
    def test_opt_in_only_and_clean_install_never_contacts_any_source(self):
        def forbidden(url):raise AssertionError('No network while disabled')
        for value in ({}, {'sparkdash': {}}, {'sparkdash': {'enabled': False}}):
            result = spark.read_sparkdash(value, read=forbidden, now=lambda: NOW)
            self.assertEqual(result['status'], 'not-configured')
            self.assertEqual(result['units'], [])

    def test_exact_readonly_routes_all_ranges_and_aggregate_projection(self):
        calls = []
        def recorded(url):calls.append(url);return read(url)
        result = spark.read_sparkdash(config(), read=recorded, now=lambda: NOW)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(len(calls), 9)
        self.assertEqual(set(result['totals']), {'1h', '6h', '24h'})
        unit = result['units'][0]
        self.assertEqual(unit['host'], 'demo')
        self.assertEqual(unit['endpoints'][0]['generationTps'], 25.5)
        self.assertIsNone(unit['endpoints'][0]['requestsWaiting'])
        self.assertEqual(result['totals']['24h']['rows'][0]['completionTokens'], 20)
        self.assertEqual(unit['history']['1h']['points'][0]['t'], MS-120000)
        self.assertNotIn('memFreeMB', unit['history']['1h']['points'][0])
        for private in ('PRIVATE PASSWORD', 'SECRET', 'modelPath', 'lanIp', 'http://'):
            self.assertNotIn(private, json.dumps(result))

    def test_failed_reconnect_preserves_original_receipts_without_fabricated_rates(self):
        before = spark.read_sparkdash(config(), read=read, now=lambda: NOW)
        def failed(url):raise OSError('SECRET transport failure')
        after = spark.read_sparkdash(config(), before, read=failed, now=lambda: LATER)
        self.assertEqual(after['status'], 'unavailable')
        self.assertEqual(after['units'][0]['observedAt'], NOW)
        self.assertEqual(after['units'][0]['lastAttemptAt'], LATER)
        self.assertEqual(after['totals']['6h']['rows'], before['totals']['6h']['rows'])
        self.assertEqual(after['totals']['6h']['status'], 'unavailable')
        self.assertNotIn('SECRET', json.dumps(after))
        recovered = spark.read_sparkdash(config(), after, read=read, now=lambda: LATER)
        self.assertEqual(recovered['units'][0]['endpoints'][0]['generationTps'], 25.5)
        self.assertEqual(recovered['totals']['6h']['rows'][0]['completionTokens'], 20)

    def test_new_source_does_not_inherit_another_installations_history(self):
        before = spark.read_sparkdash(config(), read=read, now=lambda: NOW)
        changed = config();changed['sparkdash']['url'] = 'http://127.0.0.1:3001'
        def failed(url):raise OSError('unavailable')
        after = spark.read_sparkdash(changed, before, read=failed, now=lambda: LATER)
        self.assertNotEqual(before['sourceId'], after['sourceId'])
        self.assertEqual(after['units'][0]['endpoints'], [])
        self.assertIsNone(after['totals']['1h']['observedAt'])
        self.assertNotIn('rows', after['totals']['1h'])

    def test_a_bad_token_range_does_not_blank_valid_units_or_other_ranges(self):
        def faulty(url):
            value = read(url)
            if 'llm-token-totals?range=6h' in url:value['series'][0]['totals']['promptTokens'] = 999
            return value
        result = spark.read_sparkdash(config(), read=faulty, now=lambda: NOW)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['units'][0]['status'], 'available')
        self.assertEqual(result['totals']['6h']['status'], 'unavailable')
        self.assertEqual(result['totals']['1h']['status'], 'available')

    def test_duplicate_models_negative_counters_and_wrong_range_are_rejected(self):
        for change in ('duplicate', 'negative', 'range'):
            value = totals('1h')
            if change == 'duplicate':value['series'][0]['models'] *= 2
            elif change == 'negative':value['series'][0]['models'][0]['completionTokens'] = -1
            else:value['range'] = 'all'
            with self.subTest(change=change), self.assertRaises(ValueError):
                spark.project_totals(value, '1h', {'engine-a'})

    def test_mapping_requires_exact_existing_address_and_never_adds_a_host(self):
        source = metrics();source['lanIp'] = '100.64.0.12'
        with self.assertRaises(ValueError):spark.project_metrics(source, 'engine-a', {'host':'demo'}, config()['hosts'])
        unlinked = spark.project_metrics(source, 'engine-a', {}, config()['hosts'])
        self.assertIsNone(unlinked['host'])
        self.assertEqual(set(config()['hosts']), {'demo'})
        bad = config();bad['sparkdash']['units']['extra']={'host':'demo'}
        self.assertEqual(spark.read_sparkdash(bad, read=read, now=lambda: NOW)['status'], 'unavailable')

    def test_history_gaps_disabled_setting_and_statistics_are_preserved(self):
        self.assertEqual(spark.project_history({'enabled':False}, '1h')['points'], [])
        value = history('1h');value['points'].append(deepcopy(value['points'][-1]))
        with self.assertRaises(ValueError):spark.project_history(value, '1h')
        value = history('1h');value['points'][0]['gpuUtil']['max'] = 10
        with self.assertRaises(ValueError):spark.project_history(value, '1h')

    def test_unknown_rate_is_not_a_measured_zero(self):
        source = metrics();source['metrics']['llm'][0]['generationTps'] = float('nan')
        source['metrics']['llm'][0]['slotsTotal'] = 0
        result = spark.project_metrics(source, 'engine-a', {}, {})
        self.assertIsNone(result['endpoints'][0]['generationTps'])
        self.assertIsNone(result['endpoints'][0]['slotsTotal'])

    def test_only_explicit_private_origins_without_credentials_queries_or_redirects(self):
        for value in ('https://example.com', 'http://8.8.8.8:3000', 'http://127.0.0.1',
                      'http://user:SECRET@127.0.0.1:3000', 'http://127.0.0.1:3000/api',
                      'http://127.0.0.1:3000?token=SECRET'):
            with self.subTest(value=value), self.assertRaises(ValueError):spark.checked_base(value)
        self.assertEqual(spark.checked_base('http://127.0.0.1:3000/'), 'http://127.0.0.1:3000')
        private=lambda *a,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('100.64.0.2',443))]
        public=lambda *a,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]
        self.assertEqual(spark.checked_base('https://demo.taildemo.ts.net',private),'https://demo.taildemo.ts.net')
        with self.assertRaises(ValueError):spark.checked_base('https://demo.taildemo.ts.net',public)
        with self.assertRaises(ValueError):spark.NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_transport_has_no_proxy_auth_or_write_method_and_reads_are_bounded(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self, limit):self.limit=limit;return b'{}'
        response=Response()
        with patch.object(spark,'build_opener') as build:
            build.return_value.open.return_value=response
            self.assertEqual(spark.fetch_json('http://127.0.0.1:3000/api/sparks/engine-a/metrics'),{})
        args=build.return_value.open.call_args
        self.assertEqual(args.args[0].method,'GET')
        self.assertNotIn('Authorization',args.args[0].headers)
        self.assertEqual(args.kwargs['timeout'],1.5)
        self.assertEqual(response.limit,2*1024*1024+1)

    def test_normalized_configuration_retains_optional_connector(self):
        value=macfleet._normalize_config(config())
        self.assertEqual(value['sparkdash'],config()['sparkdash'])


if __name__=='__main__':unittest.main()
