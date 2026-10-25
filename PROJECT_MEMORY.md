# Project memory

## Reviewed baseline (2026-10-25)

- Public Android Meta Wearables DAT SDK distribution and samples. Preserve the existing API guidance in [AGENTS.md](AGENTS.md); [README](README.md) covers SDK integration.
- Publication base: `origin/main` release 1.0.1 at `f4371bc`, used to create `master`. Original local `main` contains separate unpublished work; preserve and reconcile it independently.
- Select Gradle verification from the affected sample. Use MockDeviceKit for deterministic scenarios and retain physical acceptance separately.
- Current rollout is documentation-only; application tests have not been run.

## Handoff contract

Rollout verification: policy-coverage and local-link checks passed across all 13 workspace repositories; `git diff --check` passed. Application testing remains outside this documentation-only change.

After each item record task/owner, branch/worktree, base SHA, changed files, commit/PR, acceptance cases, exact verification commands/results/artifacts, pending external acceptance and next action. Store status in [project plan](PROJECT_PLAN.md); reconcile with Git and remote state on resume.
