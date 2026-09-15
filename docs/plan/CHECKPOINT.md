# Orchestrator checkpoint (auto-maintained; read this first after /compact or resume)

Updated: 2026-09-15 14:40 IST — Phase 3 closed except feat/model; Phase 4 started.

## Where we are
- Phase 1, 2 DONE. Phase 3 merged into main: T-FEATURES, T-REPLAY,
  fix/features-ci (f5aebd4, CI GREEN), fix/features-settings (8d6ebf4, CI
  GREEN), feat/web-shell (a2883af; CI web job RED only because
  pnpm/action-setup has no version — fix/infra-ci in flight).
- main history is trailer-free, author anmolagarwal2625+github@gmail.com.
- Branches / worktrees (`git worktree list`; OLD scratchpad
  9a9ac25c-… holds wt-model, NEW scratchpad af9e2a51-… holds the rest):
  - feat/model (wt-model, 8 commits, rebased on main, APPROVED by
    model-code-1 + model-code-2, full gate green after rebase): MERGE NEXT,
    as soon as CI is green again.
  - fix/infra-ci (wt-infra-ci, infra-builder IN FLIGHT): pnpm/action-setup
    package_json_file, web build + mock guard step in CI, SHA-pin actions,
    Dockerfile tdigest comments. Needs code-reviewer + security-reviewer,
    then merge and confirm CI green BEFORE any other merge.
  - feat/shap (wt-shap, branched from feat/model be20040, backend-builder
    IN FLIGHT on T-SHAP): after feat/model merges, `git rebase main` it,
    then code-reviewer.
  - feat/web-mocks (wt-web-mocks, frontend-builder IN FLIGHT on T-WEB-MOCKS
    per new ruling R23): extends web/src/mock to the full §3.1 REST + WS
    surface. code-reviewer (+ux-reviewer light) then merge; THEN spawn the
    seven T-WEB-* feature builders in parallel, each on feat/web-<name>
    worktrees off main, briefs from frontend.md §1.2/§2/§4.2/§4.3/§4.5/§6.
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
