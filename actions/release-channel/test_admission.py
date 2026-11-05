import unittest
from unittest.mock import patch
from test_release import r


class AdmissionTests(unittest.TestCase):
    repo = 'hyperme-sh/example'
    revision = 'a' * 40
    tag = 'v0.24.0'

    def run_record(self, **changes):
        return dict(id=12, run_attempt=2, repository={'full_name': self.repo},
                    head_repository={'full_name': self.repo}, head_sha=self.revision,
                    head_branch=self.tag, event='push', path='.github/workflows/release-admission.yml',
                    status='completed', conclusion='success', **changes)

    def evidence(self, run=None, job='success', current_only=False):
        policy=[{'name': 'release-policy.json'}]
        replies=[[] if current_only else policy, policy,
                 {'workflow_runs': [run or self.run_record()]},
                 {'jobs': [{'name': 'release-admission / Release compatibility', 'conclusion': job}]}]
        with patch.object(r, 'api', side_effect=replies):
            return r.admission_evidence(self.repo, self.revision, self.tag, attempts=1)

    def test_exact_admission_is_recorded(self):
        self.assertEqual(self.evidence(), (12, 2))

    def test_policy_on_main_still_applies_to_older_tags(self):
        self.assertEqual(self.evidence(current_only=True), (12, 2))
        with self.assertRaises(ValueError):
            self.evidence(current_only=True, job='skipped')

    def test_no_policy_requires_no_compatibility_run(self):
        with patch.object(r, 'api', side_effect=[[], []]) as api:
            self.assertIsNone(r.admission_evidence(self.repo, self.revision, self.tag))
            self.assertEqual(api.call_count, 2)

    def test_missing_or_pending_evidence_is_not_acceptance(self):
        for runs in ([], [{**self.run_record(), 'status': 'in_progress'}]):
            with patch.object(r, 'api', side_effect=[[{'name':'release-policy.json'}], [], {'workflow_runs':runs}]), self.assertRaises(ValueError):
                r.admission_evidence(self.repo, self.revision, self.tag, attempts=1)

    def test_wrong_tag_revision_workflow_fork_or_failure_rejected(self):
        for key, value in [('head_branch','v0.24.1'), ('head_sha','b'*40),
                           ('path','.github/workflows/other.yml'), ('event','pull_request'),
                           ('head_repository',{'full_name':'attacker/fork'}), ('conclusion','failure')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.evidence(run={**self.run_record(), key:value})

    def test_configuration_only_does_not_qualify(self):
        for job in ('skipped', 'failure', None):
            with self.subTest(job=job), self.assertRaises(ValueError):
                self.evidence(job=job)

    def test_api_failure_is_not_missing_policy(self):
        with patch.object(r, 'api', side_effect=RuntimeError('unavailable')), self.assertRaises(RuntimeError):
            r.admission_evidence(self.repo, self.revision, self.tag)
