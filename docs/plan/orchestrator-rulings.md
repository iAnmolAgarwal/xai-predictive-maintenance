# Orchestrator rulings on planner-flagged questions

Binding for the plan-reviewer and every builder. Each ruling becomes an ADR in
docs/DECISIONS.md during Phase 5.

## R1. Docker images: build locally by default, publish to GHCR from CI
`docker compose up` builds images locally (no external registry dependency for
a grader). CI additionally publishes images to GHCR on `main`; README documents
`make dev PULL=1` as the fast path. The 3-minute target is measured on a
machine with a warm base-image cache (python:3.12-slim, node:22-alpine,
eclipse-mosquitto, nodered/node-red); the fresh-reader reports the cold number
honestly.

## R2. IMS: commit the processed band-energy features, not the raw archive
The raw 1.4 GB download is never part of `make dev`. `make data-ims` downloads,
extracts, and regenerates `data/processed/ims/*.parquet` (must stay < 5 MB,
enforced by a data test). Those processed parquet files ARE committed, so a
fresh clone streams both plants immediately with zero downloads. AI4I (small
CSV) is fetched by `make data` and also cached under data/processed; the AI4I
processed parquet is committed too if < 5 MB, so `make dev` needs no network
beyond Docker. The .gitignore is amended by T-INFRA to allow
`data/processed/**/*.parquet` and `data/processed/**/*.json`.

## R3. SHAP in probability space, interventional perturbation, 256-row background
Waterfall bars must sum from base value to the on-screen probability. LightGBM
via `shap.TreeExplainer(model, data=background, feature_perturbation=
"interventional", model_output="probability")`; RandomForest via TreeExplainer
on the classifier (probability output native). The same explainer
configuration is used for serving, what-if, and the faithfulness check.
Background sample size and seed live in settings.yaml.

## R4. Ablation reported per plant, honestly
AI4I rows are i.i.d.; windowed features are expected to help on IMS and may
not help on AI4I. EVALUATION.md reports both and says so. No fabricated lift.

## R5. Reproducibility scope
Same seed + same speed + unmodified config ⇒ identical alert ids, timestamps,
explanations. A config change via PUT /api/config starts a new "run id"; the
API exposes the run id so the dashboard can show it.

## R6. Coverage omit list
`.coveragerc` may omit only: `__main__.py`, container entrypoint scripts, and
the `make train` CLI wrapper. Everything else counts toward the 85% gate.

## R7. Frontend contract requirements are all accepted
- `sentence_refs` / `SentenceSpan` character offsets: backend emits them.
- `GET /api/state_at`: backend implements it exactly as the frontend needs.
- `Channel.min/max` in the machine descriptor for fixed chart y-domains: yes.
- Positional `values[]` aligned to the channel list in telemetry frames: yes.
- `gradients` in the what-if response for optimistic sub-frame updates: yes.
- WebSocket schema: backend emits `contracts/ws-schema.json`; `make contracts`
  generates `web/src/contracts/ws.ts` from it via json-schema-to-typescript.
  The frontend never hand-writes a network type.

## R8. Frontend assumptions confirmed
Dataset time is the displayed time everywhere (wall clock only in a tooltip).
One plant at a time; switching plant re-subscribes the WebSocket. Below 1440 px
the alert rail becomes an overlay drawer with an unread badge.

## R9. Task ids
Backend plan task ids (T-INFRA, T-CONTRACTS, ...) are canonical. The frontend
plan's tasks are T-WEB-SHELL, T-WEB-PLANT-FLOOR, T-WEB-MACHINE-DETAIL,
T-WEB-SHAP-VIZ, T-WEB-ALERT-FEED, T-WEB-PLAYBACK, T-WEB-WHATIF,
T-WEB-MODEL-COMPARE. The plan-reviewer must confirm both files use these.

## Rulings after plan review 1 (docs/plan/reviews/plan-review-1.md)

All 41 blocking items are accepted as written, with the reviewer's
recommended resolution where it offered one. Additional rulings on the forks
it left open:

## R10. No WebSocket resume; full re-snapshot on reconnect
The server sends `hello` then `snapshot` on every connect. No per-plant frame
sequence, no replay ring. Frontend keeps only `lastMessageAt` for liveness.

## R11. Heartbeat direction
Server emits `ping` every `api.ws_ping_seconds` (default 10) regardless of
replay state; client replies `pong`. No client-initiated ping. No `subscribe`
message; the `plant_id` query parameter is the complete subscription. All
replay control goes through REST `POST /api/replay/command`; the WebSocket
only broadcasts `replay_state`.

## R12. Replay looping and run ids
`replay.loop` defaults to true for demos; each loop increments `run_id` and
the `hello`/`replay_state` frames carry it. The e2e profile sets
`replay.loop=false` via environment override. `ConfigPatch` may not mutate
`replay.speed` (review suggestion 4 accepted).

## R13. Caveat and demo machine are required, not optional
Review suggestions 2 and 10 are promoted to blocking: the SHAP-vs-causation
caveat is rendered under the explanation sentence with testid
`explanation-caveat`; `plants.<id>.demo_machine_id` lives in settings.yaml and
the plant floor deep-links it. Suggestions 3, 5, 6, 7, 9 are also adopted.

## R14. New tasks
`T-DOCS` is defined in backend.md and owned by the docs-writer agent in
Phase 5. `T-WEB-E2E` is defined in frontend.md and owned by a
frontend-builder in Phase 5. Phase 5 also includes `T-PERF` (profiling at 20x
with 12 machines; may touch files across web/src/features/* by exception,
serialised after all Phase 4 merges) — define it in frontend.md.

## R15. Contract artefact filenames
`contracts/openapi.json`, `contracts/ws-schema.json` (committed, owned by
T-CONTRACTS). Generated, never committed: `web/src/contracts/api.ts`,
`web/src/contracts/ws.ts`. Committed, owned by T-WEB-SHELL:
`web/src/contracts/index.ts`, `web/src/contracts/.gitignore`.

## Rulings after plan revision 1

## R16. One probability on screen: no post-hoc calibrator in the serving path
The served LightGBM probability is the number used for alerting, display,
`RiskMessage.probability`, `Explanation.output_value`, and the SHAP
explanation. No isotonic/Platt calibrator sits between the model and the
alert threshold. Calibration is reported in EVALUATION.md as a diagnostic
(reliability curve, Brier score); if the raw model is poorly calibrated the
fix is in training (class weighting, `scale_pos_weight`, or the threshold
default), never a separate number. Backend §6 Risk 3 is closed by this ruling.

## R17. Roll-up label source
`Explanation.other_contributions_count` and `ModelInfo.n_features` both
exist; the frontend uses `other_contributions_count` for the "N other
features" label and needs no model lookup for it.

## Rulings after plan review 2

## R18. Media capture tooling
`tsx` is pre-declared in `web/package.json` devDependencies by T-WEB-SHELL
alongside `openapi-typescript` and `json-schema-to-typescript`; `make media`
runs `pnpm -C web exec tsx scripts/capture_media.ts`. (Review 2 item 15.)

## R19. ADR numbering
ADR-001…ADR-019 map one-to-one to rulings R1–R19. Non-ruling decisions
(SQLite, LightGBM, IMS horizon N, MQTT/WS divergence, etc.) are numbered from
ADR-020 upward in backend.md §2's ADR table, which is the single source T-DOCS
copies into docs/DECISIONS.md. (Review 2 item 3.)

## R20. Frontend perf numbers destination
T-PERF's measurements go into its report and are transcribed by T-DOCS into
README.md and docs/FINAL_REVIEW.md, never into docs/EVALUATION.md (which is
T-MODEL's machine-generated file). (Review 2 item 16.)
