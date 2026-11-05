import base64
import hashlib
import json
import unittest
from unittest.mock import patch
from test_release import r
from stable_policy import accepted


class IndependentAdmissionTests(unittest.TestCase):
    repo='hyperme-sh/component';main_sha='c'*40;revision='a'*40
    def setUp(self):
        raw=b'{"public_api":{"read":"str"}}'
        digest=hashlib.sha256(raw).hexdigest()
        self.policy={'schema_version':1,'repository':self.repo,'component':'component','line':'0.24','version_files':['pyproject.toml']}
        def bundle(version,sha):return {'schema_version':1,'line':'0.24','components':{'component':{'version':version,'contract':'contract.json','contract_sha256':digest,'artifact':{'kind':'package','uri':'urn:sha256:'+sha,'sha256':sha}}}}
        self.data={(self.main_sha,'release-policy.json'):json.dumps(self.policy).encode(),
            (self.revision,'release-policy.json'):json.dumps(self.policy).encode(),
            (self.revision,'pyproject.toml'):b'[project]\nname="component"\nversion="0.24.1"\n',
            (self.main_sha,'releases/accepted/release.json'):json.dumps(bundle('0.24.0','b'*64)).encode(),
            (self.main_sha,'releases/accepted/contract.json'):raw,
            ('b'*40,'releases/candidate/release.json'):json.dumps(bundle('0.24.0','b'*64)).encode(),
            ('b'*40,'releases/candidate/contract.json'):raw,
            (self.revision,'releases/candidate/release.json'):json.dumps(bundle('0.24.1',hashlib.sha256(b'tested').hexdigest())).encode(),
            (self.revision,'releases/candidate/contract.json'):raw}
        self.provenance={'repository':self.repo,'revision':'b'*40,'release_id':7,'tag':'v0.24.0','assets':{'component.whl':'sha256:'+'b'*64}}
        self.release={'id':7,'tag_name':'v0.24.0','prerelease':False,'draft':False,'immutable':True,
            'assets':[{'name':'component.whl','digest':'sha256:'+'b'*64}]}
    def source(self,repo,revision,path):
        self.assertEqual(repo,self.repo)
        if path=='releases/accepted/provenance.json':return json.dumps(self.provenance).encode()
        if (revision,path) not in self.data:raise ValueError('No accepted stable source metadata')
        return self.data[(revision,path)]
    def live(self,path):
        if path==f'repos/{self.repo}/releases/7':return self.release
        if path==f'repos/{self.repo}/git/ref/tags/v0.24.0':return {'ref':'refs/tags/v0.24.0','object':{'type':'commit','sha':'b'*40}}
        self.fail('Unexpected API request '+path)
    def exercise(self):
        with patch.object(r,'api',return_value={'sha':self.main_sha}),patch.object(r,'source_file',side_effect=self.source),patch.object(r,'latest_stable',return_value={'id':7}),patch.object(accepted,'github_json',side_effect=self.live):
            return r.independent_admission(self.repo,self.revision,'v0.24.1',{'component.whl':b'tested'})
    def test_actual_stable_baseline_and_tested_candidate_pass(self):
        self.assertEqual(self.exercise(),self.main_sha)
    def test_test_snapshot_record_is_rejected_independently_of_ci(self):
        self.provenance['tag']='test-'+'b'*40
        with self.assertRaisesRegex(ValueError,'test snapshots'):self.exercise()
    def test_forged_stable_label_cannot_change_live_prerelease(self):
        self.release['prerelease']=True
        with self.assertRaisesRegex(ValueError,'prerelease or draft'):self.exercise()
    def test_missing_stable_baseline_cannot_be_bootstrapped_from_test_artifacts(self):
        self.data.pop((self.main_sha,'releases/accepted/release.json'))
        with self.assertRaisesRegex(ValueError,'No accepted stable'):self.exercise()
    def test_wrong_artifact_and_changed_patch_contract_are_rejected(self):
        path=(self.revision,'releases/candidate/release.json');original=self.data[path]
        data=json.loads(original);data['components']['component']['artifact']['sha256']='f'*64;self.data[path]=json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError,'actual tested artifact'):self.exercise()
        self.data[path]=original
        raw=b'{"public_api":{"read":"changed"}}';self.data[(self.revision,'releases/candidate/contract.json')]=raw
        data=json.loads(original);data['components']['component']['contract_sha256']=hashlib.sha256(raw).hexdigest();self.data[path]=json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError,'patch changed'):self.exercise()
    def test_tagged_version_sources_cannot_redirect_to_a_decoy(self):
        data={**self.policy,'version_files':['decoy/pyproject.toml']};self.data[(self.revision,'release-policy.json')]=json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError,'version_files'):self.exercise()
    def test_policy_values_do_not_confuse_true_with_one(self):
        data={**self.policy,'schema_version':True};self.data[(self.revision,'release-policy.json')]=json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError,'schema_version'):self.exercise()
    def test_release_inventory_ignores_test_snapshots_and_orders_stable_versions(self):
        stable=lambda n:dict(id=n,tag_name=f'v0.24.{n}',draft=False,prerelease=False)
        records=[stable(1),dict(id=99,tag_name='test-'+'f'*40,draft=False,prerelease=True),stable(2)]
        with patch.object(r,'api',return_value=records):self.assertEqual(r.latest_stable(self.repo)['id'],2)
        with patch.object(r,'api',return_value=records[1:2]),self.assertRaisesRegex(ValueError,'No actual stable'):r.latest_stable(self.repo)
    def test_stale_main_record_cannot_ignore_a_newer_stable_release(self):
        with patch.object(r,'api',return_value={'sha':self.main_sha}),patch.object(r,'source_file',side_effect=self.source),patch.object(r,'latest_stable',return_value={'id':8}),self.assertRaisesRegex(ValueError,'latest actual stable'):
            r.independent_admission(self.repo,self.revision,'v0.24.1',{'component.whl':b'tested'})
    def test_existing_release_rechecks_its_original_preceding_stable_context(self):
        records=[dict(id=7,tag_name='v0.24.0',draft=False,prerelease=False),
                 dict(id=8,tag_name='v0.24.1',draft=False,prerelease=False),
                 dict(id=9,tag_name='v0.25.0',draft=False,prerelease=False)]
        with patch.object(r,'api',return_value=records) as api,patch.object(r,'source_file',side_effect=self.source),patch.object(accepted,'github_json',side_effect=self.live):
            self.assertEqual(r.independent_admission(self.repo,self.revision,'v0.24.1',{'component.whl':b'tested'},baseline_revision=self.main_sha,before_version='0.24.1'),self.main_sha)
            self.assertTrue(all('/releases?' in call.args[0] for call in api.call_args_list))
    def test_mutable_main_cannot_rewrite_the_stable_contract(self):
        raw=b'{"public_api":{"read":"rewritten"}}';self.data[(self.main_sha,'releases/accepted/contract.json')]=raw
        data=json.loads(self.data[(self.main_sha,'releases/accepted/release.json')]);data['components']['component']['contract_sha256']=hashlib.sha256(raw).hexdigest()
        self.data[(self.main_sha,'releases/accepted/release.json')]=json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError,'immutable stable source'):self.exercise()
    def test_qualification_manifest_cannot_be_relabelled_by_copying_its_path(self):
        path=(self.revision,'releases/candidate/release.json');data=json.loads(self.data[path]);data['purpose']='artifact-qualification';data['stable_release']=False;self.data[path]=json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError,'Test qualification'):self.exercise()
    def test_contract_paths_cannot_read_outside_the_metadata_snapshot(self):
        path=(self.main_sha,'releases/accepted/release.json');original=self.data[path]
        for contract in ['/etc/passwd','../../outside','.git/config']:
            with self.subTest(contract=contract):
                data=json.loads(original);data['components']['component']['contract']=contract;self.data[path]=json.dumps(data).encode()
                with self.assertRaisesRegex(ValueError,'Unsafe contract'):self.exercise()
    def test_metadata_reads_are_bounded_and_cannot_escape(self):
        for path in ['../escape','/absolute','.git/config']:
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'Unsafe'):r.source_file(self.repo,self.revision,path)
        response={'type':'file','encoding':'base64','size':3,'content':base64.b64encode(b'abc').decode()}
        with patch.object(r,'api',return_value=response):self.assertEqual(r.source_file(self.repo,self.revision,'pyproject.toml'),b'abc')
        for invalid in [{**response,'encoding':'none'},{**response,'size':4},{**response,'size':r.MAX_METADATA_BYTES+1}]:
            with self.subTest(invalid=invalid),patch.object(r,'api',return_value=invalid),self.assertRaises(ValueError):
                r.source_file(self.repo,self.revision,'pyproject.toml')
