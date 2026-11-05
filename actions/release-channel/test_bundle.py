import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bundle as b

REPO = 'hyperme-sh/example'
SHA = 'a' * 40
CONFIG = dict(schema=1, next='0.24.0', workflow='.github/workflows/package.yml')
PAYLOAD = {'original-0.2.0.whl': b'original package metadata and bytes'}


def run():
    return dict(id=12, repository={'full_name': REPO}, head_repository={'full_name': REPO},
                head_sha=SHA, head_branch='main', event='push', path=CONFIG['workflow'],
                status='completed', conclusion='success')


def manifest():
    return dict(schema=1, kind='test-bundle', repository=REPO, next='0.24.0', tag='0.24.0-test.0',
                revision=SHA, workflow=CONFIG['workflow'], run_id=12, artifact_id=34,
                assets={n: b.r.digest(v) for n, v in PAYLOAD.items()})


class BundleTests(unittest.TestCase):
    def setUp(self):
        policy = patch.object(b.r, 'policy_configured', return_value=False)
        self.policy_configured = policy.start()
        self.addCleanup(policy.stop)
        stub = patch.object(b, 'stable_exists', return_value=False)
        self.stable_exists = stub.start()
        self.addCleanup(stub.stop)

    def test_stable_target_cannot_mint_new_test(self):
        self.stable_exists.return_value = True
        with self.assertRaisesRegex(ValueError, 'already stable'): self.publish()

    def test_next_configuration(self):
        for changes in [{}, {'next': '0.24.0-test.0'}, {'next': '01.0.0'}, {'next': '1.0'},
                        {'next': '0.24.0\n'}, {'schema': True}, {'workflow': '../evil'}, {'extra': True}]:
            with self.subTest(changes=changes), patch.object(b.r, 'source_file', return_value=json.dumps({**CONFIG, **changes}).encode()):
                if changes:
                    with self.assertRaises(ValueError): b.configuration(REPO, SHA)
                else: self.assertEqual(b.configuration(REPO, SHA), CONFIG)

    def test_inventory_numbers_not_lexical(self):
        refs = [{'ref': f'refs/tags/0.24.0-test.{n}', 'object': {'type': 'commit', 'sha': str(n)*40}} for n in [0, 9, 10]]
        with patch.object(b.r, 'api', return_value=refs):
            self.assertEqual(max(b.inventory(REPO, '0.24.0')), 10)
        for name in ['00', '-1', '1-other', 'x']:
            with patch.object(b.r, 'api', return_value=[{'ref': 'refs/tags/0.24.0-test.'+name}]), self.assertRaises(ValueError):
                b.inventory(REPO, '0.24.0')

    def publish(self, record=None, refs=None):
        event = {'repository': {'full_name': REPO}, 'workflow_run': {'id': 12}}
        with patch.object(b.r, 'api', return_value=record or run()), \
             patch.object(b, 'configuration', return_value=CONFIG), \
             patch.object(b.r, 'qualified_run', return_value=12), \
             patch.object(b.r, 'tested_files', return_value=(34, PAYLOAD)), \
             patch.object(b, 'inventory', return_value=refs or {}), \
             patch.object(b.r, 'tag_revision', return_value=SHA), \
             patch.object(b.r, 'gh') as command, patch.object(b.r, 'publish') as publish:
            tag = b.publish_test(REPO, event)
            return tag, command.call_args_list, publish.call_args

    def test_test_publication_preserves_payload(self):
        tag, commands, published = self.publish()
        self.assertEqual(tag, '0.24.0-test.0')
        self.assertEqual(len(commands), 1)
        self.assertIn('ref=refs/tags/0.24.0-test.0', commands[0].args)
        self.assertEqual(published.args[:3], (REPO, tag, SHA))
        self.assertTrue(published.args[4])
        self.assertEqual(published.args[3], {**PAYLOAD, b.r.MANIFEST: b.canonical(manifest())})
        self.assertEqual(self.publish(refs={9: ('0.24.0-test.9', 'b'*40)})[0], '0.24.0-test.10')

    def test_bad_runs_cannot_publish(self):
        for changes in [{'event': 'pull_request'}, {'conclusion': 'failure'}, {'status': 'in_progress'},
                        {'head_branch': 'feature'}, {'head_repository': {'full_name': 'evil/fork'}},
                        {'path': '.github/workflows/other.yml'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError): self.publish({**run(), **changes})

    def test_stale_next_fails_before_any_mutation(self):
        with patch.object(b.r, 'api', return_value=run()), \
             patch.object(b, 'configuration', side_effect=[CONFIG, {**CONFIG, 'next': '0.25.0'}]), \
             patch.object(b.r, 'gh') as command, self.assertRaisesRegex(ValueError, 'Stale next'):
            b.publish_test(REPO, {'repository': {'full_name': REPO}, 'workflow_run': {'id': 12}})
        command.assert_not_called()

    def test_collision_is_not_retried_or_overwritten(self):
        with patch.object(b.r, 'gh', side_effect=RuntimeError('collision')) as command, \
             patch.object(b.r, 'api', return_value=run()), patch.object(b, 'configuration', return_value=CONFIG), \
             patch.object(b.r, 'qualified_run', return_value=12), patch.object(b.r, 'tested_files', return_value=(34,PAYLOAD)), \
             patch.object(b, 'inventory', return_value={}), patch.object(b.r, 'publish') as publish:
            with self.assertRaises(RuntimeError):
                b.publish_test(REPO, {'repository': {'full_name': REPO}, 'workflow_run': {'id': 12}})
        self.assertEqual(command.call_count, 1)
        publish.assert_not_called()

    def test_rerun_verifies_without_mutation(self):
        files = {**PAYLOAD, b.r.MANIFEST: b.canonical(manifest())}
        with patch.object(b.r, 'api', return_value=run()), patch.object(b, 'configuration', return_value=CONFIG), \
             patch.object(b.r, 'qualified_run', return_value=12), patch.object(b.r, 'tested_files', return_value=(34, PAYLOAD)), \
             patch.object(b, 'inventory', return_value={0: ('0.24.0-test.0', SHA)}), \
             patch.object(b, 'verify_test', return_value=(SHA, files)), patch.object(b.r, 'gh') as command, \
             patch.object(b.r, 'publish') as publish:
            self.assertEqual(b.publish_test(REPO, {'repository': {'full_name': REPO}, 'workflow_run': {'id':12}}), '0.24.0-test.0')
            files['original-0.2.0.whl'] = b'changed'
            with self.assertRaisesRegex(ValueError, 'changed tested bytes'):
                b.publish_test(REPO, {'repository': {'full_name': REPO}, 'workflow_run': {'id':12}})
        command.assert_not_called(); publish.assert_not_called()

    def test_verify_requires_original_actions_bytes_and_manifest(self):
        for mutation in ['none', 'payload', 'digest', 'source', 'config', 'expired', 'mutable', 'draft', 'identity']:
            files = {**PAYLOAD, b.r.MANIFEST: b.canonical(manifest())}
            m = manifest()
            if mutation == 'payload': files['original-0.2.0.whl'] = b'evil'
            if mutation == 'digest': m['assets'] = {}
            if mutation == 'identity': m['repository'] = 'evil/fork'
            files[b.r.MANIFEST] = b.canonical(m)
            release = dict(immutable=mutation!='mutable', draft=mutation=='draft', prerelease=True)
            with self.subTest(mutation=mutation), patch.object(b.r, 'release_by_tag', return_value=release), \
                 patch.object(b.r, 'release_files', return_value=files), \
                 patch.object(b.r, 'tag_revision', return_value='b'*40 if mutation=='source' else SHA), \
                 patch.object(b, 'configuration', return_value={} if mutation=='config' else CONFIG), \
                 patch.object(b.r, 'tested_files', side_effect=ValueError('expired') if mutation=='expired' else None,
                              return_value=(34,PAYLOAD)):
                if mutation == 'none': self.assertEqual(b.verify_test(REPO,'0.24.0-test.0',CONFIG), (SHA,files))
                else:
                    with self.assertRaises(ValueError): b.verify_test(REPO,'0.24.0-test.0',CONFIG)

    def test_promotion_copies_every_byte_and_rejects_other_stable_source(self):
        files = {**PAYLOAD, b.r.MANIFEST: b.canonical(manifest())}
        with patch.object(b, 'configuration', return_value=CONFIG), patch.object(b, 'verify_test', return_value=(SHA,files)), \
             patch.object(b.r, 'api', return_value=[]), patch.object(b.r, 'publish') as publish:
            self.assertEqual(b.promote(REPO,'0.24.0-test.0'),'0.24.0')
            publish.assert_called_once_with(REPO,'0.24.0',SHA,files,False)
        with patch.object(b, 'configuration', return_value=CONFIG), patch.object(b, 'verify_test', return_value=(SHA,files)), \
             patch.object(b.r, 'api', return_value=[{'ref':'refs/tags/0.24.0'}]), \
             patch.object(b.r, 'tag_revision', return_value='b'*40), patch.object(b.r, 'publish') as publish:
            with self.assertRaisesRegex(ValueError,'already points elsewhere'): b.promote(REPO,'0.24.0-test.0')
        publish.assert_not_called()

    def test_component_policy_prevents_stable_bundle_namespace_collision(self):
        self.policy_configured.return_value = True
        with patch.object(b, 'configuration', return_value=CONFIG), \
             patch.object(b, 'verify_test', return_value=(SHA, PAYLOAD)), \
             patch.object(b.r, 'publish') as publish:
            with self.assertRaisesRegex(ValueError, 'Component repositories cannot promote'):
                b.promote(REPO, '0.24.0-test.0')
        publish.assert_not_called()
        self.policy_configured.assert_called_once_with(REPO, SHA)

    def test_promotion_requires_explicit_dispatch_on_main(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'event.json'; path.write_text(json.dumps({'inputs':{'gold_test':'0.24.0-test.0'}}))
            for event, ref, allowed in [('workflow_dispatch','refs/heads/main',True),('push','refs/tags/0.24.0',False),
                                        ('workflow_run','refs/heads/main',False),('workflow_dispatch','refs/heads/feature',False)]:
                env={'GITHUB_REPOSITORY':REPO,'GITHUB_EVENT_PATH':str(path),'BUNDLE_MODE':'promote',
                     'GITHUB_EVENT_NAME':event,'GITHUB_REF':ref}
                with patch.dict(os.environ,env), patch.object(b,'promote') as promote:
                    if allowed: b.main(); promote.assert_called_once_with(REPO,'0.24.0-test.0')
                    else:
                        with self.assertRaises(ValueError): b.main()
                        promote.assert_not_called()
