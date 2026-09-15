# Orchestrator checkpoint (auto-maintained; read this first after /compact or resume)

Updated: 2026-09-15 20:05 IST — PAUSED by the user (session limit nearly
reached). All agents stopped cleanly; every worktree's state is below.

## Where we are
- Phases 1–3 DONE. Merged into main (CI GREEN at 7f94834): T-INFRA,
  T-CONTRACTS, T-DATA, T-FEATURES, T-REPLAY, T-WEB-SHELL, fix/infra-ci,
  T-MODEL, T-SHAP (+fix/explain-ci), T-WEB-MOCKS (R23).
- Rulings added this session: R23 (mock ownership), R24 (SHAP additivity
  5e-3 + grammar), R25 (warm-up: no scoring while NaN). User rule: at most
  5 concurrent subagents (8 GB RAM) — see memory max-five-agents.md.
- Phase 4 in progress. Worktrees under the NEW scratchpad
  /private/tmp/claude-501/-Users-anmolagarwal-iotAnalyticsLab-epm/af9e2a51-3cb6-469f-b450-ace4807a1d0a/scratchpad/
  (reviews in `reviews/`, shared web brief in `briefs/web-common.md`,
  screenshots in `shots/`). If that scratchpad is gone, `git worktree list`.
  - feat/api (wt-api, 10 commits on main 010c057, 8 DIRTY files): T-API
    build DONE; api-code-1 + api-security-1 both NEEDS_WORK; fix pass 1
    was mid-way ("Now the tests for snapshot-after-seek, positional values,
    and sparkline") — dirty: api/app.py, deps.py, routers/machines.py,
    routers/plants.py, pipeline/consumer.py, store/pointintime.py + 2 more.
    RESUME: backend-builder, same fix brief (both reviews), "continue from
    the worktree state", then code-reviewer + security-reviewer re-review,
    merge (rebase onto main first: base is 010c057, main moved with docs).
  - feat/web-alert-feed (7 commits, 2 DIRTY: AlertCard.tsx, AlertFeed.tsx):
    code-1 + ux-1 NEEDS_WORK; fix pass 1 mid-way ("AlertCard needs the
    tabIndex prop" = roving tabindex work). RESUME: frontend-builder with
    the same fix brief, continue; then re-review both; merge.
  - feat/web-plant-floor (7 commits, clean): code-1 NEEDS_WORK (drop
    `motion` from the initial bundle, −41 kB gz; use CSS/WAAPI for the
    pulse); UX review never completed (stopped twice). RESUME: fix pass
    (code-1 item) then code re-review + ux review; merge.
  - feat/web-shap-viz (5 commits, clean): code-1 APPROVED; ux review never
    completed. RESUME: ux-reviewer; merge on APPROVED.
  - feat/web-machine-detail (6 commits, clean): build DONE, no reviews
    yet. RESUME: code-reviewer + ux-reviewer; merge.
  - feat/web-playback (0 commits, untracked web/src/features/playback/
    partial files from a builder stopped early): RESUME: frontend-builder
    with the T-WEB-PLAYBACK brief, "inspect and continue or restart".
  - feat/web-whatif (clean, nothing started), feat/web-model-compare
    (untracked stub dir from a killed builder): NOT STARTED.
- Shell follow-ups (one `fix/web-shell-integration` frontend-builder task
  after the features merge): web/e2e/smoke.spec.ts lines 39/42 (assert
  machine-tile-* and alert-feed instead of placeholders); routes.tsx must
  infer the plant from a deep-linked machine id (/machines/ims-01); pick
  one owner for `floor-demo-link` (shell vs floor.grid); T-WEB-WHATIF
  should reuse ShapWaterfall from shap-viz once merged.
- T-INFRA follow-ups (fold into the T-NODERED infra brief): `make evaluate`
  runs scripts/faithfulness.py first (R24); `make setup` runs contracts-ts;
  CI bundle-guard grep case-insensitive on contents; §2.2 lists
  contracts-ts; CI should assert the no-mock-in-prod test ran.
- Orchestrator decisions still open (non-blocking): per-tick `top_features`
  preview (API sends previews only after a machine's first alert); alert
  feed not run-scoped while `state_at` is; T-DOCS ADRs for R21–R25.

## Merge order when resuming
feat/api (after fix + 2 re-reviews) → feat/web-shap-viz (after ux) →
feat/web-machine-detail (after 2 reviews) → feat/web-plant-floor (fix + 2)
→ feat/web-alert-feed (fix + 2) → playback → whatif → model-compare (each
code + ux) → fix/web-shell-integration → T-NODERED (infra-builder; needs
the live API) → Phase 5 (T-WEB-E2E → T-PERF → T-DOCS → fresh-reader →
final review + codex audit) → Phase 6 tag v1.0.0. Rebase each branch onto
main before merging; run its gate; `--no-ff`; push; `gh run list` green
before the next merge. caffeinate was released at pause.

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

## Environment incident 2026-09-15
- Host disk filled to 0 B during parallel docker/pytest runs. Reclaimed ~7 GB:
  deleted extracted IMS copies from the old scratchpad datacache (kept
  bearings.zip), docker builder/volume prune, brew/pip caches, stale
  pytest tmp registries. Every builder/reviewer brief must now carry a disk
  warning (no extra venvs, no docker volumes, delete scratch). OrbStack had
  stopped; `orbctl start` fixed it.

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
