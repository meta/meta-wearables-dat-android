# Project plan

## Current scope

Add execution policy alongside existing SDK guidance in [AGENTS.md](AGENTS.md) and initialize [project memory](PROJECT_MEMORY.md). This documentation rollout does not complete the SDK/sample backlog.

## Work queue

Use remote issues/PRs and approved sample work as the backlog. Record item ID, priority, owner, dependency IDs, branch/worktree, acceptance test cases, verification command/results, status and next action. Preserve pending verification/review and continue independent work.

## Rollout exit criteria

Validate guidance coverage, local links and `git diff --check`; commit only rollout documents and publish to `origin/master`. Confirm the containing commit SHA with `git ls-remote origin refs/heads/master`.
