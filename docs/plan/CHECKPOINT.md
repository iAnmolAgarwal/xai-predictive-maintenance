# Orchestrator checkpoint (auto-maintained; read this first after /compact or resume)

Updated: 2026-09-15 18:30 IST — usage limit hit at ~17:40 and reset at 18:20; Phase 4 builders relaunched.

## Where we are
- Phase 1, 2, 3 DONE and merged: T-FEATURES, T-REPLAY, fix/features-ci,
  fix/features-settings, feat/web-shell, fix/infra-ci (PR #1, both reviews
  APPROVED, CI green), feat/model (APPROVED x2), feat/shap (T-SHAP, review 1
  + ruling R24). CI on main GREEN through the model merge; the shap merge
  push is the latest run.
- main history is trailer-free, author anmolagarwal2625+github@gmail.com.
- Branches / worktrees (`git worktree list`; OLD scratchpad
  9a9ac25c-… holds wt-model, NEW scratchpad af9e2a51-… holds the rest):
  - feat/api (wt-api, branched from the PRE-rebase feat/shap head b568e82;
    backend-builder IN FLIGHT on T-API). When it reports: `git rebase --onto
    main b568e82 feat/api` in wt-api, run the gate, then code-reviewer AND
    security-reviewer, fix loop, merge.
  - MERGED since: fix/explain-ci (golden rtol 1e-12; CI green), feat/web-mocks
    (T-WEB-MOCKS, review 1 NEEDS_WORK → fix pass → review 2 APPROVED).
  - 17:40 429: all eight builders died. T-API kept 3 commits + dirty tests;
    feature worktrees were empty. 18:25 relaunched: T-API (continue) +
    plant-floor, machine-detail, shap-viz, alert-feed. STILL TO LAUNCH when
    a slot frees: playback, whatif, model-compare (worktrees exist, clean;
    model-compare has an untracked stub dir to inspect). Cap concurrent
    builders at ~5 to avoid another session-limit hit.
  - Seven T-WEB-* frontend-builders, one per worktree
    wt-web-{plant-floor,machine-detail,shap-viz,alert-feed,playback,whatif,
    model-compare} on branches feat/web-<name> off main (post web-mocks).
    Shared brief: scratchpad/briefs/web-common.md; ports 5500–5569. Each
    needs code-reviewer AND ux-reviewer, fix loop, then merge one at a time
    (rebase each onto main before merging; they only touch their own
    directory + one e2e spec, so conflicts are not expected).
  - Rulings added this session: R23 (mock ownership), R24 (SHAP additivity
    5e-3 + grammar additions), R25 (warm-up: no scoring while NaN).
  - T-INFRA follow-ups pending (fold into T-NODERED's infra brief): `make
    evaluate` must run scripts/faithfulness.py first (R24); `make setup`
    should run `contracts-ts`; CI guard grep should be case-insensitive on
    contents; §2.2 should list `contracts-ts`.
- Reviews of this session live in the NEW scratchpad `reviews/`:
  model-code-1/2, features-ci-code-2 (+Review 3), web-shell-verdicts.md
  (code-2 + ux-2 both APPROVED, delivered inline).
- Old worktrees wt-features-ci / wt-features-settings / wt-web-shell are
  merged; remove them (`git worktree remove`) when convenient.

## Next after the in-flight three
1. Merge order: fix/infra-ci (after 2 reviews) → feat/model → feat/web-mocks
   → feat/shap (after review) → T-API (backend-builder; needs SHAP; code +
   security review) → T-NODERED (infra-builder) → seven T-WEB-* (code + ux
   each) → Phase 5 (T-WEB-E2E → T-PERF → T-DOCS → fresh-reader → final
   review + codex audit) → Phase 6 tag v1.0.0.
2. T-API brief must carry: model-code-1 handoff notes, T-SHAP report, the
   warm-up NaN alert-suppression decision (first ~14.3 h of features are
   NaN; suppress scoring until the vector is complete and expose it as
   `MachineSummary.probability = null`), R10/R11/R12/R21.

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
