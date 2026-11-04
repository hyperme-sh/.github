# Package release channels

Use this action at an exact reviewed commit. It requires only the caller's
`GITHUB_TOKEN` (`contents: write`, `actions: read`), Python 3 and GitHub CLI on an
isolated Ubuntu runner. It never checks out or executes the caller's source or
packages. Keep validation jobs read-only and scoped dependency credentials there.

A successful **push to main** validation workflow uploads a single flat
`tested-dist` Actions artifact, after all source, wheel, sdist and installed tests
pass. Preserve the actual tested artifacts; do not rebuild for publication.
Configure upload-artifact with `if-no-files-found: error` and 90-day retention.
A separate `workflow_run: completed` publisher invokes this action with the
validation workflow's exact repository-relative path. It checks the run identity,
conclusion and original artifact digest before publishing `test-<commit>` as an
immutable prerelease. Workflow-dispatch and PR checks are not release candidates.

A `push: tags: ['v*']` publisher invokes the same action. Only `vMAJOR.MINOR.PATCH`
is accepted. The tag must point to a commit with an immutable test release. The
publisher downloads that candidate AND its original successful Actions artifact,
checks exact byte equality, and publishes the unchanged package files with a
production manifest. It does not run a package manager or rebuild anything.
GitHub release tags identify snapshots; they do not rewrite package metadata or
publish to PyPI/npm. A service contract wheel is still a contract wheel, not a
qualified OCI runtime. Deployment adapters must understand the artifact type.

Enable **immutable releases** in the caller repository before the first run.
Private repositories and their assets remain private. No public attestation,
new App, credential, or reviewer gate is required. Immutable publication uses a
draft followed by asset upload and final publication. An interrupted draft is
left unpublished for inspection; remove that draft and retry after diagnosis.
Completed identical publications are idempotent; differing bytes are rejected.
A rerun that changes a previously published test snapshot is deliberately rejected.

## Evidence lifetime

Promote within the Actions artifact retention period (normally 90 days; repository
or organization policy can shorten it). Expired or deleted evidence fails closed;
validate a new main revision to obtain a new candidate. Immutable release assets
alone are **not** proof of successful testing, even if their manifest names a green
run. Production release assets remain retained after promotion. Consumers must
retain their accepted source/digest receipt and never silently accept a changed
version. This action does not itself deploy or establish service health.

## Consumer workflow

Use one publisher workflow with triggers for the validation workflow's completion
and stable tag pushes, contents-write/actions-read permissions, and a repository
release concurrency group keyed by source revision/tag, with cancellation disabled
(so separate main merges do not evict one another from the pending queue). Gate workflow_run publication
on successful main push events. The action repeats these checks against the API.
Do not grant write tokens to validation jobs or execute downloaded package code in
the publisher. Repositories with selected-action policies must allow the exact
upload-artifact and release action SHAs before enabling these workflows.
