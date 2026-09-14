# Goal: "Why Did the Model Flag This Machine?"

Explainable-AI IoT Predictive Maintenance system. This file is the verbatim
requirements source for every planner, builder and reviewer.

## Assignment text (graded)

> Build a predictive maintenance pipeline (standard), then add SHAP (SHapley
> Additive exPlanations) values on top of the GBM/Random Forest model to
> generate human-readable explanations for each alert: "This motor was flagged
> because vibration at 3 kHz exceeded the 95th percentile for 4 consecutive
> hours." Dashboard shows not just predictions but the contributing sensor
> features ranked by importance.

Context: college IoT Analytics lab (JIIT) whose standard platform is Node-RED.
No hardware. Data comes from public datasets, replayed over MQTT to simulate
live sensors.

## Quality bar (non-negotiable)

- Every module has tests. Backend >= 85% line coverage on non-glue code.
  Frontend has component tests for every interactive element and at least one
  end-to-end smoke test (Playwright).
- Lint + format + typecheck clean: `ruff` + `mypy --strict` on Python,
  `eslint` + `tsc --noEmit` on TypeScript. CI runs all of it on every push
  (GitHub Actions).
- No placeholder text, no `TODO`, no mocked data paths in the shipped app. If
  something is genuinely out of scope, it is removed, not stubbed.
- Everything runs from a fresh clone with one command (`make dev` or
  `docker compose up`).
- Conventional Commits, feature branches merged `--no-ff`, `main` always green.

## Architecture (may be refined, not discarded)

```
[Replay Publisher] --MQTT--> [Broker] --> [Ingestion + Feature Engine] --> [Model + SHAP Service] --> [WebSocket] --> [Dashboard]
      ^                                              |                                 |
   dataset rows                                  TimescaleDB / SQLite             alert store + explanation store
                                                                                          |
                                                                            [Node-RED flow] (parallel consumer, lab compliance)
```

- **Replay Publisher** (Python): streams dataset rows over MQTT at a
  configurable rate (default 2 Hz, adjustable live from the dashboard: 0.5x,
  1x, 5x, 20x). Multiple machines in flight simultaneously. Deterministic seed
  so demos are reproducible.
- **Broker**: Mosquitto via Docker.
- **Feature Engine** (Python): rolling-window features per machine: mean, std,
  min/max, slope, EWMA, and for any vibration-like channel, band energies via
  FFT. Windows: 1 h / 4 h / 24 h in dataset-time.
- **Model**: Gradient-boosted trees (LightGBM or XGBoost) AND a Random Forest,
  trained offline, versioned, with a documented training script and evaluation
  report (PR-AUC, recall at fixed precision, calibration curve). The GBM is the
  served model; RF is kept for the comparison view.
- **SHAP Service**: `shap.TreeExplainer` on the served model. For every alert,
  produce per-feature SHAP values, the base value, and a rule-based
  natural-language explanation built from the top-k features
  ("vibration_3khz_p95_4h contributed +0.31: stayed above its 95th percentile
  for 4 consecutive hours"). Templates must be feature-aware (percentile
  framing, threshold framing, trend framing), not a generic "feature X was
  high".
- **API**: FastAPI. REST for history/config, WebSocket for live telemetry +
  alerts + explanations. OpenAPI spec is the contract the frontend is built
  against.
- **Dashboard**: React + TypeScript + Vite. See Dashboard section. This is
  where most of the effort goes.
- **Node-RED flow** (`nodered/flow.json`): subscribes to the same MQTT topics,
  calls the SHAP service over HTTP, and renders a minimal Node-RED Dashboard
  view. Exists for lab-format compliance; must import cleanly into Node-RED
  4.x and work, but is not the showcase.

## Data

- **Primary: AI4I 2020 Predictive Maintenance** (UCI, id 601). Fetch via
  `ucimlrepo` or direct download in a `make data` step; never commit it.
- **Secondary: NASA IMS Bearing dataset** (real 20 kHz vibration,
  run-to-failure). This is what makes the "vibration at 3 kHz" narrative
  literally true. Ingest at least one test set, downsample and precompute band
  energies offline, and expose it as a second selectable "plant" in the
  dashboard. If the download is flaky, retry with backoff; if genuinely
  unavailable, ship AI4I-only and document exactly what was attempted in
  `docs/DECISIONS.md`.
- Failure labels: AI4I has them natively. For IMS, label the last N hours
  before end-of-record as "failure imminent" and document N and why.
- All thresholds (alert probability cutoff, percentile levels, "consecutive
  hours" windows) live in one config file with documented defaults. Nothing is
  hardcoded in business logic.

## Dashboard: "interactive and highly visually addictive"

Treat it as a product, not a lab UI.

- **Plant floor view**: a spatial map of all machines (grid or schematic), each
  a live tile with a health ring, sparkline of risk over the last window, and a
  status glow (healthy / watch / alert). Tiles animate on state change.
  Clicking a tile opens the machine.
- **Machine detail view**:
  - Live multi-channel telemetry with smooth streaming charts (no chart-redraw
    flicker; canvas or a streaming-capable lib).
  - Risk timeline with alert markers.
  - **SHAP waterfall** for the current/selected alert: base value ->
    contributions -> final probability, animated in. Hover any bar to see the
    feature's raw value, its historical percentile, and the sentence
    explaining it.
  - **Force-plot-style horizontal bar** of pushes up/down.
  - **Beeswarm / global importance** across all alerts for that machine.
  - The generated explanation sentence, prominently, with each feature name in
    it hyperlinked to its bar.
- **Alert feed**: a right-rail live feed of alerts with explanation
  one-liners; new alerts slide in. Filter by machine, severity, feature.
- **Playback controls**: pause/play/speed/scrub the replay. Scrubbing back
  re-renders the state at that time, including the explanation that was active
  then.
- **Model comparison toggle**: GBM vs RF side by side for the same alert:
  different probabilities, different SHAP attributions, with a one-line
  commentary on where they disagree.
- **"What-if" panel**: sliders on the top-5 features; recompute probability +
  SHAP in real time via the API. The single most engaging thing in the app;
  make it feel instant (< 150 ms round trip locally).
- **Aesthetic direction**: dark, high-contrast, industrial-instrument feel.
  Restrained motion (Framer Motion) that communicates state changes, not
  decoration. One accent colour for danger, one for healthy, neutrals
  elsewhere. Typography with a proper scale. Empty and loading states designed,
  not defaulted. 60 fps on a mid-range laptop with 12 machines streaming.
- Responsive down to 1280 px. Mobile not required.
- Keyboard navigable; colour is never the only signal.

## Docs (graded artefacts)

- `README.md`: what it is, architecture diagram (Mermaid), one-command run,
  screenshots/GIF of the dashboard (recorded with Playwright), how the
  explanation is generated, dataset credits.
- `docs/ARCHITECTURE.md`: components, data flow, topic schema, feature list
  with definitions, model card.
- `docs/DECISIONS.md`: ADR-style log; every non-obvious choice with
  alternatives considered. Include the SHAP-vs-causation caveat explicitly.
- `docs/EVALUATION.md`: model metrics, calibration, ablation showing the value
  of the windowed features, and a short section on explanation faithfulness
  (does removing the top-SHAP feature actually move the prediction the
  expected way).
- `docs/LAB_REPORT.md`: in the lab's format (Aim, Flow Design, Node
  Configuration, Code, Output, Result) covering the Node-RED flow.

## Definition of done

- `git clone` -> `make dev` -> dashboard live with 12 machines streaming within
  3 minutes on a fresh machine.
- Alerts fire with SHAP waterfall + generated sentence; sentence is
  feature-aware and matches the numbers on screen.
- What-if sliders update probability and attributions in < 150 ms round trip
  locally.
- Scrubbing the timeline reproduces historical explanations exactly.
- GBM vs RF comparison view works for any alert.
- Node-RED flow imports and runs against the same broker.
- Both datasets selectable (or IMS absence documented with evidence).
- CI green; coverage thresholds met; lint/typecheck clean.
- All docs present and verified by a fresh reader.
- Every commit on `main` follows Conventional Commits.
- `docs/FINAL_REVIEW.md` shows all criteria PASS.
- Pushed to GitHub, tagged `v1.0.0`.

## Toolchain available on the build machine

- macOS arm64, Python 3.12 via `uv`, Node 26 + pnpm, Docker 29 + Compose v5
  (OrbStack), `gh` CLI, `codex` CLI.
- Build phases and file ownership are decided in `docs/plan/backend.md` and
  `docs/plan/frontend.md`.
