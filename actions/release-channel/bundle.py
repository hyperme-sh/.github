"""Versioned test bundles and explicit byte-preserving promotion.

Only trusted publisher code runs; repository configuration is fetched as data.
Package metadata is deliberately never rewritten.
"""
import json
import os
import re
from pathlib import Path

import release as r

CONFIG = '.github/test-channel.json'
VERSION = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'


def configuration(repo, revision):
    data = json.loads(r.source_file(repo, revision, CONFIG))
    r.require(isinstance(data, dict) and set(data) == {'schema', 'next', 'workflow'}, 'Invalid test channel configuration')
    r.require(type(data['schema']) is int and data['schema'] == 1, 'Unsupported test channel schema')
    r.require(isinstance(data['next'], str) and re.fullmatch(VERSION, data['next']), 'next must be MAJOR.MINOR.PATCH')
    r.require(isinstance(data['workflow'], str) and re.fullmatch(r'\.github/workflows/[A-Za-z0-9_-]+\.ya?ml', data['workflow']), 'Invalid validation workflow')
    return data


def canonical(data):
    return (json.dumps(data, sort_keys=True, indent=2) + '\n').encode()


def inventory(repo, version):
    prefix = f'refs/tags/{version}-test.'
    refs = r.api(f'repos/{repo}/git/matching-refs/tags/{version}-test.')
    r.require(isinstance(refs, list) and len(refs) < 10000, 'Incomplete or excessive test tag inventory')
    result = {}
    for ref in refs:
        name = ref.get('ref', '')
        r.require(name.startswith(prefix) and re.fullmatch(r'0|[1-9][0-9]*', name[len(prefix):]), 'Malformed test tag in target line')
        r.require(ref.get('object', {}).get('type') == 'commit', 'Test tags must identify commits directly')
        result[int(name[len(prefix):])] = (name.removeprefix('refs/tags/'), ref['object']['sha'])
    return result


def verify_test(repo, tag, config):
    r.require(re.fullmatch(re.escape(config['next']) + r'-test\.(0|[1-9][0-9]*)', tag), 'Selected test tag differs from next')
    publication = r.release_by_tag(repo, tag)
    r.require(publication and publication.get('immutable') is True and publication.get('prerelease') is True
              and publication.get('draft') is False, 'Selected test must be a published immutable prerelease')
    files = r.release_files(repo, publication)
    raw = files.get(r.MANIFEST)
    r.require(isinstance(raw, bytes) and len(raw) <= r.MAX_METADATA_BYTES, 'Test manifest required')
    manifest = json.loads(raw)
    keys = {'schema', 'kind', 'repository', 'next', 'tag', 'revision', 'workflow', 'run_id', 'artifact_id', 'assets'}
    r.require(isinstance(manifest, dict) and set(manifest) == keys and canonical(manifest) == raw, 'Noncanonical test manifest')
    r.require(type(manifest['schema']) is int and manifest['schema'] == 1 and manifest['kind'] == 'test-bundle'
              and manifest['repository'] == repo and manifest['next'] == config['next'] and manifest['tag'] == tag
              and manifest['workflow'] == config['workflow'], 'Test manifest identity mismatch')
    revision = manifest['revision']
    r.require(isinstance(revision, str) and re.fullmatch('[0-9a-f]{40}', revision), 'Invalid source revision')
    r.require(r.tag_revision(repo, tag) == revision, 'Test tag source mismatch')
    r.require(configuration(repo, revision) == config, 'Test source configuration differs')
    for key in ('run_id', 'artifact_id'):
        r.require(type(manifest[key]) is int and manifest[key] > 0, 'Invalid test evidence identity')
    payload = {name: data for name, data in files.items() if name != r.MANIFEST}
    r.require(manifest['assets'] == {name: r.digest(data) for name, data in payload.items()}, 'Test asset digest mismatch')
    _, tested = r.tested_files(repo, config['workflow'], revision, manifest['run_id'], manifest['artifact_id'])
    r.require(tested == payload, 'Test release differs from original qualified artifact')
    r.validate_service_channels(payload)
    return revision, files


def stable_exists(repo, version):
    refs = r.api(f'repos/{repo}/git/matching-refs/tags/{version}')
    r.require(isinstance(refs, list), 'Invalid stable tag inventory')
    return any(ref.get('ref') == 'refs/tags/' + version for ref in refs) or r.release_by_tag(repo, version) is not None


def publish_test(repo, event):
    r.require(event.get('repository', {}).get('full_name') == repo, 'Wrong event repository')
    run_id = event.get('workflow_run', {}).get('id')
    r.require(type(run_id) is int and run_id > 0, 'Workflow completion identity required')
    run = r.api(f'repos/{repo}/actions/runs/{run_id}')
    revision = run.get('head_sha')
    r.require(isinstance(revision, str) and re.fullmatch('[0-9a-f]{40}', revision), 'Invalid validation source')
    config = configuration(repo, revision)
    r.require(config == configuration(repo, 'main'), 'Stale next declaration or workflow')
    r.validate_run(run, repo, config['workflow'], revision)
    r.require(r.qualified_run(repo, config['workflow'], revision) == run_id, 'Superseded validation run')
    artifact_id, payload = r.tested_files(repo, config['workflow'], revision, run_id)
    r.validate_service_channels(payload)
    refs = inventory(repo, config['next'])
    matches = [tag for tag, sha in refs.values() if sha == revision]
    r.require(len(matches) <= 1, 'Multiple test tags for one source; inspect manually')
    if matches:
        # Completed retries verify the original manifest and exact bytes. Partial
        # drafts/tags fail closed; never overwrite or silently mint a replacement.
        _, existing = verify_test(repo, matches[0], config)
        r.require({k: v for k, v in existing.items() if k != r.MANIFEST} == payload, 'Rerun changed tested bytes')
        return matches[0]
    r.require(not stable_exists(repo, config['next']), 'next is already stable; declare the next target before publishing new tests')
    tag = f"{config['next']}-test.{max(refs, default=-1) + 1}"
    manifest = dict(schema=1, kind='test-bundle', repository=repo, next=config['next'], tag=tag,
                    revision=revision, workflow=config['workflow'], run_id=run_id, artifact_id=artifact_id,
                    assets={name: r.digest(data) for name, data in sorted(payload.items())})
    # Atomic creation rejects collisions. No force-update, tag deletion or retry
    # with a different number after an ambiguous write.
    r.gh('api', f'repos/{repo}/git/refs', '--method', 'POST', '-f', 'ref=refs/tags/' + tag, '-f', 'sha=' + revision)
    r.require(r.tag_revision(repo, tag) == revision, 'Allocated test tag source mismatch')
    r.publish(repo, tag, revision, {**payload, r.MANIFEST: canonical(manifest)}, True)
    return tag


def promote(repo, tag):
    config = configuration(repo, 'main')
    revision, files = verify_test(repo, tag, config)
    r.require(not r.policy_configured(repo, revision),
              'Component repositories cannot promote bundle labels; select these artifacts in the coordinator instead')
    # Keep even the provenance manifest unchanged: it records the test origin.
    # Stable selection is expressed by the destination GitHub release/tag.
    stable = config['next']
    refs = r.api(f'repos/{repo}/git/matching-refs/tags/{stable}')
    r.require(isinstance(refs, list), 'Invalid stable tag inventory')
    for ref in refs:
        if ref.get('ref') == 'refs/tags/' + stable:
            r.require(r.tag_revision(repo, stable) == revision, 'Stable tag already points elsewhere')
    r.publish(repo, stable, revision, files, False)
    return stable


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    r.require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo), 'Invalid repository')
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    mode = os.environ['BUNDLE_MODE']
    if mode == 'test':
        r.require(os.environ['GITHUB_EVENT_NAME'] == 'workflow_run', 'Test publication requires workflow completion')
        tag = publish_test(repo, event)
    else:
        r.require(mode == 'promote' and os.environ['GITHUB_EVENT_NAME'] == 'workflow_dispatch'
                  and os.environ['GITHUB_REF'] == 'refs/heads/main', 'Promotion requires explicit main dispatch')
        tag = event.get('inputs', {}).get('gold_test', '')
        r.require(isinstance(tag, str) and tag, 'Select an exact gold_test tag')
        tag = promote(repo, tag)
    print('Verified bundle: ' + tag)


if __name__ == '__main__':
    main()
