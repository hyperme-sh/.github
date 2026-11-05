import json
import subprocess
import unittest
from unittest.mock import patch
from test_release import r
import test_independent_admission as independent_tests


class InitialClaimTests(unittest.TestCase):
    repo='hyperme-sh/component'; sha='a'*40
    def claim(self, sha=None, collision=False, existing=False):
        reply={'ref':'refs/heads/release/initial-stable','object':{'type':'commit','sha':sha or self.sha}}
        with patch.object(r,'api',return_value=reply),patch.object(r,'gh') as gh:
            if collision:gh.side_effect=subprocess.CalledProcessError(422,['gh'])
            r.initial_source_claim(self.repo,self.sha,existing=existing)
            self.assertEqual(gh.call_count,0 if existing else 1)
    def test_atomic_claim_same_source_retry_and_read_only_recovery(self):
        self.claim();self.claim(collision=True);self.claim(existing=True)
    def test_competing_revision_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'Another source'):self.claim(sha='b'*40,collision=True)
    def test_unknown_claim_is_not_assumed_owned(self):
        with patch.object(r,'api',side_effect=RuntimeError('offline')),patch.object(r,'gh',side_effect=subprocess.CalledProcessError(1,['gh'])),self.assertRaises(RuntimeError):
            r.initial_source_claim(self.repo,self.sha)
    def test_initial_job_requires_new_publisher_mode(self):
        run=dict(id=12,run_attempt=1,repository={'full_name':self.repo},head_repository={'full_name':self.repo},
                 head_sha=self.sha,head_branch='v0.24.0',event='push',path='.github/workflows/release-admission.yml',status='completed',conclusion='success')
        jobs={'jobs':[{'name':'release-admission / Initial release admission','conclusion':'success'},
                      {'name':'release-admission / Release compatibility','conclusion':'skipped'}]}
        with patch.object(r,'api',return_value=jobs):
            self.assertEqual(r.check_admission_record(self.repo,self.sha,'v0.24.0',run,include_mode=True),(12,1,True))
            with self.assertRaises(ValueError):r.check_admission_record(self.repo,self.sha,'v0.24.0',run)


class InitialIndependentTests(unittest.TestCase):
    repo=independent_tests.IndependentAdmissionTests.repo; main_sha=independent_tests.IndependentAdmissionTests.main_sha; revision=independent_tests.IndependentAdmissionTests.revision
    setUp=independent_tests.IndependentAdmissionTests.setUp
    source=independent_tests.IndependentAdmissionTests.source
    def exercise(self, history=None, before=None):
        def api(path):
            if path.endswith('/commits/main'):return {'sha':self.main_sha}
            if '/releases?' in path:return history(path) if callable(history) else (history or [])
            self.fail(path)
        options={'baseline_revision':self.main_sha,'before_version':before} if before else {}
        with patch.object(r,'api',side_effect=api),patch.object(r,'source_file',side_effect=self.source):
            return r.independent_admission(self.repo,self.revision,'v0.24.1',{'component.whl':b'tested'},initial=True,**options)
    def test_first_declaration_independently_binds_versions_contracts_and_bytes(self):
        self.assertEqual(self.exercise(),self.main_sha)
    def test_stable_created_after_ci_blocks_publication(self):
        with self.assertRaisesRegex(ValueError,'baseline is required'):self.exercise([{'prerelease':False,'tag_name':'v0.24.0'}])
    def test_complete_history_before_claim(self):
        with self.assertRaisesRegex(ValueError,'baseline is required'):
            self.exercise(lambda path:[{'prerelease':True}]*100 if path.endswith('page=1') else [{'prerelease':False}])
    def test_forged_asset_and_tag_policy_cannot_borrow_initial_ci(self):
        path=(self.revision,'releases/candidate/release.json');data=json.loads(self.data[path]);data['components']['component']['artifact']['sha256']='f'*64;self.data[path]=json.dumps(data).encode()
        with self.assertRaisesRegex(ValueError,'actual tested artifact'):self.exercise()
    def test_existing_initial_recovery_ignores_only_same_or_later_versions(self):
        records=[{'prerelease':False,'tag_name':'v0.24.1'},{'prerelease':False,'tag_name':'v1.0.0'}]
        self.assertEqual(self.exercise(records,before='0.24.1'),self.main_sha)
        with self.assertRaisesRegex(ValueError,'baseline is required'):
            self.exercise([*records,{'prerelease':False,'tag_name':'v0.24.0'}],before='0.24.1')
    def test_recovery_filter_preserves_pagination(self):
        with self.assertRaisesRegex(ValueError,'baseline is required'):
            self.exercise(lambda path:[{'prerelease':False,'tag_name':'v1.0.0'}]*100 if path.endswith('page=1') else [{'prerelease':False,'tag_name':'v0.24.0'}],before='0.24.1')
