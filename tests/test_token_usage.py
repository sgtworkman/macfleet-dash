import hashlib
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'collector'))
from token_usage import read_usage, classify
from publish_token_usage import publish_snapshot
import publish_token_usage as publisher

NOW = 1791979200
SCHEMA = '''CREATE TABLE session_model_usage(session_id TEXT,model TEXT,billing_provider TEXT,billing_base_url TEXT,billing_mode TEXT,task TEXT,api_call_count INTEGER,input_tokens INTEGER,output_tokens INTEGER,cache_read_tokens INTEGER,cache_write_tokens INTEGER,reasoning_tokens INTEGER,first_seen REAL,last_seen REAL); CREATE TABLE messages(content TEXT);'''
def database(path, rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as c:
        c.executescript(SCHEMA)
        c.execute('INSERT INTO messages VALUES (?)', ('PRIVATE PROMPT MUST NEVER LEAVE',))
        c.executemany('INSERT INTO session_model_usage VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',rows)
def row(session='private-session-id',model='fixture-model',url='http://100.64.0.10:18890/v1',tokens=100,last=NOW-1):
    return (session,model,'custom',url,'','chat',1,tokens,10,50,2,3,NOW-100,last)

class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='macfleet-token-test-')
        self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def test_local_and_cloud_split_is_source_backed_and_cache_is_not_added_again(self):
        database(self.root/'state.db',[row(),row('cloud',url='https://user:SECRET@api.z.ai/v1?key=SECRET',tokens=200)])
        before=hashlib.sha256((self.root/'state.db').read_bytes()).hexdigest()
        d=read_usage(self.root,{'100.64.0.10':'Demo Studio'},NOW)
        self.assertEqual(d['totals']['local']['inputTokens'],100)
        self.assertEqual(d['totals']['cloud']['inputTokens'],200)
        self.assertEqual(d['totals']['local']['outputTokens'],10)
        self.assertEqual(d['totals']['local']['cacheReadTokens'],50)
        self.assertEqual(d['groups'][1]['targetName'],'Demo Studio')
        for secret in ('SECRET','PRIVATE PROMPT','private-session-id','billing_base_url','http://'):
            self.assertNotIn(secret,json.dumps(d))
        self.assertEqual(hashlib.sha256((self.root/'state.db').read_bytes()).hexdigest(),before)
    def test_missing_empty_or_wrong_schema_never_becomes_zero(self):
        d=read_usage(self.root,now=NOW)
        self.assertEqual(d['status'],'unavailable');self.assertIsNone(d['totals']['cloud']['inputTokens'])
        database(self.root/'state.db',[])
        d=read_usage(self.root,now=NOW);self.assertEqual(d['sources'][0]['status'],'no-row/unverified')
        self.assertIsNone(d['totals']['local']['outputTokens'])
    def test_duplicate_alias_and_migrated_record_count_once_with_latest_counters(self):
        database(self.root/'state.db',[row(tokens=100)])
        database(self.root/'profiles'/'copied'/'state.db',[row(tokens=120,last=NOW)])
        alias=self.root/'profiles'/'alias';alias.mkdir()
        (alias/'state.db').symlink_to(self.root/'state.db')
        d=read_usage(self.root,now=NOW)
        self.assertEqual(d['totals']['local']['inputTokens'],120)
        self.assertEqual(d['totals']['local']['recordCount'],1)
        self.assertEqual(d['coverage']['duplicatesRemoved'],1)
        self.assertIn('duplicate alias · not counted',[s['status'] for s in d['sources']])
    def test_missing_negative_and_unclassified_fields_remain_explicit(self):
        database(self.root/'state.db',[row(tokens=None),row('bad',url='',tokens=-5)])
        d=read_usage(self.root,now=NOW)
        self.assertEqual(d['status'],'partial');self.assertIsNone(d['totals']['local']['inputTokens'])
        self.assertEqual(d['coverage']['unclassifiedRecords'],1)
        self.assertIsNone(d['totals']['unknown']['inputTokens'])
    def test_endpoint_classification_does_not_guess_from_provider_or_model(self):
        for url in ('', 'nonsense', 'https://api.z.ai.evil.example/v1', 'https://unregistered.example/v1'):
            self.assertEqual(classify(url)[0],'unknown')
        self.assertEqual(classify('http://mini1.ts.net/v1')[0],'local')
        self.assertEqual(classify('https://chatgpt.com/backend-api')[0],'cloud')
    def test_atomic_projection_is_aggregate_only_and_private(self):
        database(self.root/'state.db',[row()])
        d=read_usage(self.root,now=NOW)
        output=self.root/'viewer'/'token-usage.json';output.parent.mkdir()
        publish_snapshot(output,d)
        self.assertEqual(json.loads(output.read_text())['totals']['local']['inputTokens'],100)
        self.assertEqual(output.stat().st_mode & 0o777,0o600)
        self.assertNotIn('PRIVATE PROMPT',output.read_text())
        self.assertEqual(list(output.parent.glob('.token-usage-*')),[])

    def test_whole_and_fractional_seconds_keep_real_chronological_bounds(self):
        whole=row('whole',last=NOW-1)
        fractional=list(row('fractional',last=NOW-0.75))
        fractional[-2]=NOW-99.75
        database(self.root/'state.db',[whole,tuple(fractional)])
        d=read_usage(self.root,now=NOW)
        first=datetime.fromisoformat(d['groups'][0]['firstSeen'].replace('Z','+00:00')).timestamp()
        last=datetime.fromisoformat(d['groups'][0]['lastSeen'].replace('Z','+00:00')).timestamp()
        self.assertEqual(first,NOW-100)
        self.assertEqual(last,NOW-0.75)
        self.assertEqual(datetime.fromisoformat(d['coverage']['start'].replace('Z','+00:00')).timestamp(),NOW-100)
        self.assertEqual(datetime.fromisoformat(d['coverage']['end'].replace('Z','+00:00')).timestamp(),NOW-0.75)


class PublisherTests(unittest.TestCase):
    def test_existing_loopback_helper_publishes_independent_private_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'viewer').mkdir()
            usage={'status':'available','observedAt':'2026-10-16T04:30:00Z','groups':[]}
            models={'schema':'macfleet.models.v1','observedAt':usage['observedAt'],'hosts':[]}
            config={'hosts':{'demo':{'method':'http','ts_ip':'100.64.0.5','model_url':'http://100.64.0.5:8000/v1/models'}}}
            result=SimpleNamespace(returncode=0,stdout='p123\nn127.0.0.1:8780\n')
            with patch.object(publisher,'ROOT',root), patch.object(sys,'argv',['publisher','--viewer-port','8780','--config','fixture.json']), patch.object(publisher.subprocess,'run',return_value=result) as listener, patch('macfleet.load_config',return_value=config) as load, patch.object(publisher,'read_usage',return_value=usage), patch.object(publisher,'read_models',return_value=models) as read, patch('builtins.print'):
                publisher.main()
            load.assert_called_once_with('fixture.json')
            read.assert_called_once_with(config)
            self.assertIn('-iTCP:8780',listener.call_args.args[0])
            for name,value in [('token-usage.json',usage),('model-status.json',models)]:
                output=root/'viewer'/name
                self.assertEqual(json.loads(output.read_text()),value)
                self.assertEqual(output.stat().st_mode & 0o777,0o600)

    def test_unverified_or_non_loopback_viewer_stops_before_reads_and_writes(self):
        for returncode,stdout in [(1,''),(0,''),(0,'n*:8791\n'),(0,'n127.0.0.1:8791\nn100.64.0.5:8791\n')]:
            with self.subTest(stdout=stdout), patch.object(sys,'argv',['publisher']), patch.object(publisher.subprocess,'run',return_value=SimpleNamespace(returncode=returncode,stdout=stdout)), patch.object(publisher,'read_usage') as usage, patch.object(publisher,'read_models') as models, patch.object(publisher,'publish_snapshot') as write:
                with self.assertRaises(SystemExit):publisher.main()
                usage.assert_not_called();models.assert_not_called();write.assert_not_called()

    def test_invalid_port_stops_before_inspecting_listener_or_sources(self):
        for port in ['80','65536']:
            with patch.object(sys,'argv',['publisher','--viewer-port',port]), patch.object(publisher.subprocess,'run') as listener:
                with self.assertRaises(SystemExit):publisher.main()
                listener.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
