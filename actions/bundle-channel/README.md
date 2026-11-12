# Versioned test bundles

Declare `.github/test-channel.json` in the caller:

```json
{"schema": 1, "next": "0.24.0", "workflow": ".github/workflows/validate.yml"}
```

Pin this action to an exact reviewed commit. Invoke `mode: test` from a
`workflow_run: completed` publisher for the declared validation workflow, with
`contents: write` and `actions: read`. Serialize test publication and promotion in
one repository-wide concurrency group with `cancel-in-progress: false`.
Public repositories use hosted runners; private repositories use
`[self-hosted, linux, x64, debrunner]`. Never execute caller code in the publisher.

Only a successful same-repository main push qualifies. The publisher reads the
configuration at the tested commit and at current main; both must agree. It
checks the latest validation run for that commit, downloads its `tested-dist`
artifact, verifies GitHub's ZIP digest and creates `0.24.0-test.0`, then `.1`, etc.
Numbers are per repository and target version. Existing tags reserve numbers;
atomic ref creation rejects collisions. PR jobs never publish. Declare a new
`next` after stable promotion; new tests for an already stable target are refused.

Test bundles are GitHub prereleases. The manifest records source, workflow/run,
artifact ID and hashes of every asset. Embedded package versions and dependency
metadata remain unchanged. A bundle label is not a Python/npm package version or
an assertion of service API compatibility. Consumers must use the exact bundle's
artifacts and qualified dependency locks, not infer package versions from labels.
This action does not publish to package indexes, deploy services, select a gold
candidate or establish cross-component/runtime/provider acceptance.

Stable bundle promotion is confined to the coordinator/template repository,
which has no component `release-policy.json`. The publisher rejects promotion
when either the selected source or current main has a component package policy.
Component repositories may publish test bundles, but their stable package
namespace and accepted baseline remain owned by the existing package publisher.
The coordinator must explicitly assemble and qualify component artifacts before
it can promote them as a plane bundle.

For explicit promotion, invoke `mode: promote` only through `workflow_dispatch`
on main with the input `gold_test` set to an exact tag such as `0.24.0-test.7`.
The destination is the current declared `next`, here `0.24.0`, without a `v`
prefix. Promotion verifies the immutable test release, source tag, configuration,
original successful Actions artifact and every asset's bytes, then copies the
entire asset set unchanged. Even the test provenance manifest is preserved.
No rebuild, package-version rewrite or automatic stable tag trigger occurs.
Stable promotion remains an explicitly selected owner action; an agent must not
dispatch it without authorization for that exact candidate and destination.

Existing immutable-release settings are required, as for the stable package
publisher. No reviewer, branch protection, environment approval or settings
mutation is installed. A completed retry verifies the existing bytes without
replacing them. An interrupted draft/tag fails closed for inspection; automation
does not delete it, overwrite it or allocate a replacement. Original Actions
evidence must remain available; expired artifacts cannot be promoted (the caller
requests 90-day retention). Repository retention may be shorter.

This is separate from `release-channel`, whose `vMAJOR.MINOR.PATCH` package release
path retains its existing package compatibility/admission checks. Do not treat a
bundle as an accepted component package baseline. Repositories opt into this test
flow explicitly; installing the action does not enable it for existing callers.

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
