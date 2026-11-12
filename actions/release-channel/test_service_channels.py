import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

import release
import service_channels as channels
import test_bundle as fixtures
import bundle


POLICY = {'api': 'ghcr.io/hyperme-sh/api/runtime', 'user': 'ghcr.io/hyperme-sh/user/runtime'}


def payload(api='test', user='0.6.1'):
    return {channels.ASSET: json.dumps({'schema': 1, 'services': {
        key: repo + ':' + tag for (key, repo), tag in zip(POLICY.items(), [api, user])
    }}).encode(), 'package.whl': b'original bytes'}


class ServiceChannels(unittest.TestCase):
    def test_shared_owner_vectors(self):
        vectors = json.loads(Path(__file__).with_name("service-reference-vectors.json").read_text())
        for value in vectors["accepted"]:
            self.assertEqual(channels.reference(value, vectors["repository"]), value)
        for value in vectors["rejected"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                channels.reference(value, vectors["repository"])

    def test_independent_peer_versions_remain_tags(self):
        for api, user in [('test', 'test'), ('0.6.0', '0.6.8'), ('0.6.0-test.2', 'v1.2.3')]:
            files = payload(api, user)
            before = dict(files)
            with patch.dict(os.environ, SERVICE_REPOSITORIES=json.dumps(POLICY)), \
                    patch.object(release.subprocess, 'run') as network:
                actual = release.validate_service_channels(files)
            self.assertEqual(actual['api'], POLICY['api'] + ':' + api)
            self.assertEqual(actual['user'], POLICY['user'] + ':' + user)
            self.assertEqual(files, before)
            network.assert_not_called()

    def test_reference_rejects_scope_credentials_injection_and_digest(self):
        repo = POLICY['api']
        for value in [repo, repo + ':', repo + ':test\n', repo + ':test extra',
                      repo + ':$(id)', repo + ':test@sha256:' + 'a'*64,
                      repo + '@sha256:' + 'a'*64, 'https://' + repo + ':test',
                      'user:password@' + repo + ':test', repo + '-evil:test',
                      'evil.io/hyperme-sh/api/runtime:test', repo + ':x'*100]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                channels.reference(value, repo)

    def test_bad_policy(self):
        for repo in ['https://ghcr.io/team/api', 'user:password@ghcr.io/team/api',
                     'ghcr.io/team/../api', 'ghcr.io:65536/team/api', 'ghcr.io/team/api ']:
            with self.subTest(repo=repo), self.assertRaises(ValueError):
                channels.reference(repo + ':test', repo)

    def test_policy_and_complete_asset_required_together(self):
        for files, policy in [({}, POLICY), (payload(), {}), (payload(), {'api': POLICY['api']}),
                              ({channels.ASSET: b'{}'}, POLICY)]:
            with self.subTest(files=files, policy=policy), self.assertRaises(ValueError):
                channels.validate(files, json.dumps(policy))
        self.assertEqual(channels.validate({'package.whl': b'bytes'}, '{}'), {})

    def test_duplicate_keys_and_boolean_schema_refused(self):
        for raw in [b'{"schema":1,"schema":1,"services":{}}',
                    json.dumps({'schema': True, 'services': {k: v+':test' for k,v in POLICY.items()}}).encode()]:
            with self.assertRaises(ValueError):
                channels.validate({channels.ASSET: raw}, json.dumps(POLICY))
        with self.assertRaises(ValueError):
            channels.validate(payload(), '{"api":"a","api":"b"}')


class PublisherChannels(unittest.TestCase):
    def publish(self, files):
        from contextlib import ExitStack
        with ExitStack() as stack:
            for name, value in [('api', fixtures.run()), ('qualified_run', 12),
                                ('tested_files', (34, files)), ('tag_revision', fixtures.SHA)]:
                stack.enter_context(patch.object(release, name, return_value=value))
            stack.enter_context(patch.object(bundle, 'configuration', return_value=fixtures.CONFIG))
            stack.enter_context(patch.object(bundle, 'inventory', return_value={}))
            stack.enter_context(patch.object(bundle, 'stable_exists', return_value=False))
            stack.enter_context(patch.dict(os.environ, SERVICE_REPOSITORIES=json.dumps(POLICY)))
            commands = stack.enter_context(patch.object(release, 'gh'))
            published = stack.enter_context(patch.object(release, 'publish'))
            try:
                bundle.publish_test(fixtures.REPO, {'repository': {'full_name': fixtures.REPO},
                                                   'workflow_run': {'id': 12}})
            except ValueError:
                commands.assert_not_called()
                published.assert_not_called()
                raise
            return published.call_args.args[3]

    def test_test_bundle_keeps_valid_runtime_tags_and_hashes(self):
        original = payload()
        files = self.publish(original)
        self.assertEqual(files[channels.ASSET], original[channels.ASSET])
        manifest = json.loads(files[release.MANIFEST])
        self.assertEqual(manifest['assets'][channels.ASSET], release.digest(original[channels.ASSET]))

    def test_invalid_channels_fail_before_tag_or_release_mutation(self):
        with self.assertRaises(ValueError):
            self.publish(payload(api='test@sha256:' + 'a'*64))
