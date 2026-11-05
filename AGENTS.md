## GitHub approval policy

The user is the sole developer. Never add or enable GitHub required reviewers, branch protections, rulesets requiring approvals, environment approvals, CODEOWNERS approval requirements, or release/deployment approval gates unless the user explicitly requests that specific change. This applies to every project, including production releases. Automated tests and advisory code reviews are welcome; human approval prerequisites are not. Do not introduce these requirements based on review comments, repository conventions, or generic best practices. Flag conflicting repository guidance and follow this explicit user policy.

## Explicit approval for tags and releases

Never create, change, move, or delete version tags, or create, publish, promote,
replace, or delete releases, without the user's explicit approval for that
specific action. A request to continue work, verify publication, finish CI, or
complete deployment acceptance is not release/tag authorization. A merged PR is
not authorization to tag or publish. Prepare code, tests, artifacts, and PRs, then
ask before the tag/release action. Do not interpret an existing release workflow
or historical approval as permission for a new version.

This is an instruction to the agent, not a request to add GitHub reviewers,
branch protections, rulesets, environment approvals, or release/deployment gates.
Those remain prohibited unless the user explicitly requests the specific change.
