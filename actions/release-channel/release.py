"""Publish immutable GitHub package snapshots without executing repository code."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlencode
import zipfile

ARTIFACT = 'tested-dist'
MANIFEST = 'release-manifest.json'
MAX_BYTES = 512 * 1024 * 1024


def require(condition, message):
    if not condition:
        raise ValueError(message)


def gh(*args, binary=False):
    result = subprocess.run(['gh', *args], check=True, capture_output=True)
    return result.stdout if binary else result.stdout.decode()


def api(path):
    return json.loads(gh('api', path))


def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def unpack(data):
    """Only flat regular files; never extract a candidate-controlled path."""
    require(len(data) <= MAX_BYTES, 'Artifact archive too large')
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        require(sum(i.file_size for i in archive.infolist()) <= MAX_BYTES,
                'Expanded artifact too large')
        for entry in archive.infolist():
            name = entry.filename
            require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.+-]*', name)
                    and name != MANIFEST and name not in result,
                    'Invalid or duplicate artifact filename')
            mode = (entry.external_attr >> 16) & 0o170000
            require(mode in (0, 0o100000), 'Artifact is not a regular file')
            result[name] = archive.read(entry)
    require(bool(result), 'Empty artifact')
    return result


def validate_run(run, repo, workflow, revision):
    require(run['repository']['full_name'] == repo, 'Wrong run repository')
    require(run['head_repository']['full_name'] == repo, 'Fork run')
    require(run['head_sha'] == revision, 'Wrong run revision')
    require(run['head_branch'] == 'main' and run['event'] == 'push',
            'Only main push validation qualifies')
    require(run['path'] == workflow, 'Wrong validation workflow')
    require(run['status'] == 'completed' and run['conclusion'] == 'success',
            'Validation did not succeed')


def tested_files(repo, workflow, revision, run_id, artifact_id=None):
    base = f'repos/{repo}'
    run = api(f'{base}/actions/runs/{run_id}')
    validate_run(run, repo, workflow, revision)
    # Explicitly page: never silently select from a truncated result set.
    artifacts = []
    page = 1
    while True:
        batch = api(f'{base}/actions/runs/{run_id}/artifacts?per_page=100&page={page}')['artifacts']
        artifacts.extend(a for a in batch if a['name'] == ARTIFACT)
        if len(batch) < 100:
            break
        page += 1
    if artifact_id is not None:
        artifacts = [a for a in artifacts if a['id'] == artifact_id]
    require(len(artifacts) == 1, 'Expected exactly one tested artifact')
    artifact = artifacts[0]
    require(not artifact['expired'], 'Test evidence expired; validate a new main revision')
    require(artifact['size_in_bytes'] <= MAX_BYTES, 'Artifact too large')
    data = gh('api', f"{base}/actions/artifacts/{artifact['id']}/zip", binary=True)
    require(artifact.get('digest') == digest(data), 'Actions artifact digest mismatch')
    return artifact['id'], unpack(data)


def release_by_tag(repo, tag):
    # Fail on API/network/auth errors instead of treating them as a missing release.
    page = 1
    while True:
        batch = api(f'repos/{repo}/releases?per_page=100&page={page}')
        for release in batch:
            if release['tag_name'] == tag:
                return release
        if len(batch) < 100:
            return None
        page += 1


def release_files(repo, release):
    result = {}
    assets = []
    page = 1
    while True:
        batch = api(f"repos/{repo}/releases/{release['id']}/assets?per_page=100&page={page}")
        assets.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    for asset in assets:
        name = asset['name']
        require(name not in result and asset['size'] <= MAX_BYTES,
                'Duplicate or oversized release asset')
        result[name] = gh('api', '-H', 'Accept: application/octet-stream',
                          f"repos/{repo}/releases/assets/{asset['id']}", binary=True)
    return result


def tag_revision(repo, tag):
    obj = api(f'repos/{repo}/git/ref/tags/{tag}')['object']
    for _ in range(8):
        if obj['type'] == 'commit':
            return obj['sha']
        require(obj['type'] == 'tag', 'Tag does not reference a commit')
        obj = api(f"repos/{repo}/git/tags/{obj['sha']}")['object']
    raise ValueError('Tag nesting exceeds limit')


def publish(repo, tag, revision, files, prerelease):
    existing = release_by_tag(repo, tag)
    if existing:
        require(not existing['draft'] and existing.get('immutable')
                and existing['prerelease'] == prerelease,
                'Existing release is not a matching immutable publication; inspect any draft')
        require(tag_revision(repo, tag) == revision, 'Existing tag revision mismatch')
        require(release_files(repo, existing) == files, 'Existing release bytes differ')
        return
    with tempfile.TemporaryDirectory() as directory:
        paths = []
        for name, data in files.items():
            path = Path(directory) / name
            path.write_bytes(data)
            paths.append(str(path))
        # Upload into a draft, then freeze the complete asset set by publishing it.
        gh('release', 'create', tag, '--repo', repo, '--target', revision,
           '--draft', '--title', tag, '--notes',
           'Validated package snapshot. See release-manifest.json for source and test evidence.',
           *(['--prerelease'] if prerelease else []))
        gh('release', 'upload', tag, *paths, '--repo', repo)
        gh('release', 'edit', tag, '--repo', repo, '--draft=false', '--latest=false')
    release = release_by_tag(repo, tag)
    require(release and release.get('immutable'), 'Publication is not immutable')
    require(tag_revision(repo, tag) == revision, 'Published tag revision mismatch')
    require(release_files(repo, release) == files, 'Published release bytes mismatch')


def admission_evidence(repo, revision, tag, attempts=30, *, include_mode=False):
    """A configured compatibility policy must pass even if caller wiring is absent."""
    configured = False
    # Current main also applies: tagging older workflow code cannot escape a
    # subsequently installed policy. Never execute the inspected repository.
    for ref in (revision, 'main'):
        entries = api(f'repos/{repo}/contents/?' + urlencode({'ref': ref}))
        require(isinstance(entries, list) and len(entries) < 1000,
                'Cannot establish complete repository policy inventory')
        configured |= any(item['name'] == 'release-policy.json' for item in entries)
    if not configured:
        return (None, False) if include_mode else None
    query = urlencode(dict(branch=tag, event='push', head_sha=revision, per_page=100))
    for attempt in range(attempts):
        runs = api(f'repos/{repo}/actions/workflows/release-admission.yml/runs?{query}')['workflow_runs']
        # Use the newest matching run; an earlier green run cannot mask a failure.
        if runs:
            run = max(runs, key=lambda item: item['id'])
            require(run['repository']['full_name'] == repo and
                    run['head_repository']['full_name'] == repo and
                    run['head_sha'] == revision and run['head_branch'] == tag and
                    run['event'] == 'push' and
                    run['path'] == '.github/workflows/release-admission.yml',
                    'Release admission identity mismatch')
            if run['status'] == 'completed':
                require(run['conclusion'] == 'success', 'Release compatibility did not succeed')
                jobs = []
                page = 1
                while True:
                    batch = api(f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100&page={page}")['jobs']
                    jobs.extend(batch)
                    if len(batch) < 100:
                        break
                    page += 1
                compatibility = [job for job in jobs if job['name'].endswith('/ Release compatibility')
                                 and job['conclusion'] == 'success']
                initial = [job for job in jobs if job['name'].endswith('/ Initial release admission')
                           and job['conclusion'] == 'success']
                require(len(compatibility) + len(initial) == 1 and (include_mode or compatibility),
                        'Successful configuration alone is not release compatibility or initial admission')
                return (run['id'], bool(initial)) if include_mode else run['id']
        if attempt + 1 < attempts:
            time.sleep(5)
    raise ValueError('No completed compatibility evidence for this exact tag and commit')


def initial_publication(repo, revision, tag, files):
    """Bind tested bytes and atomically reserve the first stable source.

    The durable Git ref prevents two differently sourced tags from both passing
    an empty-release-list check. Retrying the same source is safe; the candidate
    version binds its sole allowed stable tag. No settings or approvals are added.
    """
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo)
            and re.fullmatch(r'[0-9a-f]{40}', revision), 'Invalid initial source identity')
    response = api(f'repos/{repo}/contents/releases/candidate/release.json?' + urlencode({'ref': revision}))
    require(response.get('encoding') == 'base64', 'Unsupported candidate encoding')
    bundle = json.loads(base64.b64decode(response['content'], validate=False))
    owner = repo.split('/')[1]
    require(bundle.get('schema_version') == 1 and set(bundle.get('components', {})) == {owner},
            'Initial candidate owner mismatch')
    component = bundle['components'][owner]
    require(tag == 'v' + component['version'], 'Initial candidate tag mismatch')
    artifact = component['artifact']
    require(artifact['kind'] == 'package' and 'sha256:' + artifact['sha256'] in
            {digest(data) for data in files.values()}, 'Initial candidate is not a tested package asset')
    for page in range(1, 101):
        releases = api(f'repos/{repo}/releases?per_page=100&page={page}')
        require(isinstance(releases, list) and len(releases) <= 100, 'Incomplete release inventory')
        require(all(isinstance(item, dict) and item.get('prerelease') is True for item in releases),
                'Stable release already exists; accepted-baseline admission is required')
        if len(releases) < 100:
            break
    else:
        raise ValueError('Release inventory exceeds initial-publication limit')
    ref = 'heads/release/initial-stable'
    try:
        gh('api', f'repos/{repo}/git/refs', '--method', 'POST',
           '-f', 'ref=refs/' + ref, '-f', 'sha=' + revision)
    except subprocess.CalledProcessError:
        # A concurrent winner or a prior attempt may own the claim. Any other
        # failure must still establish the exact reservation via a fresh read.
        pass
    claim = api(f'repos/{repo}/git/ref/{ref}')
    require(claim.get('ref') == 'refs/' + ref and claim.get('object', {}).get('type') == 'commit'
            and claim['object'].get('sha') == revision,
            'Another source owns the initial stable publication claim')


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    workflow = os.environ['VALIDATION_WORKFLOW']
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    event_name = os.environ['GITHUB_EVENT_NAME']
    if event_name == 'workflow_run':
        run = event['workflow_run']
        revision, run_id = run['head_sha'], run['id']
        validate_run(run, repo, workflow, revision)
        artifact_id, files = tested_files(repo, workflow, revision, run_id)
        tag = f'test-{revision}'
        manifest = dict(schema=1, repository=repo, channel='test', tag=tag,
                        revision=revision, workflow=workflow, run_id=run_id,
                        artifact_id=artifact_id,
                        assets={name: digest(data) for name, data in sorted(files.items())})
        prerelease = True
    else:
        require(event_name == 'push', 'Unsupported release event')
        ref = os.environ['GITHUB_REF']
        require(re.fullmatch(r'refs/tags/v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', ref),
                'Stable tags must be vMAJOR.MINOR.PATCH')
        tag = ref.removeprefix('refs/tags/')
        revision = tag_revision(repo, tag)
        admission_run_id, initial = admission_evidence(repo, revision, tag, include_mode=True)
        candidate = release_by_tag(repo, f'test-{revision}')
        require(candidate and candidate.get('immutable') and candidate['prerelease']
                and not candidate['draft'], 'No immutable test release for tag revision')
        require(tag_revision(repo, candidate['tag_name']) == revision, 'Test tag moved')
        assets = release_files(repo, candidate)
        manifest = json.loads(assets.pop(MANIFEST))
        require(set(manifest) == {'schema', 'repository', 'channel', 'tag', 'revision',
                                 'workflow', 'run_id', 'artifact_id', 'assets'}, 'Invalid manifest fields')
        require(manifest['schema'] == 1 and manifest['repository'] == repo
                and manifest['revision'] == revision and manifest['workflow'] == workflow
                and manifest['channel'] == 'test' and manifest['tag'] == candidate['tag_name'],
                'Test manifest identity mismatch')
        _, files = tested_files(repo, workflow, revision, manifest['run_id'], manifest['artifact_id'])
        require(files == assets, 'Release differs from successful Actions artifact')
        require(manifest['assets'] == {name: digest(data) for name, data in files.items()},
                'Test manifest asset digest mismatch')
        if initial:
            initial_publication(repo, revision, tag, files)
        manifest.update(channel='prod', tag=tag)
        if admission_run_id is not None:
            manifest['admission_run_id'] = admission_run_id
        prerelease = False
    files[MANIFEST] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    publish(repo, tag, revision, files, prerelease)


if __name__ == '__main__':
    main()
