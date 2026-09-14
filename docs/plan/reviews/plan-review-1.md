# Plan reconciliation review 1 — NEEDS_WORK

Convention: **BE** = docs/plan/backend.md, **FE** = docs/plan/frontend.md. Ties go to backend naming unless the backend is missing something the frontend genuinely needs.

## Blocking issues

### A. Identifier and enum contract

1. **`machine_id` / `plant_id` formats are incompatible.** FE §3 uses `^[A-Z]-\d{2}$` (`M-03`) and slug plant ids. BE §3.1 fixes `machine_id = "{plant_id}-{nn}"` (`ai4i-03`, `ims-01`) and `plant_id ∈ {"ai4i","ims"}`. Change **FE**: adopt BE forms in §3, both wireframes (§1.3), §4.2 testid examples, §4.3 router test (`/machines/ai4i-03?alert=alt_9f2c71ab40d3e155`), §4.4. Alert ids are `alt_<16 hex>`.

2. **Model discriminator `"gbm"` vs `"lgbm"`.** Change **FE** to `"lgbm"` throughout, including testids `compare-prob-lgbm` / `compare-prob-rf` and §4.3 wording.

3. **`status` and `severity` are two different enums; FE collapsed them.** BE: machine `status: "healthy"|"watch"|"alert"|"offline"`; alert `severity: "medium"|"high"|"critical"`. Change **FE**: introduce `MachineStatus` and `AlertSeverity` as above; add `offline` treatment to §6.3; alert-feed filter list becomes medium/high/critical; `alert-filter-severity` testid values follow.

4. **§6.3 glow table lacks `medium` and `offline` rows.** Change **FE** §6.3: six rows (healthy/watch/alert/offline; medium/high/critical) each with a non-colour glyph.

### B. Time representation

5. **`t` vs `ts`/`dataset_ts`.** **FE changes**: use `dataset_ts` and `ts` in §3.1, §3.1.1, §3.2, §3.3 and the ring buffer. Both ISO-8601 strings on the wire; decode parses `dataset_ts` once into the Float64Array ring buffer. **BE** adds a sentence to §3.5 that WS frames use the same two-clock ISO representation as MQTT.

### C. SHAP space (contradicts R3)

6. **BE annotates SHAP values as log-odds.** Change **BE** §3.4 comments to probability space; §3.9/§4 additivity test asserts `base_value + Σ shap + other_contributions_shap == probability`; §6 R3 records the closed decision (`model_output="probability"`, `feature_perturbation="interventional"`, background 256 rows, seed from settings). `RiskMessage.top_features[].shap` is in the same space; say so.

7. **`shap_space` field required by FE, absent in BE.** Change **BE** §3.4: add `shap_space: Literal["probability"]` to `Explanation` and `WhatIfResponse`.

8. **FE `final_value` vs BE `output_value`; FE `other_contributions_sum` vs BE `other_contributions_shap`.** Change **FE** §3.1.1 and §4.3 to BE names. **BE** states `output_value == probability` explicitly in §3.4.

9. **`sentence_refs` vs `sentence_spans`.** Change **FE** to `sentence_spans` (§3.1.1, §4.3, §7 item 2).

### D. Explanation / ShapContribution field diff

10. **Contribution field names and nullability.** FE `name`→`feature`; FE `window`→`window_hours: int|null` (FE formats label); BE `unit: str`→`str|null`; FE `value: number`→`number|null` with a designed null state; FE adds `stat`, `framing`, `threshold`, `consecutive_hours`, `direction` (drives ▲/▼ glyph).

11. **BE has no per-feature sentence fragment.** Change **BE** §3.4: add `sentence: str` to `ShapContribution` (rendered clause from §3.9 templates) and persist it: `shap_values` table gains `sentence TEXT NOT NULL`.

12. **FE Explanation fields absent from BE.** **BE** adds `machine_id: str` and `model_kind: Literal["lgbm","rf"]`. **FE** drops `severity` and `top_k` from Explanation.

13. **"ALL features present" vs top-k truncation.** Change **FE** §3.1.1 comment: top `top_k` (default 8) by |shap| desc; remainder folded into `other_contributions_shap`.

### E. REST surface

14. **Paths differ.** FE → BE forms: `GET /api/machines?plant_id=`; `GET /api/telemetry?machine_id=&since=&until=`; `GET /api/risk?machine_id=&since=&until=`; `POST /api/replay/command` with `ReplayCommand{command, speed, dataset_ts, request_id}` (FE §4.3 playback test updates); `GET /api/state_at?plant_id=&dataset_ts=`. `GET /api/plants` returns a bare `list[Plant]`; FE envelope `{items, next_cursor}` only where BE pages (`/api/alerts`).

15. **Ten response models named in BE §3.4 are never defined.** `HealthResponse`, `TelemetrySeries`, `RiskSeries`, `AlertPage`, `Alert`, `GlobalImportance`, `ConfigResponse`, `ConfigPatch`, `ModelInfo`, `FeatureDisagreement`. **BE** defines all ten with binding fields:
   - `TelemetrySeries` columnar: `{dataset_ts: list[datetime], channels: dict[str, list[float|None]]}`, equal lengths, server-side LTTB to `max_points`.
   - `RiskSeries`: `{dataset_ts: [...], probability: [...], alerts: list[AlertMarker]}`, `AlertMarker = {alert_id, dataset_ts, severity, probability}`.
   - `Alert` carries `headline: str` and `top_feature: str`; `alerts` table gains `top_feature`.
   - `GlobalImportance` precomputed for beeswarm: `{n_alerts, features: [{feature, display_name, mean_abs_shap, points: [{shap, value_percentile, alert_id}]}]}` with `?limit=`.
   - `HealthResponse` includes `model_id` and replay state.

16. **`Plant` and `Channel` mismatches.** **FE** adopts BE `Plant` (`dataset_start`, `dataset_end`, `available`, `unavailable_reason`, `channels`, `row_interval_seconds`); adds a tested "plant unavailable" state to §4.3. `Channel` → `ChannelSpec = {name, display_name, unit, vibration_like, nominal_min, nominal_max}` in §3.1, §4.3, §6.4.

17. **`MachineSummary` vs FE `Machine`.** **FE** → `probability: float|None`, `dataset_ts`, `open_alert_id`, `risk_sparkline`; drop `machine_type`; sparkline length read from payload, not hardcoded.

18. **What-if response shape.** **BE** adds `gradients: dict[str, float]` and `sentence_spans` to `WhatIfResponse`. **FE**: `WhatIfResponse` is its own type; store slices change; `latency_ms`→`compute_ms`; `whatif.lastLatencyMs` measured client-side around the fetch (that is the DoD number), `compute_ms` displayed separately. §4.4 step 5 asserts the client-side number.

19. **`state_at` per-machine explanation ids.** **FE** derives the map via `active_alerts[].machine_id` → `alert_id` → `active_explanations[].alert_id`. **BE** states in §3.4 that at most one alert per machine is open at a time.

### F. WebSocket surface

20. **Path.** **FE** → `/ws?plant_id=`.

21. **Per-frame `seq` / reconnect-resume absent from BE.** **FE drops resume**: full re-snapshot on reconnect (`hello` then `snapshot`). Change FE §1.1, §3.2, §3.3 (`lastSeq`→`lastMessageAt`), §4.3 reconnect test, wireframe.

22. **Frame-type union mismatch.** **FE** handles `hello` (stores `run_id`, plant descriptor; shows `run_id` in top bar with `run-id` testid). `playback`→`replay_state` with BE `ReplayState` fields. **BE** §3.5 adds server→client `ping` every `api.ws_ping_seconds` (new key, default 10) regardless of replay state; client replies `pong`. **FE** ignores unknown types without error (say so in §3.2).

23. **`telemetry` / `risk` WS frame bodies.** **BE** changes WS frames to batched positional form: `telemetry = {type, dataset_ts, ts, updates: [{machine_id, dataset_ts, seq, values: list[float|None]}]}` coalesced per `api.ws_flush_ms`; `risk = {type, updates: [{machine_id, dataset_ts, probability, status, alert_id, model_id, top_features}]}`. MQTT `TelemetryMessage` keeps object-map `channels`; BE §3.3/§3.5 state the deliberate divergence. **FE** `risk`→`probability`.

24. **Channel order stability.** **BE** §3.1/§3.4 declares `Plant.channels` canonical fixed order; `MachineDetail.channels` identical; `values[]` positional; changes only with a version bump. FE drops `channels_version`.

25. **`alert`/`explanation`/`snapshot` envelope.** Use BE spread form; FE changes. **BE** states WS `alert` frame is the REST `Alert` model. **BE** `snapshot` gains `replay_state` and per-machine current `values[]`.

26. **Client→server messages.** **BE** deletes `subscribe` (query param is the full subscription) and the client-initiated `ping`/`pong` pair in favour of server heartbeat (item 22). Both plans state: authoritative transport control = REST `POST /api/replay/command`.

### G. Rulings compliance

27. **R7 violated: FE hand-writes `ws.ts`.** **FE** deletes §3.2.1 parity machinery and `ws-parity.test-d.ts`; `ws.ts` is generated by `make contracts` from `contracts/ws-schema.json`; §3.2 TypeScript block becomes a requirements statement. Remove references to `GET /ws/schema` and `contracts/ws.schema.json`.

28. **R6 violated: BE coverage omit list too wide.** **BE** §4 → exactly R6's list. `xpm/replay/main.py` becomes `xpm/replay/__main__.py`; `api/app.py` and `store/db.py` covered via ASGITransport tests.

29. **R2 partially contradicted; `.gitignore` unowned.** **BE** §0 restates rationale (raw not committed; processed parquet committed; model artefacts reproducible). Add `.gitignore` to T-INFRA. Add `make data-ims` to §2.2 and `tests/data/test_processed_size.py` (<5 MB) to T-DATA.

30. **BE §6 still presents R1/R3/R4/R5 as open.** Convert to stated decisions citing the rulings. Add `make dev PULL=1` README note and GHCR publish job in `.github/workflows/ci.yml` to T-INFRA.

31. **R9 violated: lowercase task ids in FE.** Change globally to `T-WEB-*`. Add canonical ids for Phase 5 nodes (see 35).

### H. File ownership collisions

32. **`web/src/contracts/**` claimed by both.** T-CONTRACTS owns generated `web/src/contracts/api.ts` and `ws.ts` (not committed). T-WEB-SHELL owns `web/src/contracts/index.ts` and `web/src/contracts/.gitignore`. Filename is `api.ts`. Drop `web/openapi-ts.config.ts`; keep BE's CLI invocation in the Makefile.

33. **Two web container definitions.** **FE owns** `web/Dockerfile`, `web/nginx.conf`, `web/.dockerignore`; delete `docker/web.Dockerfile` from T-INFRA; compose references `web/Dockerfile`.

34. **`make dev` means two things.** `make dev` = `docker compose up --build`. Vite dev is `pnpm -C web dev`, not a Make target. **FE** §6.7 changes.

35. **Unowned files and unnamed tasks.** Add `T-DOCS` (owns `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` pre-seeded with ADRs for R1–R9+, `docs/FINAL_REVIEW.md`, `docs/LAB_REPORT.md` co-authored with T-NODERED's output, README screenshots/GIF script under `scripts/`, release/tag step) to **BE**. Add `T-WEB-E2E` (owns `web/e2e/journey.spec.ts`, `web/e2e/perf.spec.ts`) to **FE**. Map "tagged v1.0.0" and "merged --no-ff" to T-DOCS.

36. **`openapi-typescript` declared by wrong plan.** Both plans: T-WEB-SHELL pre-declares `openapi-typescript@7` and `json-schema-to-typescript` in `web/package.json`; T-CONTRACTS only invokes them.

### I. Dependency graph

37. **BE graph false `API --> FE` edge.** Remove; keep `CONTRACTS --> FE`; add `API --> WEB_E2E`.

38. **FE graph roots contracts in the API task.** Rename node to `T-CONTRACTS (contracts/openapi.json + contracts/ws-schema.json)`. Delete the "hand-checked-in snapshot of api.d.ts" escape hatch.

39. **FE Phase 5 undeclared backend deps.** Add edges from T-API, T-REPLAY, T-MODEL, T-SHAP, T-DATA to T-WEB-E2E.

### J. Testability

40. **Phase-5 e2e sequence not achievable as written.** Step 5 must assert the client-side round trip (item 18). Step 6 needs item 19. Step 1 collides with `replay.autostart`/`loop`: **BE** states a loop increments `run_id` and the e2e/compose profile sets `replay.loop=false`; **FE** §4.4 pins the run via `run_id` from `hello`.

41. **FE tests hardcode 12 tiles; IMS has 4.** Grid is `machine_count`-driven; §4.3 adds a 4-machine case. Ring-buffer sizing from `Plant.channels.length` (AI4I 7 channels, IMS 9): 12 × 9 × 3600 × 8 B ≈ 3.1 MB.

## Non-blocking suggestions (orchestrator promoted 2 and 10 to blocking; see rulings R10+)

1. GOAL coverage is complete once items 35 and 40 land.
2. `Explanation.caveat` has no home in the UI: render a persistent footnote under the sentence with `explanation-caveat` testid.
3. `alerts.closed_dataset_ts_ms` is never exposed; either expose `closed_dataset_ts` on `Alert` or note closure is internal to `state_at`.
4. `ConfigPatch` allowing `replay.speed` duplicates the replay command; remove it.
5. Collect FE UI constants into `web/src/config.ts` owned by T-WEB-SHELL; `speed` type from the generated contract.
6. Unit test for slope rendering fallback when window mean is zero.
7. Wire `n_features` through so the roll-up label reads "146 other features".
8. Confirm the `no-mock-in-prod` test still executes if `web/src/mock/` is excluded from coverage.
9. Units come from the backend at runtime; FE formatter must not re-map them.
10. Add `plants.<id>.demo_machine_id` to settings.yaml; plant floor deep-links it for the README GIF flow.

NEEDS_WORK
