# Orchestrator checkpoint (auto-maintained; read this first after /compact or resume)

Updated: 2026-09-15 13:40 IST — RESUMED; Phase 3 review loop in flight.

## Where we are
- Phase 1, 2 DONE. Phase 3: T-FEATURES and T-REPLAY merged into main.
- `main` = 5992600 (history rewritten: no AI trailers, author
  anmolagarwal2625+github@gmail.com = GitHub iAnmolAgarwal; force-pushed).
  CI on main is RED (platform ULP tie in exact-rank percentiles,
  tests/features golden `air_temp_slope_4h`, one rank off on Linux).
- 2026-09-15 13:35: all four branches rebased onto the rewritten main
  (`git rebase --onto main <old-base>` + amend: trailers stripped, author
  forced to +github). All worktrees clean; every fix-pass commit was already
  committed before the builders died. Reviews spawned in parallel:
  features-ci-code-1, model-code-1, web-shell-code-2, web-shell-ux-2 (reports
  land in the NEW session scratchpad
  `/private/tmp/claude-501/-Users-anmolagarwal-iotAnalyticsLab-epm/af9e2a51-3cb6-469f-b450-ace4807a1d0a/scratchpad/reviews/`).
- Worktrees still live under the OLD session scratchpad (`git worktree list`):
  - wt-features-ci / fix/features-ci (off main 702475a, 2 commits 8912960
    bdad617, clean, no trailers): BUILD DONE, code review 1 IN FLIGHT. Rank tie test tolerant
    to float64 noise (RANK_RTOL=1e-9 scaled by running max |value|), ai4i
    golden regenerated (28 ranks moved, 0 values), ULP-perturbation tests,
    benchmark-disabled guard. Proven on x86-64 Linux in docker (pre-fix main
    fails, branch passes 581). Next: code-reviewer, then merge FIRST.
  - wt-web-shell / feat/web-shell (20 commits on main, clean): fix pass 1
    COMMITTED (14 fix commits, no builder report). Code review 2 + UX review 2
    IN FLIGHT.
  - wt-features-settings / fix/features-settings (4 commits on main, clean,
    rebased): APPROVED (old scratchpad features-settings-code-1.md). Merge
    right after fix/features-ci.
  - wt-model / feat/model (6 commits daf0f43..9719642 on main, clean, no
    trailers): T-MODEL BUILD DONE, code review 1 IN FLIGHT. Report in
    scratchpad/reviews/model-build-report.md (key deviations: plant level in
    registry path, grouped_time split rule, warm-up NaN drop, libomp on mac).
    Next: code-reviewer (check deviations against §3.7/R5/R16), then merge
    after the Phase 3 branches.

## Resume procedure
1. `gh auth status`; `git status`; `git worktree list`; check each worktree
   for dirty files and partial commits before re-briefing any builder.
2. For a dead builder: spawn the same role with the original brief plus
   "continue from the existing worktree state; do not start over".
3. Before merging ANY branch: rewrite it
   (`git filter-repo --force --refs refs/heads/<branch> --mailmap <mailmap>
   --message-callback <strip Co-Authored-By/Claude-Session>`) or verify
   `git log main..<branch> --format='%ae %B'` has only the +github address and
   no trailers. Then `git merge --no-ff`, gate, push.
4. Merge order: fix/features-ci -> fix/features-settings -> feat/web-shell
   (after APPROVED x2) -> feat/model (Phase 4, review first).
5. Then Phase 4 per docs/plan/backend.md §5: T-SHAP, T-API, T-NODERED, seven
   T-WEB-* features (code + ux review each). Phase 5: T-WEB-E2E, T-PERF,
   T-DOCS, fresh-reader, final review + codex, tag v1.0.0.

## Invariants
- Every Agent call: named agent type + `model: "opus"`.
- NO commit trailers of any kind (user instruction 2026-09-14); repo git
  config carries the identity. Tell every builder in its brief.
- Builders work in worktrees; Fable never writes application code.
- Stop spawning on a 429/usage limit; resume after reset.
- `caffeinate -dims` should be running (`pgrep -lx caffeinate`).

## Follow-ups not yet scheduled
- ci.yml: `pnpm/action-setup@v4` has no version and no root packageManager
  (T-INFRA fix; web-shell fix pass adds packageManager in web/package.json).
- docker/*.Dockerfile comments still justify build-essential with tdigest.
- docs/plan/backend.md §3.6 still shows percentile_algorithm: tdigest.
- T-DOCS: compose creates missing bind-mount dirs root-owned; ADR for R21/R22.
- Security hardening (SHA-pin actions, pip-audit, secrets hook) in Phase 5.
