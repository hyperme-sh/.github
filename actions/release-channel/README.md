# Stable package publication

Use this action at an exact reviewed commit on an isolated Linux runner (including Debian 13) with
GitHub CLI and the caller's repository-scoped `GITHUB_TOKEN`
(`contents: write`, `actions: read`). Validation jobs retain read-only permissions
and any private dependency credentials. The publisher never checks out or
executes the caller's source, packages or metadata scripts.
The action provisions managed Python 3.12 through pinned uv before importing its
bundled policy. It runs outside the caller checkout, with project and uv config
discovery disabled; caller dependencies and scripts are never installed. This
supports Debian debrunners without relying on setup-python Ubuntu binaries or
the system Python version.

Main validation retains its exact tested files in one flat `tested-dist` Actions
artifact after the owning source, wheel, sdist and consumer checks. Main merges,
PRs and workflow completion events do not create GitHub releases or tags. Existing
historical `test-<commit>` snapshots remain qualification evidence, and do not
reserve their embedded stable package version.

An explicit `push: tags: ['v*']` publisher accepts only `vMAJOR.MINOR.PATCH`. It
resolves the tag source, selects the newest main-push validation attempt for that
exact source and verifies its successful identity, artifact digest and bytes.
It publishes those unchanged files with a stable provenance manifest; it neither
rebuilds them nor publishes to PyPI/npm. Expired/missing Actions artifacts fail
closed. Repository/organization retention may shorten the requested 90 days.

For a component with release policy, the exact tag's automated compatibility run
must succeed. The publisher also independently re-runs its pinned, bundled policy
on data read from GitHub: the current main's stable accepted record and policy,
and the tagged candidate's metadata, version sources and contracts. Candidate
version-source redirection is refused. The baseline must be an actual immutable,
non-draft/non-prerelease stable release with a matching tag source and published
asset digests. Package candidates must identify actual tested bytes; container
candidates require matching tested image provenance. Successful-looking caller
jobs cannot replace these checks. Bundled policy is compared in CI with its exact
reviewed upstream source.

A missing accepted stable baseline remains closed. First stable bootstrap and
coordinated release readiness are separate explicit release work; a test snapshot
is never installed as a substitute. No human reviewer, environment approval or
branch protection is required by this action.

Immutable release settings must already be configured. Publication uses a draft,
asset upload and final publication, then verifies the result's immutability, tag
source and bytes. Existing identical results are preserved; replacement bytes are
refused. Interrupted drafts remain unpublished for diagnosis. This action does
not deploy services, qualify provider behavior or establish runtime health.

Retries of a completed immutable release verify its original validation artifact,
exact admission run attempt and recorded baseline snapshot. They recheck the
preceding stable version for that release and preserve the original manifest,
without publishing again or requiring main's accepted pointer to stay behind.
Missing or expired original evidence still fails verification closed.

### Initial stable package publication

A successful exact-tag `Initial release admission` job is distinct from backward
compatibility. The publisher independently reruns the pinned initial policy on
bounded metadata fetched from the owning source, binds its package digest to the
validated Actions artifact, and checks every page of live release history.
Existing stable releases or unknown history block initial publication.

Before publication it atomically claims `refs/heads/release/initial-stable` at the
source revision. Competing revisions cannot both become the first stable release;
the candidate version binds the permitted tag. This ordinary Git ref is never
force-updated and adds no branch protection, reviewer or approval setting.

The immutable publication records its initial mode and original main-policy
revision. Retry verification rechecks the original admission attempt, artifact,
policy, source claim and absence of earlier stable versions without mutating the
claim or published evidence. Failed unpublished attempts may need repair before
changing source; never clear a claim after stable publication. Subsequent releases
require genuine accepted stable provenance and ordinary compatibility admission.
Automatic test releases remain disabled. Initial mode supports package assets;
OCI and runtime/provider deployment qualification remain separate.

For explicitly opted-in `next-test.N` bundle publication and byte-preserving
bundle promotion, see [bundle-channel](../bundle-channel/README.md). That separate
action preserves embedded package versions and does not weaken this package
publisher's admission checks.

## Service channels

Optional `service-repositories` is a JSON map from service names to approved
registry/repository paths, for example
`{"api":"ghcr.io/hyperme-sh/api/runtime"}`. An opted-in caller includes a flat
`service-channels.json` asset in its qualified artifact:

```json
{"schema":1,"services":{"api":"ghcr.io/hyperme-sh/api/runtime:test"}}
```

Both publishers and completed retries validate the entire service set before
publication. References require an explicit tag in the configured repository;
credentials, URLs, whitespace, digests and tag/digest combinations are refused.
The tag is preserved without registry resolution. Independent peers may carry
different patch versions. These fields configure service updates, not package
identity or permission to promote production.

The optional asset is hashed and compared with the original qualified bytes just
like every other downloadable asset. Registry-backed package extraction retains
its exact qualified OCI digest. Existing callers without service metadata remain
compatible. Configure this input in the trusted publishing workflow, never from
an untrusted PR input.

The shared parser and `service-reference-vectors.json` in `actions/release-channel`
are the contract for Spanopticon #70. Infra #922 owns the scheduled channel
resolution and independently updated peer scenarios; this parser does not claim
those runtime checks. No registry is contacted by the unit/contract suite.

### First-build preparation

`python prepare.py --candidate PATH/release.json --provenance PATH/preparation.json
--source-root CHECKOUT` uses Spanopticon's vendored preparation contract. Install
`packaging==25.0` for this optional preparation command. Existing publisher
callers and production admission are unchanged. The output cannot authorize
publication, claim a stable baseline, or replace the owner's fresh build and
consumer qualification. Supply `--baseline-root` and `--repository` for a prior
stable comparison; a source checkout containing an accepted record cannot omit
that comparison. Test-only records fail stable verification.

`stable_policy/preparation-vectors.json` is copied byte-for-byte from Spanopticon.
The source manifest and verifier bind all preparation modules and vectors to the
reviewed source revision. CI checks the copy against that source and exercises
the same accepted/refused cases with a mocked registry. The scheduled-only
`qualify_preparation.py` additionally compares the bundled path against current
Spanopticon source. Infra #922 owns the combined registration; this addresses #19
and depends on Spanopticon #71 / PR #73. No artifact is published by either path.
