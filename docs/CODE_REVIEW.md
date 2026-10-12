# Code Review Assistant

CodeRabbit is the selected review assistant, matching the `coderabbitai[bot]`
integration observed in `Kozphy/ci-failure-orchestrator` PR #11. That project also
has Qodo comments; its latest inspected comment reports an expired trial. This
packet configures CodeRabbit only and does not purchase or change a provider plan.

## Repository configuration

`.coderabbit.yaml` configures automatic reviews of ready pull requests and
incremental reviews on new commits. Draft PRs are excluded. Review instructions
focus on tenant isolation, approval scope, queue recovery, budgets, evidence
truthfulness, migrations, and workflow permissions. Bot auto-approval and code
editing features are disabled. No merge workflow is added.

Knowledge-base scopes stay local to this repository, automatic repository linking
is disabled, and external web/Jira/Linear/MCP context is disabled. Review path
filters exclude local upstream checkouts and runtime artifacts; these filters do
not replace Git ignores, secret redaction, or GitHub App permissions.

The pull request template records objective, changed files, architecture,
migration/security impact, actual validation evidence, limitations, acceptance,
and rollback. CodeRabbit findings are supplementary; required CI and human review
remain necessary. This config alone does not install the GitHub App, enforce
branch protection, prove a live review, or prevent someone with repository write
permission from merging manually.

## Verified integration and plan limitations

On 2026-10-12, [PR #1](https://github.com/Kozphy/ai-company-os/pull/1) received a
`coderabbitai[bot]` summary and walkthrough. The bot explicitly reported that it
used `Kozphy/ai-company-os/.coderabbit.yaml` with the CHILL profile. Its commit
status succeeded for commit `50856a0`, and both Python 3.11 and 3.12 CI jobs passed
on the [pull request run](https://github.com/Kozphy/ai-company-os/actions/runs/38220738446).
Existing GitHub App access is therefore demonstrated; no additional installation
step was needed for this PR.

The bot reported a Free plan providing summaries and walkthroughs, and said a
subscription upgrade is required for comprehensive line-by-line review. No inline
review or submitted GitHub review was observed. A successful CodeRabbit status
therefore demonstrates summary processing, not a complete bug/security review or
approval. Qodo also posted its expired-trial/billing-blocked notice. No payment,
credit purchase, or subscription upgrade was performed.

## Owner setup if reviews stop or access changes

1. Open [GitHub App installations](https://github.com/settings/installations).
2. Configure the existing CodeRabbit installation and add only
   `Kozphy/ai-company-os` to its selected repositories. If CodeRabbit is not
   installed, use its [GitHub App page](https://github.com/apps/coderabbitai).
3. Verify that this repository is enabled in the
   [CodeRabbit repository dashboard](https://app.coderabbit.ai/).
4. Confirm available review entitlement without purchasing credits, upgrading a
   subscription, or accepting new charges unless separately authorized.
5. Review and manually merge the configuration PR when approved. Open a small
   subsequent ready PR and verify the behavior available under the current plan. If
   necessary, comment `@coderabbitai review` on that PR.
6. Verify configuration with `@coderabbitai configuration`; do not count a skipped
   review or a billing notification as a successful code review.

The current GitHub CLI account can push code and create PRs, but GitHub rejected
installation enumeration with HTTP 403 because its OAuth token is not a GitHub
App user token. Installation access could not be enumerated through that
interface, but the subsequent PR response demonstrated existing CodeRabbit access.
Full line-by-line review remains unverified and is unavailable under the plan
reported by the bot.

## Validation and rollback

The YAML was parsed and validated against CodeRabbit's published configuration
JSON schema on 2026-10-12. No application code or dependency change is required.
The configuration reference is at
https://docs.coderabbit.ai/reference/configuration and installation guidance at
https://docs.coderabbit.ai/getting-started/quickstart.

Rollback by reverting `.coderabbit.yaml` and the template/documentation changes.
Removing the YAML restores provider defaults and does not disable the app. To
stop CodeRabbit access/reviews entirely, remove this repository from the GitHub
App installation and disable it in the provider dashboard.
