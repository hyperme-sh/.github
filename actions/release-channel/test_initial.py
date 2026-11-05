import base64
import json
import subprocess
import unittest
from unittest.mock import patch
from test_release import r


class InitialPublicationTests(unittest.TestCase):
    repo = 'hyperme-sh/example'
    sha = 'a' * 40
    files = {'example.whl': b'tested'}

    def exercise(self, *, asset=None, releases=None, claim=None, collision=False):
        bundle = {'schema_version': 1, 'components': {'example': {
            'version': '0.24.0', 'artifact': {'kind': 'package',
            'sha256': asset or r.digest(b'tested').removeprefix('sha256:')}}}}
        replies = [{'encoding': 'base64', 'content': base64.b64encode(json.dumps(bundle).encode()).decode()},
                   releases or [], {'ref': 'refs/heads/release/initial-stable',
                                    'object': {'type': 'commit', 'sha': claim or self.sha}}]
        with patch.object(r, 'api', side_effect=replies), patch.object(r, 'gh') as gh:
            if collision:
                gh.side_effect = subprocess.CalledProcessError(422, ['gh'])
            r.initial_publication(self.repo, self.sha, 'v0.24.0', self.files)
            gh.assert_called_once()

    def test_first_source_claim_and_same_source_retry(self):
        self.exercise()
        self.exercise(collision=True)

    def test_competing_first_source_cannot_publish(self):
        with self.assertRaisesRegex(ValueError, 'Another source'):
            self.exercise(claim='b'*40, collision=True)

    def test_declared_artifact_must_be_in_successful_test_files(self):
        with self.assertRaisesRegex(ValueError, 'tested package'):
            self.exercise(asset='b'*64)

    def test_release_appearing_after_admission_blocks_publication(self):
        with self.assertRaisesRegex(ValueError, 'Stable release already exists'):
            self.exercise(releases=[{'prerelease': False}])

    def test_unknown_release_classification_fails_closed(self):
        with self.assertRaisesRegex(ValueError, 'Stable release already exists'):
            self.exercise(releases=[{}])

    def test_initial_job_requires_new_publisher_mode(self):
        run = dict(id=12, run_attempt=1, repository={'full_name': self.repo},
                   head_repository={'full_name': self.repo}, head_sha=self.sha,
                   head_branch='v0.24.0', event='push', path='.github/workflows/release-admission.yml',
                   status='completed', conclusion='success')
        replies = [[{'name': 'release-policy.json'}], [], {'workflow_runs': [run]},
                   {'jobs': [{'name': 'release-admission / Initial release admission', 'conclusion': 'success'},
                             {'name': 'release-admission / Release compatibility', 'conclusion': 'skipped'}]}]
        with patch.object(r, 'api', side_effect=replies):
            self.assertEqual(r.admission_evidence(self.repo, self.sha, 'v0.24.0', attempts=1, include_mode=True), (12, True))
        with patch.object(r, 'api', side_effect=replies), self.assertRaises(ValueError):
            r.admission_evidence(self.repo, self.sha, 'v0.24.0', attempts=1)

    def test_complete_history_is_checked_before_claiming(self):
        bundle = {'schema_version': 1, 'components': {'example': {
            'version': '0.24.0', 'artifact': {'kind': 'package',
            'sha256': r.digest(b'tested').removeprefix('sha256:')}}}}
        replies = [{'encoding': 'base64', 'content': base64.b64encode(json.dumps(bundle).encode()).decode()},
                   [{'prerelease': True}] * 100, [{'prerelease': False}]]
        with patch.object(r, 'api', side_effect=replies) as api, patch.object(r, 'gh') as gh:
            with self.assertRaisesRegex(ValueError, 'Stable release already exists'):
                r.initial_publication(self.repo, self.sha, 'v0.24.0', self.files)
            self.assertTrue(api.call_args.args[0].endswith('page=2'))
            gh.assert_not_called()

    def test_claim_read_failure_does_not_assume_ownership(self):
        bundle = {'schema_version': 1, 'components': {'example': {
            'version': '0.24.0', 'artifact': {'kind': 'package',
            'sha256': r.digest(b'tested').removeprefix('sha256:')}}}}
        replies = [{'encoding': 'base64', 'content': base64.b64encode(json.dumps(bundle).encode()).decode()},
                   [], RuntimeError('unavailable')]
        with patch.object(r, 'api', side_effect=replies), patch.object(r, 'gh', side_effect=subprocess.CalledProcessError(1, ['gh'])):
            with self.assertRaises(RuntimeError):
                r.initial_publication(self.repo, self.sha, 'v0.24.0', self.files)
