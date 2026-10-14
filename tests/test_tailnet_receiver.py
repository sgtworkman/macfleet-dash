import copy
from datetime import datetime, timezone, timedelta
import http.client
from http.server import HTTPServer
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('receiver', ROOT/'collector/tailnet_receiver.py')
receiver = importlib.util.module_from_spec(spec); spec.loader.exec_module(receiver)
NOW = datetime(2026, 10, 14, 18, tzinfo=timezone.utc)
HOST = {'id':'fixture-pc','expectedComputerName':'FIXTURE-PC','nodeId':'nFixturePeer123','address':'100.64.1.20','kind':'range','site':'Fixture','purpose':'pos','services':[]}
CONFIG = {'schema':receiver.SCHEMA,'bindAddress':'100.64.1.10','port':8792,'collectorNodeId':'nFixtureReceiver123','hosts':[HOST]}


def sample():
    return {'schema':'workman.windows-fleet-pilot.v1','host':'FIXTURE-PC','status':'available','units':'GiB','observedAt':NOW.isoformat(),'os':'Windows fixture','cpuUsedPct':0,'ramGb':16,'memUsedGb':8,'uptimeDays':2,'disks':[{'drive':'C:','status':'available','totalGb':100,'usedGb':70,'freeGb':30}],'networkState':'available','network':[{'name':'NIC','receivedBytes':1000,'sentBytes':500}],'services':[],'gpuUtilPct':None,'temperatureC':None,'powerW':None}


def identity(address):
    return {'id':HOST['nodeId'],'addresses':[HOST['address']+'/32']}


class ReceiverTests(unittest.TestCase):
    def test_optional_existing_ssh_identity_route_keeps_host_key_checks_and_projects_no_account_data(self):
        response=type('Result',(),{'stdout':json.dumps({'Node':{'StableID':HOST['nodeId'],'Addresses':[HOST['address']+'/32'],'Endpoints':['not published']},'UserProfile':{'LoginName':'not published'}}).encode()})()
        with mock.patch.object(receiver.subprocess,'run',return_value=response) as run:
            value=receiver.whois(HOST['address'],'/usr/local/bin/tailscale',via='fixture-trusted-host')
            self.assertEqual(value,identity(HOST['address']));self.assertNotIn('not published',json.dumps(value))
            self.assertIn('StrictHostKeyChecking=yes',run.call_args[0][0]);self.assertIn('BatchMode=yes',run.call_args[0][0])
        with self.assertRaises(ValueError): receiver.whois(HOST['address'],'tailscale',via='-oUnsafeOption')
        with self.assertRaises(ValueError): receiver.whois('8.8.8.8','tailscale')
    def test_listener_never_accepts_public_lan_loopback_wildcard_or_viewer_port(self):
        for address in ('0.0.0.0','127.0.0.1','192.168.1.1','8.8.8.8','100.128.0.1','::1'):
            with self.assertRaises(ValueError): receiver.checked_config(dict(CONFIG,bindAddress=address))
        for port in (8791,80,True,'8792',65536):
            with self.assertRaises(ValueError): receiver.checked_config(dict(CONFIG,port=port))
        self.assertEqual(receiver.checked_config(CONFIG),CONFIG)

    def test_duplicate_address_node_native_name_and_host_id_are_rejected(self):
        for update in ({'id':'second'},{'id':'second','nodeId':'nAnotherPeer123'},{'id':'second','address':'100.64.1.21'},{'id':'second','expectedComputerName':'fixture-pc'}):
            with self.assertRaises(ValueError): receiver.checked_config(dict(CONFIG,hosts=[HOST,dict(HOST,**update)]))

    def test_exact_address_and_stable_node_identity_are_both_required(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'snapshot.json'
            ingest=receiver.Receiver(CONFIG,out,identity,now=lambda:NOW)
            with self.assertRaises(PermissionError): ingest.accept('100.64.1.21',HOST['id'],sample())
            with self.assertRaises(PermissionError): ingest.accept(HOST['address'],'other',sample())
            ingest.identity_lookup=lambda _: {'id':'nWrongIdentity','addresses':[HOST['address']+'/32']}
            with self.assertRaises(ValueError): ingest.accept(HOST['address'],HOST['id'],sample())
            self.assertFalse(out.exists())

    def test_real_zero_is_retained_pilot_does_not_claim_automatic_and_output_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'snapshot.json'; ingest=receiver.Receiver(CONFIG,out,identity,now=lambda:NOW)
            row=ingest.accept(HOST['address'],HOST['id'],sample())
            self.assertEqual(row['cpuUsedPct'],0); self.assertEqual(row['enrollment'],'pilot')
            self.assertEqual(row['source'],'windows-tailnet'); self.assertEqual(row['purpose'],'pos')
            self.assertEqual(out.stat().st_mode & 0o777,0o600)
            self.assertEqual(row['receivedAt'],receiver.bridge.iso(NOW))

    def test_replay_wrong_native_identity_or_unreviewed_service_cannot_refresh_last_seen(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'snapshot.json'; ingest=receiver.Receiver(CONFIG,out,identity,now=lambda:NOW)
            ingest.accept(HOST['address'],HOST['id'],sample()); before=out.read_bytes()
            for update in ({},{'host':'OTHER-PC'},{'services':[{'name':'Unapproved','state':'available','status':'Running'}]}):
                with self.assertRaises(ValueError): ingest.accept(HOST['address'],HOST['id'],dict(sample(),**update))
                self.assertEqual(out.read_bytes(),before)

    def test_extra_fields_are_dropped_and_network_rates_need_two_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'snapshot.json'; clock=[NOW]
            ingest=receiver.Receiver(CONFIG,out,identity,now=lambda:clock[0])
            first=sample(); first['privateFile']='must not escape'; first['network'][0]['mac']='must not escape'
            row=ingest.accept(HOST['address'],HOST['id'],first)
            self.assertNotIn('must not escape',out.read_text()); self.assertIsNone(row['network'][0]['rxMBps'])
            clock[0]+=timedelta(seconds=5); second=sample(); second['observedAt']=clock[0].isoformat(); second['network'][0]['receivedBytes']+=5000000
            row=ingest.accept(HOST['address'],HOST['id'],second)
            self.assertEqual(row['network'][0]['rxMBps'],1); self.assertIsNone(row['netRxMbps'])
            self.assertEqual(len(json.loads(out.read_text())['history']['hosts'][HOST['id']]),2)

    def test_corrupt_previous_snapshot_is_not_silently_erased(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'snapshot.json'; out.write_text('{bad')
            ingest=receiver.Receiver(CONFIG,out,identity,now=lambda:NOW)
            with self.assertRaises(ValueError): ingest.accept(HOST['address'],HOST['id'],sample())
            self.assertEqual(out.read_text(),'{bad')

    def test_clock_warning_is_preserved_and_receiver_clock_rollback_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'snapshot.json'; clock=[NOW]
            ingest=receiver.Receiver(CONFIG,out,identity,now=lambda:clock[0]); value=sample()
            value['observedAt']=(NOW+timedelta(minutes=30)).isoformat()
            row=ingest.accept(HOST['address'],HOST['id'],value)
            self.assertEqual(row['clockState'],'skewed'); self.assertEqual(row['clockSkewSeconds'],1800)
            clock[0]-=timedelta(minutes=1); value['observedAt']=(NOW+timedelta(minutes=31)).isoformat()
            with self.assertRaises(ValueError): ingest.accept(HOST['address'],HOST['id'],value)

    def test_refresh_can_record_verified_schedule_but_cannot_widen_listener(self):
        config=copy.deepcopy(CONFIG)
        with tempfile.TemporaryDirectory() as directory:
            ingest=receiver.Receiver(CONFIG,Path(directory)/'snapshot.json',identity,now=lambda:NOW,config_reader=lambda:config)
            config['hosts'][0]['automaticVerified']=True; ingest.refresh_config()
            self.assertEqual(ingest.accept(HOST['address'],HOST['id'],sample())['enrollment'],'enrolled')
            config['bindAddress']='100.64.1.11'
            with self.assertRaises(ValueError): ingest.refresh_config()

    def test_http_has_no_read_route_and_rejects_oversize_framing_and_unapproved_sources(self):
        class FixtureReceiver:
            config={'hosts':[{'address':'127.0.0.1','id':'fixture-pc'}]}
            def refresh_config(self):pass
            def accept(self,*args):self.accepted=args
        fixture=FixtureReceiver(); server=HTTPServer(('127.0.0.1',0),receiver.handler_for(fixture))
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        def request(method,path,body=None,headers=None):
            connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
            connection.request(method,path,body,headers or {}); response=connection.getresponse(); status=response.status; response.read(); connection.close(); return status
        try:
            self.assertEqual(request('GET','/tailnet-windows.json'),404)
            self.assertEqual(request('POST','/v1/samples/other','{}',{'Content-Type':'application/json'}),403)
            self.assertEqual(request('POST','/v1/samples/fixture-pc','{}',{'Content-Type':'application/json','Content-Length':str(receiver.MAX_BYTES+1)}),422)
            self.assertEqual(request('POST','/v1/samples/fixture-pc','{}',{'Content-Type':'text/plain'}),422)
            self.assertEqual(request('POST','/v1/samples/fixture-pc','{}',{'Content-Type':'application/json'}),202)
            self.assertEqual(fixture.accepted,('127.0.0.1','fixture-pc',{}))
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=3)

    def test_sender_and_installer_do_not_bypass_policy_open_ports_or_overwrite_an_owner(self):
        sender=(ROOT/'windows/send-fleet.ps1').read_text(); installer=(ROOT/'windows/install-sender.ps1').read_text()
        for text in (sender,installer):
            for forbidden in ('Set-ExecutionPolicy','-ExecutionPolicy Bypass','New-NetFirewallRule','Enable-PSRemoting','Start-Process','-Force','Funnel'):
                self.assertNotIn(forbidden,text)
        self.assertIn('Receiver Tailscale identity mismatch',sender)
        self.assertIn('-MaximumRedirection 0 -Proxy $null',sender)
        self.assertIn('Monitoring task already exists',installer)
        self.assertIn('-AtStartup',installer); self.assertIn('-RepetitionInterval (New-TimeSpan -Minutes 5)',installer)


if __name__=='__main__':unittest.main()
