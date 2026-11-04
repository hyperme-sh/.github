import importlib.util
import io
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

spec = importlib.util.spec_from_file_location('release_channel', Path(__file__).with_name('release.py'))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def archive(entries):
    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w') as z:
        for name, data in entries:
            z.writestr(name, data)
    return out.getvalue()


class ReleaseTests(unittest.TestCase):
    def run_record(self):
        return dict(repository={'full_name': 'hyperme-sh/example'},
                    head_repository={'full_name': 'hyperme-sh/example'},
                    head_sha='a' * 40, head_branch='main', event='push',
                    path='.github/workflows/package.yml', status='completed', conclusion='success')

    def test_only_successful_same_repo_main_push(self):
        run = self.run_record()
        r.validate_run(run, 'hyperme-sh/example', '.github/workflows/package.yml', 'a' * 40)
        for field, value in [('head_repository', {'full_name': 'attacker/example'}),
                             ('head_branch', 'feature'), ('event', 'pull_request'),
                             ('path', '.github/workflows/other.yml'), ('head_sha', 'b' * 40),
                             ('conclusion', 'failure'), ('status', 'in_progress')]:
            with self.subTest(field=field), self.assertRaises(ValueError):
                r.validate_run({**run, field: value}, 'hyperme-sh/example',
                               '.github/workflows/package.yml', 'a' * 40)

    def test_untrusted_archive_paths(self):
        for name in ['../escape', '/absolute', 'nested/file', 'release-manifest.json', '.', '..']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                r.unpack(archive([(name, b'bad')]))
        self.assertEqual(r.unpack(archive([('package.whl', b'exact bytes')])),
                         {'package.whl': b'exact bytes'})

    def test_symlink_and_duplicate_rejected(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            entry = zipfile.ZipInfo('symlink')
            entry.external_attr = 0o120777 << 16
            z.writestr(entry, '../target')
        with self.assertRaises(ValueError):
            r.unpack(out.getvalue())
        with self.assertWarns(UserWarning):
            data = archive([('same', b'a'), ('same', b'b')])
        with self.assertRaises(ValueError):
            r.unpack(data)

    def test_download_verified_against_actions_digest(self):
        data = archive([('package.whl', b'tested')])
        artifact = dict(id=42, name='tested-dist', expired=False,
                        size_in_bytes=len(data), digest=r.digest(data))
        for changes, succeeds in [({}, True), ({'digest': 'sha256:forged'}, False),
                                   ({'expired': True}, False)]:
            with self.subTest(changes=changes), patch.object(r, 'api', side_effect=[
                self.run_record(), {'artifacts': [{**artifact, **changes}]}]), \
                    patch.object(r, 'gh', return_value=data):
                if succeeds:
                    self.assertEqual(r.tested_files('hyperme-sh/example',
                                     '.github/workflows/package.yml', 'a' * 40, 1, 42),
                                     (42, {'package.whl': b'tested'}))
                else:
                    with self.assertRaises(ValueError):
                        r.tested_files('hyperme-sh/example', '.github/workflows/package.yml',
                                       'a' * 40, 1, 42)

    def test_wrong_artifact_id_and_ambiguous_artifacts_fail(self):
        artifact = dict(id=42, name='tested-dist')
        for artifacts, requested in [([artifact], 43), ([artifact, artifact], None), ([], None)]:
            with patch.object(r, 'api', side_effect=[self.run_record(), {'artifacts': artifacts}]), \
                    self.assertRaises(ValueError):
                r.tested_files('hyperme-sh/example', '.github/workflows/package.yml',
                               'a' * 40, 1, requested)

    def test_existing_publication_must_match(self):
        with patch.object(r, 'api', return_value={'enabled': True}), \
                patch.object(r, 'release_by_tag', return_value={
                    'draft': False, 'immutable': True, 'prerelease': False}), \
                patch.object(r, 'tag_revision', return_value='a' * 40), \
                patch.object(r, 'release_files', return_value={'package.whl': b'changed'}), \
                self.assertRaises(ValueError):
            r.publish('hyperme-sh/example', 'v1.0.0', 'a' * 40, {'package.whl': b'tested'}, False)

    def test_publication_requires_immutability(self):
        with patch.object(r, 'api', return_value={'enabled': False}), \
                patch.object(r, 'gh') as command, self.assertRaises(ValueError):
            r.publish('hyperme-sh/example', 'v1.0.0', 'a' * 40, {}, False)
        command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
