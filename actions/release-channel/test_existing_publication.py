import json
import os
import unittest
from unittest.mock import patch
from test_release import r


class ExistingPublicationTests(unittest.TestCase):
    repo='hyperme-sh/example';revision='a'*40;tag='v1.2.3'
    def setUp(self):
        self.files={'example.whl':b'tested'}
        self.initial_job=False
        self.claim_revision=self.revision
        self.manifest=dict(schema=1,repository=self.repo,channel='prod',tag=self.tag,revision=self.revision,
            workflow='.github/workflows/package.yml',run_id=3,artifact_id=7,assets={'example.whl':r.digest(b'tested')},
            admission_run_id=11,admission_run_attempt=2,policy_baseline_revision='c'*40)
        self.release=dict(id=99,tag_name=self.tag,immutable=True,prerelease=False,draft=False)
        self.run=dict(id=11,run_attempt=2,repository={'full_name':self.repo},head_repository={'full_name':self.repo},
            head_sha=self.revision,head_branch=self.tag,event='push',path='.github/workflows/release-admission.yml',status='completed',conclusion='success')
    def api(self,path):
        if path==f'repos/{self.repo}/actions/runs/11/attempts/2':return self.run
        if path==f'repos/{self.repo}/actions/runs/11/attempts/2/jobs?per_page=100&page=1':
            return {'jobs':[{'name':'release-admission / '+('Initial release admission' if self.initial_job else 'Release compatibility'),'conclusion':'success'}]}
        if path==f'repos/{self.repo}/git/ref/heads/release/initial-stable':
            return {'ref':'refs/heads/release/initial-stable','object':{'type':'commit','sha':self.claim_revision}}
        self.fail('Unexpected API request: '+path)
    def exercise(self):
        published={**self.files,r.MANIFEST:(json.dumps(self.manifest,sort_keys=True,indent=2)+'\n').encode()}
        with patch.dict(os.environ,dict(GITHUB_REPOSITORY=self.repo,VALIDATION_WORKFLOW='.github/workflows/package.yml',GITHUB_EVENT_NAME='push',GITHUB_REF='refs/tags/'+self.tag)), \
                patch.object(r,'tag_revision',return_value=self.revision),patch.object(r,'release_by_tag',return_value=self.release), \
                patch.object(r,'release_files',return_value=published),patch.object(r,'policy_configured',return_value=True), \
                patch.object(r,'api',side_effect=self.api),patch.object(r,'tested_files',return_value=(7,{'example.whl':b'tested'})) as tested, \
                patch.object(r,'independent_admission',return_value='c'*40) as independent, \
                patch.object(r,'admission_evidence') as current_admission,patch.object(r,'qualified_run') as current_validation,patch.object(r,'publish') as publish:
            try:r.main()
            finally:
                publish.assert_not_called();current_admission.assert_not_called();current_validation.assert_not_called()
            tested.assert_called_once_with(self.repo,'.github/workflows/package.yml',self.revision,3,7)
            options={'initial':True} if self.manifest.get('initial_release') else {}
            independent.assert_called_once_with(self.repo,self.revision,self.tag,self.files,baseline_revision='c'*40,before_version='1.2.3',**options)
    def test_retry_preserves_original_artifact_admission_attempt_and_baseline(self):self.exercise()
    def test_tampered_published_bytes_do_not_qualify_for_recovery(self):
        self.files['example.whl']=b'forged'
        with self.assertRaisesRegex(ValueError,'asset digest mismatch'):self.exercise()
        self.manifest['assets']['example.whl']=r.digest(b'forged')
        with self.assertRaisesRegex(ValueError,'original tested artifact'):self.exercise()
    def test_wrong_original_admission_attempt_or_failed_proof_is_rejected(self):
        self.run['run_attempt']=3
        with self.assertRaisesRegex(ValueError,'Original admission identity'):self.exercise()
        self.run['run_attempt']=2;self.run['conclusion']='failure'
        with self.assertRaisesRegex(ValueError,'did not succeed'):self.exercise()
    def test_mutable_or_prerelease_existing_result_is_not_recovery(self):
        self.release['prerelease']=True
        with self.assertRaisesRegex(ValueError,'immutable stable'):self.exercise()

    def test_initial_retry_preserves_original_evidence_without_mutating_claim(self):
        self.manifest['initial_release']=True;self.initial_job=True
        with patch.object(r,'gh') as gh:
            self.exercise()
            gh.assert_not_called()
    def test_initial_mode_cannot_be_forged_or_claim_substituted(self):
        self.manifest['initial_release']=True
        with self.assertRaisesRegex(ValueError,'Original initial admission'):self.exercise()
        self.initial_job=True;self.claim_revision='d'*40
        with self.assertRaisesRegex(ValueError,'Another source'):self.exercise()
