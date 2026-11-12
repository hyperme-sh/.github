"""Publish immutable GitHub package snapshots without executing repository code."""
import hashlib
import base64
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile
import time
from urllib.parse import urlencode
from urllib.parse import quote
import zipfile

import service_channels

from stable_policy import component_release
from stable_policy.policy import json_document, same_json

ARTIFACT = 'tested-dist'
MANIFEST = 'release-manifest.json'
MAX_BYTES = 512 * 1024 * 1024
MAX_METADATA_BYTES = 4 * 1024 * 1024


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


def registry_files(repo, workflow, revision, run_id, attempt=None, expected=None):
    base = f'repos/{repo}/actions/runs/{run_id}'
    run = api(base if attempt is None else f'{base}/attempts/{attempt}')
    validate_run(run, repo, workflow, revision)
    attempt = run['run_attempt']
    jobs = api(f'{base}/attempts/{attempt}/jobs?per_page=100')
    require(len(jobs['jobs']) == jobs['total_count'], 'Incomplete validation job inventory')
    identities = [j['name'].removeprefix('Qualified OCI ') for j in jobs['jobs']
                  if j['name'].startswith('Qualified OCI ') and j['conclusion'] == 'success']
    require(len(identities) == 1 and re.fullmatch(r'sha256:[0-9a-f]{64}', identities[0]),
            'Successful validation must record exactly one OCI digest')
    digest_id = identities[0]
    require(expected is None or expected == digest_id, 'Original registry digest changed')
    ref = f'ghcr.io/{repo.lower()}/runtime@{digest_id}'
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, 'DOCKER_CONFIG': tmp}
        def docker(*args, **kwargs):
            return subprocess.run(['docker', *args], env=env, check=True, timeout=600, **kwargs)
        docker('login', 'ghcr.io', '--username', os.environ['GITHUB_ACTOR'], '--password-stdin',
               input=os.environ['GH_TOKEN'].encode(), stdout=subprocess.DEVNULL)
        docker('pull', ref, stdout=subprocess.DEVNULL)
        container = docker('create', '--network', 'none', ref, stdout=subprocess.PIPE).stdout.decode().strip()
        try:
            with tempfile.TemporaryFile() as stream:
                docker('cp', container+':/qualified/tested-dist.zip', '-', stdout=stream)
                require(stream.tell() <= MAX_BYTES + 10240, 'Registry package archive too large')
                stream.seek(0)
                with tarfile.open(fileobj=stream) as archive:
                    members = archive.getmembers()
                    require(len(members) == 1 and members[0].isreg() and members[0].name == 'tested-dist.zip'
                            and members[0].size <= MAX_BYTES, 'Unexpected registry package payload')
                    files = unpack(archive.extractfile(members[0]).read())
        finally:
            docker('rm', '-v', container, stdout=subprocess.DEVNULL)
    return digest_id, attempt, files


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


def policy_configured(repo, revision):
    configured = False
    # Current main also applies: tagging older workflow code cannot escape a
    # subsequently installed policy. Never execute the inspected repository.
    for ref in (revision, 'main'):
        entries = api(f'repos/{repo}/contents/?' + urlencode({'ref': ref}))
        require(isinstance(entries, list) and len(entries) < 1000,
                'Cannot establish complete repository policy inventory')
        configured |= any(item['name'] == 'release-policy.json' for item in entries)
    return configured


def check_admission_record(repo, revision, tag, run, *, include_mode=False):
    require(run['repository']['full_name'] == repo and
            run['head_repository']['full_name'] == repo and
            run['head_sha'] == revision and run['head_branch'] == tag and
            run['event'] == 'push' and run['path'] == '.github/workflows/release-admission.yml',
            'Release admission identity mismatch')
    require(run['status'] == 'completed' and run['conclusion'] == 'success', 'Release compatibility did not succeed')
    require(type(run['id']) is int and type(run['run_attempt']) is int
            and run['id'] > 0 and run['run_attempt'] > 0, 'Invalid admission attempt')
    jobs = []
    page = 1
    while True:
        batch = api(f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100&page={page}")['jobs']
        jobs.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    compatibility = [job for job in jobs if job['name'].endswith('/ Release compatibility') and job['conclusion'] == 'success']
    initial = [job for job in jobs if job['name'].endswith('/ Initial release admission') and job['conclusion'] == 'success']
    require(len(compatibility) + len(initial) == 1 and (include_mode or compatibility),
            'Successful configuration alone is not release compatibility or initial admission')
    result = (run['id'], run['run_attempt'])
    return (*result, bool(initial)) if include_mode else result


def admission_evidence(repo, revision, tag, attempts=30, *, include_mode=False):
    """A configured compatibility policy must pass even if caller wiring is absent."""
    if not policy_configured(repo, revision):
        return None
    query = urlencode(dict(branch=tag, event='push', head_sha=revision, per_page=100))
    for attempt in range(attempts):
        runs = api(f'repos/{repo}/actions/workflows/release-admission.yml/runs?{query}')['workflow_runs']
        # Use the newest matching run; an earlier green run cannot mask a failure.
        if runs:
            run = max(runs, key=lambda item: item['id'])
            if run['status'] == 'completed':
                return check_admission_record(repo, revision, tag, run, include_mode=include_mode)
        if attempt + 1 < attempts:
            time.sleep(5)
    raise ValueError('No completed compatibility evidence for this exact tag and commit')


def source_file(repo, revision, relative):
    path = PurePosixPath(relative)
    require(isinstance(relative, str) and len(relative) <= 512 and not path.is_absolute()
            and '..' not in path.parts and '.git' not in path.parts, 'Unsafe release metadata path')
    result = api(f'repos/{repo}/contents/{quote(relative, safe="/")}?' + urlencode({'ref': revision}))
    require(result.get('type') == 'file' and result.get('encoding') == 'base64', 'Release metadata must be a regular file')
    require(type(result.get('size')) is int and 0 <= result['size'] <= MAX_METADATA_BYTES, 'Release metadata exceeds limit')
    raw = base64.b64decode(''.join(result['content'].splitlines()), validate=True)
    require(len(raw) == result['size'], 'Release metadata size mismatch')
    return raw


def latest_stable(repo, before_version=None):
    releases = []
    boundary = tuple(map(int, before_version.split('.'))) if before_version else None
    for page in range(1, 101):
        batch = api(f'repos/{repo}/releases?per_page=100&page={page}')
        require(isinstance(batch, list) and len(batch) <= 100, 'Invalid release inventory')
        for release in batch:
            require(type(release.get('draft')) is bool and type(release.get('prerelease')) is bool,
                    'Incomplete release channel evidence')
            if release['draft'] or release['prerelease']:
                continue
            tag = release.get('tag_name', '')
            require(re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', tag),
                    'Unrecognized stable release tag')
            value = tuple(map(int, tag[1:].split('.')))
            if boundary is None or value < boundary:
                releases.append((value, release))
        if len(batch) < 100:
            require(releases, 'No actual stable release; test snapshots are not a bootstrap baseline')
            return max(releases, key=lambda item: item[0])[1]
    raise ValueError('Stable release inventory exceeds limit')


def independent_admission(repo, revision, tag, files, *, baseline_revision=None, before_version=None, initial=False):
    """Re-run pinned policy on data, independently of caller job names/flags."""
    main_revision = baseline_revision or api(f'repos/{repo}/commits/main').get('sha')
    require(isinstance(main_revision, str) and re.fullmatch('[0-9a-f]{40}', main_revision), 'Immutable main policy revision required')
    with tempfile.TemporaryDirectory(prefix='stable-admission-') as temporary:
        root = Path(temporary)
        baseline, candidate = root/'baseline', root/'candidate'
        remaining = MAX_METADATA_BYTES
        def fetch(destination, ref, relative):
            nonlocal remaining
            raw = source_file(repo, ref, relative)
            remaining -= len(raw)
            require(remaining >= 0, 'Release metadata inventory exceeds limit')
            target = destination/relative
            require(target.resolve().is_relative_to(destination.resolve()), 'Release metadata escapes snapshot')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            return target
        main_policy = json_document(fetch(baseline, main_revision, 'release-policy.json'))
        policy = json_document(fetch(candidate, revision, 'release-policy.json'))
        for key in ('schema_version', 'repository', 'component', 'line', 'version_files'):
            require(same_json(policy.get(key), main_policy.get(key)), 'Tagged policy differs from current owning policy: ' + key)
        versions = policy.get('version_files')
        require(isinstance(versions, list) and 0 < len(versions) <= 32 and len(versions) == len(set(versions)), 'Invalid owning version inventory')
        for relative in versions:
            fetch(candidate, revision, relative)
        def bundle(destination, ref, folder):
            document = json_document(fetch(destination, ref, folder+'/release.json'))
            require(document.get('stable_release') is not False
                    and document.get('purpose') in {None, 'stable-release'},
                    'Test qualification cannot be used as stable release metadata')
            components = document.get('components')
            require(isinstance(components, dict) and len(components) == 1, 'Expected one owning component')
            for component in components.values():
                contract = component.get('contract')
                require(isinstance(contract, str), 'Release contract path required')
                relative = PurePosixPath(contract)
                require(not relative.is_absolute() and '..' not in relative.parts
                        and '.git' not in relative.parts and len(contract) <= 512,
                        'Unsafe contract metadata path')
                fetch(destination, ref, folder+'/'+contract)
            return document
        declared = bundle(candidate, revision, 'releases/candidate')
        if initial:
            accepted_version = component_release.admit_initial(candidate, repo, policy['line'], tag,
                fetch=lambda path: initial_history(path, before_version))
        else:
            accepted = bundle(baseline, main_revision, 'releases/accepted')
            provenance = json_document(fetch(baseline, main_revision, 'releases/accepted/provenance.json'))
            require(provenance.get('release_id') == latest_stable(repo, before_version=before_version).get('id'),
                    'Current main does not record the latest actual stable release')
            stable_source = provenance.get('revision')
            require(isinstance(stable_source, str) and re.fullmatch('[0-9a-f]{40}', stable_source),
                    'Stable source revision must be immutable')
            published = bundle(root/'published', stable_source, 'releases/candidate')
            require(same_json(accepted, published), 'Accepted declaration differs from the immutable stable source')
            for component in accepted['components'].values():
                relative = component['contract']
                require((baseline/'releases/accepted'/relative).read_bytes()
                        == (root/'published/releases/candidate'/relative).read_bytes(),
                        'Accepted API contract differs from the immutable stable source')
            accepted_version = component_release.admit(candidate, baseline, repo, policy['line'], tag)
        artifact = declared['components'][policy['component']]['artifact']
        if artifact['kind'] == 'package':
            require('sha256:' + artifact['sha256'] in {digest(data) for data in files.values()}, 'Candidate does not identify an actual tested artifact')
        else:
            raw = files.get('container-provenance.json')
            require(raw is not None, 'Tested container provenance is required')
            proof = json.loads(raw)
            require(same_json(proof, {'schema_version': 1, 'repository': repo, 'revision': revision,
                             'version': accepted_version, 'artifact': artifact}), 'Tested container provenance differs from candidate')
        return main_revision


def initial_history(path, before_version=None):
    batch = api(path)
    require(isinstance(batch, list) and len(batch) <= 100, 'Invalid release inventory')
    if before_version is None:
        return batch
    # Recovery of an already immutable initial release checks only earlier
    # versions; later normal releases do not invalidate its original evidence.
    result = []
    boundary = tuple(map(int, before_version.split('.')))
    for item in batch:
        require(isinstance(item, dict) and type(item.get('prerelease')) is bool, 'Incomplete release channel evidence')
        if item['prerelease']:
            result.append(item)
            continue
        tag = item.get('tag_name', '')
        require(re.fullmatch(r'v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', tag), 'Unrecognized stable release tag')
        # Preserve page length so filtering cannot terminate pagination early.
        result.append(item if tuple(map(int, tag[1:].split('.'))) < boundary else {'prerelease': True})
    return result


def initial_source_claim(repo, revision, *, existing=False):
    """Atomically reserve one source; retry verification never mutates the ref."""
    require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo)
            and re.fullmatch(r'[0-9a-f]{40}', revision), 'Invalid initial source identity')
    ref = 'heads/release/initial-stable'
    if not existing:
        try:
            gh('api', f'repos/{repo}/git/refs', '--method', 'POST',
               '-f', 'ref=refs/' + ref, '-f', 'sha=' + revision)
        except subprocess.CalledProcessError:
            pass  # A fresh read must still prove this exact source owns the claim.
    claim = api(f'repos/{repo}/git/ref/{ref}')
    require(claim.get('ref') == 'refs/' + ref and claim.get('object', {}).get('type') == 'commit'
            and claim['object'].get('sha') == revision, 'Another source owns the initial stable publication claim')


def qualified_run(repo, workflow, revision):
    path = PurePosixPath(workflow)
    require(path.parent.as_posix() == '.github/workflows' and path.suffix in {'.yml', '.yaml'},
            'Repository-relative validation workflow path required')
    identifier = quote(path.name, safe='')
    runs = []
    for page in range(1, 101):
        query = urlencode(dict(branch='main', event='push', head_sha=revision, per_page=100, page=page))
        batch = api(f'repos/{repo}/actions/workflows/{identifier}/runs?{query}')['workflow_runs']
        require(isinstance(batch, list) and len(batch) <= 100, 'Invalid validation run inventory')
        runs.extend(run for run in batch if run.get('head_sha') == revision)
        if len(batch) < 100:
            break
    else:
        raise ValueError('Validation run inventory exceeds limit')
    require(runs, 'No main validation run for this tag revision')
    run = max(runs, key=lambda item: item['id'])
    validate_run(run, repo, workflow, revision)
    return run['id']


def verify_existing_publication(repo, tag, revision, workflow, release):
    """Recover a completed immutable publication using its original evidence."""
    require(release.get('tag_name') == tag and release.get('immutable') is True
            and release.get('prerelease') is False and release.get('draft') is False,
            'Existing publication is not an immutable stable release')
    files = release_files(repo, release)
    raw = files.pop(MANIFEST, None)
    require(isinstance(raw, bytes) and len(raw) <= MAX_METADATA_BYTES, 'Stable publication manifest required')
    manifest = json.loads(raw)
    require(isinstance(manifest, dict) and raw == (json.dumps(manifest, sort_keys=True, indent=2)+'\n').encode(),
            'Stable publication manifest is not canonical')
    required = {'schema', 'repository', 'channel', 'tag', 'revision', 'workflow', 'run_id', 'artifact_id', 'assets'}
    registry = manifest.get('schema') == 2
    if registry:
        required.remove('artifact_id')
        required.update(('image_digest','validation_attempt'))
    configured = policy_configured(repo, revision)
    initial = manifest.get('initial_release') is True
    if initial:
        require(configured, 'Initial evidence requires an owning policy')
        required.add('initial_release')
    if configured:
        required |= {'admission_run_id', 'admission_run_attempt', 'policy_baseline_revision'}
    require(set(manifest) == required and type(manifest.get('schema')) is int and manifest['schema'] in (1, 2)
            and manifest['repository'] == repo and manifest['channel'] == 'prod'
            and manifest['tag'] == tag and manifest['revision'] == revision and manifest['workflow'] == workflow,
            'Stable publication identity mismatch')
    for key in ('run_id', 'validation_attempt' if registry else 'artifact_id'):
        require(type(manifest[key]) is int and manifest[key] > 0, 'Invalid original artifact identity')
    require(manifest['assets'] == {name: digest(data) for name, data in files.items()}, 'Stable publication asset digest mismatch')
    if configured:
        run_id, attempt = manifest['admission_run_id'], manifest['admission_run_attempt']
        require(type(run_id) is int and run_id > 0 and type(attempt) is int and attempt > 0, 'Invalid original admission identity')
        original = api(f'repos/{repo}/actions/runs/{run_id}/attempts/{attempt}')
        require(original.get('id') == run_id and original.get('run_attempt') == attempt, 'Original admission identity differs')
        if initial:
            require(check_admission_record(repo, revision, tag, original, include_mode=True) == (run_id, attempt, True), 'Original initial admission differs')
            initial_source_claim(repo, revision, existing=True)
        else:
            require(check_admission_record(repo, revision, tag, original) == (run_id, attempt), 'Original admission attempt differs')
    if registry:
        _, _, tested = registry_files(repo, workflow, revision, manifest['run_id'], manifest['validation_attempt'], manifest['image_digest'])
    else:
        _, tested = tested_files(repo, workflow, revision, manifest['run_id'], manifest['artifact_id'])
    require(tested == files, 'Existing stable bytes differ from original tested artifact')
    validate_service_channels(files)
    if configured:
        baseline = manifest['policy_baseline_revision']
        require(isinstance(baseline, str) and re.fullmatch('[0-9a-f]{40}', baseline), 'Invalid original baseline revision')
        options = {'initial': True} if initial else {}
        independent_admission(repo, revision, tag, files, baseline_revision=baseline,
                              before_version=tag.removeprefix('v'), **options)
    print('Existing immutable stable publication verified; original provenance preserved')


def validate_service_channels(files):
    return service_channels.validate(files, os.environ.get('SERVICE_REPOSITORIES', '{}'))


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    workflow = os.environ['VALIDATION_WORKFLOW']
    event_name = os.environ['GITHUB_EVENT_NAME']
    require(event_name == 'push', 'Automatic test release publication is disabled; qualify Actions artifacts instead')
    ref = os.environ['GITHUB_REF']
    require(re.fullmatch(r'refs/tags/v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', ref),
            'Stable tags must be vMAJOR.MINOR.PATCH')
    tag = ref.removeprefix('refs/tags/')
    revision = tag_revision(repo, tag)
    existing = release_by_tag(repo, tag)
    if existing is not None:
        verify_existing_publication(repo, tag, revision, workflow, existing)
        return
    admission_run_id = admission_evidence(repo, revision, tag, include_mode=True)
    run_id = qualified_run(repo, workflow, revision)
    if os.environ.get('PACKAGE_SOURCE') == 'ghcr':
        image_digest, attempt, files = registry_files(repo, workflow, revision, run_id)
        provenance = dict(schema=2, image_digest=image_digest, validation_attempt=attempt)
    else:
        artifact_id, files = tested_files(repo, workflow, revision, run_id)
        provenance = dict(schema=1, artifact_id=artifact_id)
    validate_service_channels(files)
    manifest = dict(**provenance, repository=repo, channel='prod', tag=tag, revision=revision,
                    workflow=workflow, run_id=run_id,
                    assets={name: digest(data) for name, data in sorted(files.items())})
    if admission_run_id is not None:
        run, attempt, initial = admission_run_id
        options = {'initial': True} if initial else {}
        manifest['policy_baseline_revision'] = independent_admission(repo, revision, tag, files, **options)
        if initial:
            initial_source_claim(repo, revision)
            manifest['initial_release'] = True
        manifest['admission_run_id'], manifest['admission_run_attempt'] = run, attempt
    files[MANIFEST] = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    publish(repo, tag, revision, files, False)


if __name__ == '__main__':
    main()
