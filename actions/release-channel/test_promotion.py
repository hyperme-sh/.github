import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_release import r


class PromotionTests(unittest.TestCase):
    def exercise(self, asset=b'tested', manifest_changes=None, event='push', ref='refs/tags/v1.2.3', initial=False):
        repo='hyperme-sh/example'
        sha='a'*40
        manifest=dict(schema=1, repository=repo, channel='test', tag='test-'+sha,
                      revision=sha, workflow='.github/workflows/package.yml', run_id=3,
                      artifact_id=7, assets={'example.whl':r.digest(b'tested')})
        manifest.update(manifest_changes or {})
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'event.json'
            path.write_text('{}')
            with patch.dict(os.environ, dict(GITHUB_REPOSITORY=repo,
                            VALIDATION_WORKFLOW='.github/workflows/package.yml',
                            GITHUB_EVENT_PATH=str(path), GITHUB_EVENT_NAME=event, GITHUB_REF=ref)), \
                    patch.object(r,'tag_revision',return_value=sha), \
                    patch.object(r,'admission_evidence',return_value=(11, initial)) as admission, \
                    patch.object(r,'release_by_tag',return_value=dict(
                        immutable=True, prerelease=True, draft=False, tag_name='test-'+sha)), \
                    patch.object(r,'release_files',return_value={
                        r.MANIFEST:json.dumps(manifest).encode(), 'example.whl':asset}), \
                    patch.object(r,'tested_files',return_value=(7,{'example.whl':b'tested'})), \
                    patch.object(r,'initial_publication') as initial_publication, \
                    patch.object(r,'publish') as publish:
                r.main()
                admission.assert_called_once_with(repo, sha, 'v1.2.3', include_mode=True)
                self.assertEqual(initial_publication.call_count, int(initial))
                return publish.call_args

    def test_promotes_exact_bytes_and_evidence(self):
        args=self.exercise().args
        self.assertEqual(args[:3],('hyperme-sh/example','v1.2.3','a'*40))
        self.assertEqual(args[3]['example.whl'],b'tested')
        manifest=json.loads(args[3][r.MANIFEST])
        self.assertEqual((manifest['channel'],manifest['run_id'],manifest['artifact_id']),('prod',3,7))
        self.assertFalse(args[4])
        self.assertEqual(manifest['admission_run_id'], 11)

    def test_forged_candidate_cannot_borrow_a_green_run(self):
        with self.assertRaisesRegex(ValueError,'differs from successful Actions artifact'):
            self.exercise(asset=b'forged')

    def test_wrong_manifest_identity_and_digests_fail(self):
        for changes in [{'repository':'attacker/example'}, {'revision':'b'*40},
                        {'workflow':'.github/workflows/other.yml'}, {'channel':'prod'},
                        {'assets':{'example.whl':'sha256:forged'}}, {'extra':'field'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.exercise(manifest_changes=changes)

    def test_nonstable_and_nonpush_events_fail(self):
        for ref in ['refs/heads/main','refs/tags/v1.2.3-rc.1','refs/tags/v01.2.3']:
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.exercise(ref=ref)
        with self.assertRaises(ValueError):
            self.exercise(event='workflow_dispatch')

    def test_initial_mode_claims_before_publishing_tested_bytes(self):
        self.assertEqual(self.exercise(initial=True).args[3]["example.whl"], b"tested")
