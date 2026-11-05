import json
import os
import unittest
from unittest.mock import patch
from test_release import r


class PromotionTests(unittest.TestCase):
    def exercise(self, event='push', ref='refs/tags/v1.2.3', independent_error=None):
        repo='hyperme-sh/example';sha='a'*40
        def independent(*args):
            self.assertEqual(args,(repo,sha,'v1.2.3',{'example.whl':b'tested'}))
            if independent_error:raise independent_error
            return 'c'*40
        with patch.dict(os.environ,dict(GITHUB_REPOSITORY=repo,
                VALIDATION_WORKFLOW='.github/workflows/package.yml',GITHUB_EVENT_NAME=event,GITHUB_REF=ref)), \
                patch.object(r,'tag_revision',return_value=sha), \
                patch.object(r,'release_by_tag',return_value=None), \
                patch.object(r,'admission_evidence',return_value=(11,2)) as admission, \
                patch.object(r,'qualified_run',return_value=3), \
                patch.object(r,'tested_files',return_value=(7,{'example.whl':b'tested'})), \
                patch.object(r,'independent_admission',side_effect=independent), \
                patch.object(r,'publish') as publish:
            try:r.main()
            except ValueError:
                publish.assert_not_called()
                raise
            admission.assert_called_once_with(repo,sha,'v1.2.3')
            return publish.call_args

    def test_publishes_exact_actions_bytes_with_independent_evidence(self):
        args=self.exercise().args
        self.assertEqual(args[:3],('hyperme-sh/example','v1.2.3','a'*40))
        self.assertEqual(args[3]['example.whl'],b'tested')
        manifest=json.loads(args[3][r.MANIFEST])
        self.assertEqual((manifest['channel'],manifest['run_id'],manifest['artifact_id']),('prod',3,7))
        self.assertEqual(manifest['policy_baseline_revision'],'c'*40)
        self.assertEqual((manifest['admission_run_id'],manifest['admission_run_attempt']),(11,2))
        self.assertEqual(manifest['assets'],{'example.whl':r.digest(b'tested')})
        self.assertFalse(args[4])

    def test_forged_green_ci_cannot_bypass_stable_baseline_verification(self):
        with self.assertRaisesRegex(ValueError,'test snapshot'):
            self.exercise(independent_error=ValueError('test snapshot is not stable acceptance'))

    def test_main_completion_and_nonstable_events_never_publish(self):
        for event in ['workflow_run','workflow_dispatch','pull_request']:
            with self.subTest(event=event),self.assertRaisesRegex(ValueError,'disabled'):
                self.exercise(event=event)
        for ref in ['refs/heads/main','refs/tags/test-'+'a'*40,'refs/tags/v1.2.3-rc.1','refs/tags/v01.2.3']:
            with self.subTest(ref=ref),self.assertRaises(ValueError):self.exercise(ref=ref)

    def test_latest_main_run_is_required_for_exact_source(self):
        run=dict(id=3,repository={'full_name':'hyperme-sh/example'},head_repository={'full_name':'hyperme-sh/example'},
                 head_sha='a'*40,head_branch='main',event='push',path='.github/workflows/package.yml',status='completed',conclusion='success')
        with patch.object(r,'api',return_value={'workflow_runs':[run]}):
            self.assertEqual(r.qualified_run('hyperme-sh/example','.github/workflows/package.yml','a'*40),3)
        for invalid in [[],[{**run,'head_sha':'b'*40}],[run,{**run,'id':4,'status':'in_progress'}]]:
            with self.subTest(invalid=invalid),patch.object(r,'api',return_value={'workflow_runs':invalid}),self.assertRaises(ValueError):
                r.qualified_run('hyperme-sh/example','.github/workflows/package.yml','a'*40)
        with patch.object(r,'api',side_effect=[{'workflow_runs':[{**run,'head_sha':'b'*40}]*100},{'workflow_runs':[run]}]):
            self.assertEqual(r.qualified_run('hyperme-sh/example','.github/workflows/package.yml','a'*40),3)
