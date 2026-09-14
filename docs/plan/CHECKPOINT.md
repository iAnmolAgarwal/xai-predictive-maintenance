# Orchestrator checkpoint (auto-maintained; read this first after /compact)

Updated: 2026-09-14 22:50 IST

## Where we are
- Phase 1 (plan) DONE. Phase 2 (infra, data, contracts) DONE and merged into main.
- `main` is green (ruff, mypy --strict, 325 tests, contracts-check) and pushed
  at 352e88b.
- Phase 3 in progress, one worktree each under the session scratchpad
  (`git worktree list` shows them): feat/features (T-FEATURES),
  feat/replay (T-REPLAY), feat/web-shell (T-WEB-SHELL).

## Loop for every branch (unchanged)
builder -> code-reviewer (+ security-reviewer for api/infra, + ux-reviewer for
web-*) -> fix pass -> re-review until APPROVED -> `git merge --no-ff` into main
-> push -> remove worktree + delete branch -> check `gh run list`.
Reviews and builder reports live in scratchpad/reviews/*.md.

## After Phase 3 merges
Phase 4 per docs/plan/backend.md §5: T-MODEL (needs features), then T-SHAP,
then T-API (needs shap + replay), T-NODERED (needs api live), and the seven
T-WEB-* feature tasks (need web-shell + `make contracts`). Phase 5:
T-WEB-E2E -> T-PERF -> T-DOCS -> final review (+ codex cross-review) -> tag v1.0.0.

## Invariants
- Every Agent call: named agent type + `model: "opus"`.
- Builders work in worktrees off main, never in the primary checkout.
- Fable never writes application code; plan docs and this file are fine.
- Stop spawning on a 429 session limit; resume after the reset.
- `caffeinate -dims` runs in the background (pid in `pgrep -lx caffeinate`).

## Known follow-ups not yet scheduled
- Data reviewer non-blocking 3: note in xpm.data that band/horizon/Welch
  constants reconcile against settings (T-FEATURES brief asks for the test).
- Security reviewer optional items (SHA-pin actions, pip-audit in CI,
  secrets hook) — revisit in Phase 5 hardening.
- T-DOCS must mention that compose creates missing bind-mount dirs root-owned.

## Handoffs for T-API (from T-FEATURES / T-REPLAY reviews, 2026-09-14)
- Catch `ValueError` per row from `OnlineFeatureEngine.update` (null/missing
  channel) so one bad retained message cannot take the consumer down.
- Call `OnlineFeatureEngine.reset()` on every new `run_id` (loop/restart).
- `seq` is the 0-based tick index shared by all machines in a tick; mirror it
  on RiskMessage/WS frames. `loop_index` counts new runs, not dataset loops.
- Follow-up branch `fix/features-settings` (R22): default
  `features.percentile_algorithm: exact` as a Literal, drop `tdigest` dep.
