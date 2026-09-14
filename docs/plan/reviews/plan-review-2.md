# Plan reconciliation review 2 — NEEDS_WORK

Convention: **BE** = `docs/plan/backend.md`, **FE** = `docs/plan/frontend.md`,
**R*** = `docs/plan/orchestrator-rulings.md`, **item N** = the numbered blocking
item in `docs/plan/reviews/plan-review-1.md`.

## Verification of review 1's 41 blocking items

Resolved in the revised text (verified field by field, not from the changelogs):
1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 16, 17, 19, 20, 21, 22, 24, 26, 27,
28, 29, 30, 31, 32, 33, 34, 36, 37, 38, 39, 40, 41.

Not fully resolved — see blocking issues below: **8** (partially: `output_value
== probability` is stated in BE §3.4.3 but BE §6 Risk 3 still breaks it),
**15** (`ConfigResponse` and `ModelInfo` are defined but two of their fields do
not match what FE consumes), **18** (FE's own `WhatIfResponse` listing drops
fields the FE renders), **23**/**25** (FE's `snapshot` and `risk` frame rows
still diverge from BE §3.5), **35** (`T-PERF`'s output has no owned home).

---

## Blocking issues

1. **BE §6 "Risk 3", §3.6, §3.7, §1 — a calibrator is still in the serving path
   and there are still two probabilities (violates R16).**
   BE §6 Risk 3 reads: "the calibrator is applied for alerting thresholds and
   for `Alert.probability`, and `Explanation.probability` / `output_value` are
   the **explained** (pre-calibration) probability". R16 closes exactly this and
   forbids it. Supporting text in the same state: BE §1 `xpm.model`
   ("fits LightGBM and RandomForest with fixed seeds, **calibrates**, samples…"),
   BE §3.6 `model.calibration: isotonic`, BE §3.7 registry layout
   `calibrator.joblib`.
   *Fix:* delete Risk 3 and replace it with a one-paragraph statement of R16
   (the served LightGBM probability is the only probability; it drives alerting,
   `RiskMessage.probability`, `Alert.probability`, `Explanation.output_value`
   and the SHAP explanation; calibration quality is reported in
   `docs/EVALUATION.md` as a reliability curve + Brier/ECE diagnostic only, and
   a poorly calibrated model is fixed in training via `class_weight` /
   `scale_pos_weight` / the threshold default). Remove `calibration: isotonic`
   from BE §3.6, remove `calibrator.joblib` from BE §3.7 (both `lgbm/` and
   `rf/`), and strike "calibrates" from BE §1. Keep
   `model.evaluation.calibration_bins` — it is the diagnostic. This is also what
   makes FE §4.4 step 4 ("`output_value` equals the probability printed on
   screen") achievable.

2. **BE header (lines 15–18), §2 T-DOCS, §4 "docs", §6 — R16 and R17 are not
   recorded anywhere.** BE says it "records rulings R1–R15", T-DOCS is specified
   to write "ADR-001 … ADR-015, one per ruling R1–R15", and BE §4 makes a test
   assert that every ADR number referenced in the plan exists. R16 and R17 are
   binding and post-date that text.
   *Fix:* extend the header sentence to R1–R17, add ADR-016 (one probability, no
   serving calibrator) and ADR-017 (roll-up label source) to the T-DOCS
   responsibilities in BE §2, add short **R16** and **R17** entries to BE §6, and
   update the §4 assertion range to ADR-001 … ADR-017.

3. **BE — ADR numbers collide; T-DOCS cannot write `docs/DECISIONS.md` from this
   plan.** Four numbers are each claimed by two different decisions:
   ADR-005 = IMS labelling horizon (§3.2.3, §2) *and* R5 reproducibility scope
   (§6); ADR-006 = "AI4I is tabular" (§2) *and* R4 ablation (§6) *and*
   "ADR-006a" for R6; ADR-007 = model artefacts not committed (§0) *and*
   "ADR-007a" for R7; ADR-010 = MQTT/WS divergence (§3.3) *and* R10 (§6).
   ADR-004 is SQLite in §0 but "one per ruling" makes it R4 in §2. The `a`
   suffixes are not a numbering scheme.
   *Fix:* publish one explicit table in BE §2 (T-DOCS) mapping ADR number →
   decision, with rulings R1–R17 occupying ADR-001…ADR-017 and every
   non-ruling decision (SQLite, model artefacts, IMS labelling horizon, AI4I
   tabular, MQTT/WS divergence) taking ADR-018 and up. Then make every in-text
   citation in §0, §3.2.3, §3.3, §6 point at that table.

4. **FE §3.1.1 "Roll-up label", §3.1 (`GET /api/models` row), §4.3
   (`T-WEB-SHAP-VIZ`), §7 item 17 — the roll-up label is still derived from
   `ModelInfo.n_features - contributions.length` (violates R17).** R17: the
   frontend uses `Explanation.other_contributions_count` and needs no model
   lookup. FE's `Explanation` type in §3.1.1 also omits both
   `other_contributions_count` and `n_features`, which BE §3.4.3 defines.
   *Fix:* in FE §3.1.1 add `other_contributions_count: number;` and
   `n_features: number;` to the `Explanation` type; change the roll-up
   derivation to `` `${other_contributions_count} other features` `` with no
   `ModelInfo` dependency and no "unavailable" degradation branch; change the
   §4.3 shap-viz assertion to read the count from the explanation; delete
   "waterfall roll-up label" from the `GET /api/models` row in §3.1 (models is
   still needed for the compare-panel header); rewrite §7 item 17 as closed by
   R17. Add the same two fields to the `WhatIfResponse` listing (see item 8).

5. **FE §3.1 `ModelInfo.kind` does not exist — BE calls it `family`.**
   BE §3.4.2: `family: Literal["lgbm", "rf"]`. FE §3.1 table ("the frontend
   reads `model_id`, `kind` and `n_features`") and the `ModelInfo` type block
   both use `kind`. The generated `api.ts` will have no `kind`.
   *Fix:* FE → `family: "lgbm" | "rf"` in both places. (Note `Explanation`
   correctly uses `model_kind`; the two names are genuinely different fields on
   different models, so do not unify them.)

6. **FE §3.2 `snapshot` row contradicts BE §3.5 `snapshot`.**
   BE: `{type, plant_id, run_id, dataset_ts, machines: MachineSnapshot[],
   active_alerts: Alert[], replay_state: ReplayState}` where
   `MachineSnapshot = MachineSummary + values: list[float|null]`. FE invents a
   parallel top-level array `values: Array<{machine_id, dataset_ts, values}>`
   and omits `run_id`.
   *Fix:* FE §3.2 → `machines: MachineSnapshot[]` (per-machine `values[]`
   embedded), add `run_id`, delete the top-level `values` array. FE §3.2
   requirement 3 prose is already correct and needs no change; the §4.3 shell
   snapshot test must seed ring buffers from `machines[].values`.

7. **FE §3.2 `risk` row carries a top-level `dataset_ts` that BE does not
   emit.** BE §3.5: `risk = {type, plant_id, ts, updates: RiskUpdate[]}` —
   `dataset_ts` is per update only. (FE's `telemetry` row conversely omits BE's
   top-level `plant_id`, which is harmless under the ignore-unknown-fields rule,
   but reading a field that is absent is not.)
   *Fix:* FE §3.2 → `risk` payload `{type, plant_id, ts, updates: [...]}`; take
   `dataset_ts` from each update. Add `plant_id` to the `telemetry` row for
   symmetry.

8. **FE §3.3 `WhatIfResponse` omits fields the FE itself renders.** BE §3.4.3
   defines `model_kind`, `other_contributions_count`, `n_features`,
   `provisional`, `caveat` on `WhatIfResponse`. FE's listing has none of them,
   yet FE §1.2 ("rendered with an explicit 'provisional' chip and the same
   `explanation-caveat` footnote") and FE §4.3 (`whatif-provisional` and
   `explanation-caveat` are both present) require `provisional` and `caveat`,
   and the shared `ShapWaterfall` needs the roll-up count from item 4.
   *Fix:* add `model_kind: "lgbm" | "rf"`, `other_contributions_count: number`,
   `n_features: number`, `provisional: boolean`, `caveat: string` to the FE
   `WhatIfResponse` block, and extend the shared structural subset accepted by
   `ShapWaterfall` to include `other_contributions_count`.

9. **FE §3.1 `Alert` omits `machine_display_name`, which FE §6.6 announces.**
   FE §6.6: the live region announces "`{severity}` on `{display_name}`:
   `{headline}`". The FE `Alert` listing has `machine_id` only; BE §3.4.2
   `Alert` has `machine_display_name: str` (and `closed_dataset_ts`).
   *Fix:* add `machine_display_name: string` and
   `closed_dataset_ts: string | null` to the FE `Alert` listing, and state that
   the announcement uses `machine_display_name`.

10. **FE §3.1 `HealthResponse` nullability is wrong.** FE declares
    `run_id: string` and `replay: ReplayState`; BE §3.4.2 declares
    `run_id: str | None` (null before the first replay tick) and
    `replay: ReplayState | None`. The e2e readiness gate and step 1 in FE §4.4
    read `run_id` from health.
    *Fix:* FE → `run_id: string | null`, `replay: ReplayState | null`, and state
    that the e2e gate polls until `status === "ok"` **and** `run_id !== null`.

11. **`ReplayCommand.speed`'s type is not pinned in BE, but FE derives a closed
    union and its testids from it.** FE §1.1: "`Speed` type is
    `ReplayCommand["speed"]` from the generated contract, never a hand-written
    union"; FE §4.2 fixes testids `playback-speed-0.5|-1|-5|-20`. BE §3.3 only
    says `speed ∈ {0.5, 1.0, 5.0, 20.0}` in prose, while `replay.allowed_speeds`
    is a config list — so the Pydantic field could equally be `float | None`,
    which generates `number | null` and breaks FE's `Speed`.
    *Fix:* BE §3.3/§3.4 state explicitly
    `speed: Literal[0.5, 1.0, 5.0, 20.0] | None` on `ReplayCommand`, add a
    contract test that the literal set equals `replay.allowed_speeds` in
    `settings.yaml`, and note in BE §3.6 that changing `allowed_speeds` is a
    contract change requiring `make contracts`.

12. **`ConfigResponse.values` — the key set is undefined, and the FE reads five
    keys from it.** BE §3.4.2 says only "flat dotted keys"; it enumerates the
    *mutable* keys for `ConfigPatch` but never says what `values` contains. FE
    §3.1 reads `explanation.top_k`, `explanation.top_k_whatif` and
    `alerting.severity_bands`; FE §1.1/§1.2 additionally read
    `replay.allowed_speeds` and `api.sparkline_points` "from the API at
    runtime"; FE §1.1's `WS_SILENCE_TIMEOUT_MS` is really 2.5 ×
    `api.ws_ping_seconds`.
    *Fix:* BE §3.4.2 states that `ConfigResponse.values` is the **full flattened
    settings tree** (mutable and read-only alike), with `mutable_keys` marking
    the patchable subset, and names at minimum `explanation.top_k`,
    `explanation.top_k_whatif`, `explanation.top_k_preview`,
    `alerting.severity_bands.*`, `replay.allowed_speeds`,
    `api.sparkline_points`, `api.ws_ping_seconds`, `api.ws_flush_ms`,
    `api.max_series_points` as guaranteed present. FE §1.1 then derives
    `WS_SILENCE_TIMEOUT_MS` from `api.ws_ping_seconds` with the 2.5× factor as
    the only constant.

13. **FE contradicts itself on telemetry chart granularity for IMS.** FE §1.2
    and §4.3 require "one uPlot instance per `ChannelSpec` in
    `MachineDetail.channels`" and a test asserting "one chart per entry … in
    that order"; FE §7 item 16 says IMS renders the six band-energy channels in
    one grouped chart (four charts, not nine). The `telemetry-chart-{channel_name}`
    testid has no defined form for a grouped chart.
    *Fix:* pick the grouped rule (it is the better product decision), move it out
    of §7 into §1.2 as the binding behaviour ("channels with
    `vibration_like === true` **and** identical `unit` share one chart"), define
    the grouped testid (e.g. `telemetry-chart-group-{unit-slug}` with
    `telemetry-chart-{channel_name}` retained for ungrouped channels), and
    rewrite the §4.3 assertion to cover both the AI4I (7 charts) and IMS
    (4 charts) cases.

14. **FE §5 graph: `T-WEB-SHELL` has no dependency on `make contracts`, but it
    imports `@/contracts`.** `T-WEB-SHELL` owns `web/src/contracts/index.ts`
    (a barrel re-exporting the generated `api.ts` / `ws.ts`), `store/slices/*`,
    `shell/ws/client.ts` and `api/client.ts` — none of which typecheck before
    `T-CONTRACTS` has landed and `make contracts` has run. FE §5 nonetheless
    labels SHELL "PARALLEL: independent of backend runtime" with no `GEN` edge.
    *Fix:* add `GEN --> SHELL` to the FE §5 graph and reword the note to
    "independent of the backend *runtime*, but gated on `make contracts`".
    Mirror it in BE §5's parallelisability table row for `T-WEB-*`.

15. **`make media` invokes `pnpm -C web exec tsx`, but `tsx` is declared
    nowhere, and T-DOCS may not add it.** BE §2.2 `make media` runs
    `pnpm -C web exec tsx ../scripts/capture_media.ts`; `web/package.json` is
    owned by `T-WEB-SHELL` (Phase 3), whose pre-declared codegen devDependencies
    are `openapi-typescript@^7` and `json-schema-to-typescript@^15` only. T-DOCS
    (Phase 5) would have to edit a file it does not own.
    *Fix:* add `tsx` (and `@playwright/test`, if not already implied) to the
    devDependencies `T-WEB-SHELL` pre-declares in FE §2, and say so in BE §2.1
    next to the existing "Node tooling is not declared here" paragraph.
    Alternatively make `scripts/capture_media.ts` a Playwright spec run by
    `pnpm -C web exec playwright test` — but pick one and write it down.

16. **FE §4.5 sends `T-PERF`'s numbers into `docs/EVALUATION.md`, which is
    machine-written and owned by `T-MODEL`.** FE §4.5: "the numbers in
    `docs/EVALUATION.md` and `README.md` come from a real run of this spec".
    BE §2 (T-MODEL): "`docs/EVALUATION.md` is the one doc T-MODEL owns, because
    it is machine-written by `scripts/evaluate.py`. T-DOCS links to it and does
    not edit it." `T-PERF` owns no files at all. So the frontend perf numbers
    have no owner and no destination.
    *Fix:* FE §4.5 → the perf numbers land in `T-PERF`'s final report and are
    transcribed by **T-DOCS** into `README.md` and `docs/FINAL_REVIEW.md`;
    delete the `docs/EVALUATION.md` reference. Add "frontend performance
    (p95/p99 frame interval at 20× with 12 machines, from
    `web/e2e/perf.spec.ts`)" to the T-DOCS responsibilities in BE §2.

17. **FE §7 still carries two "Open questions for the plan-reviewer".** Both are
    now answered and must be recorded as closed so no builder re-opens them:
    item 17 is overruled by **R17** (use `Explanation.other_contributions_count`;
    `ModelInfo.n_features` exists in BE §3.4.2 but is not the label source);
    item 18 is **confirmed** — BE §3.4.1 `Plant.demo_machine_id: str` and
    BE §3.6 `plants.<id>.demo_machine_id` both exist, so the plant floor
    deep-links `Plant.demo_machine_id` and never reads `GET /api/config` for it.
    *Fix:* move both into the "Closed" list with those resolutions, and retitle
    §7 so it has no open-questions section.

---

## Non-blocking suggestions

1. BE §5's parallelism table never names Phases 1–5 for backend tasks, while
   FE §2/§5 do. Add an explicit phase column to BE §5 so "Phase 2 parallel" is
   readable from the backend plan alone.
2. `reports/.gitkeep` is owned by T-SHAP but BE §2 has `.gitignore` ignoring
   `reports/**`. Add the `!reports/.gitkeep` negation to the T-INFRA note.
3. FE §2 says "`compose.yaml` references `web/Dockerfile`"; the file T-INFRA
   owns is `docker-compose.yml`. Use one spelling.
4. `models/.gitignore` (T-MODEL) and the root `.gitignore` rule
   `models/registry/**` (T-INFRA) encode the same rule in two files. Keep one.
5. BE `.coveragerc` omits `scripts/entrypoint_*.py` and `scripts/train.py`
   although `source = backend/xpm` already excludes everything under `scripts/`.
   Harmless, but it makes the R6 list look wider than it is — add a sentence
   saying the two `scripts/` entries are belt-and-braces.
6. FE §6.3 defines `offline` as "published no row for the current replay tick";
   BE defines it as no telemetry for `api.offline_after_seconds` (30 s
   wall-clock). Align FE's prose to the backend definition.
7. The per-Phase-4 e2e file (`web/e2e/<task-id>.spec.ts`, granted in FE §2's
   cross-task section) is not listed in the FE §2 ownership table, which says
   "one directory each". Add the file to the table for completeness.
8. `MachineSummary.risk_sparkline: list[float]` cannot express "not yet scored"
   while `probability` is `float | None`. Consider `list[float | None]` or state
   that the sparkline is simply shorter until warm.
9. BE §3.4.2 `AlertPage.limit` is absent from the FE listing; harmless, but FE
   paging code will want it.
10. FE §4.1's coverage targets (90/80) are stated per directory; add the
    aggregate `--coverage.thresholds` values to `vitest.config.ts` in the
    T-WEB-SHELL file list so the gate is enforced, not aspirational.

---

## Checks that passed

- **R10–R15** are correctly reflected in both plans (no resume; server-only
  heartbeat; `POST /api/replay/command` as the sole transport control;
  `replay.loop` + `run_id` minting with `replay.loop=false` in
  `docker-compose.e2e.yml`; required `caveat` + `demo_machine_id`; T-DOCS /
  T-WEB-E2E / T-PERF defined; contract artefact filenames and their
  committed/generated split).
- **R16 on the frontend side:** FE references no calibrated number anywhere; the
  single failure is on the backend (blocking 1).
- **R17 check 3a:** `ModelInfo.n_features` *is* in BE §3.4.2 and
  `Explanation.other_contributions_count` *is* in BE §3.4.3 — the backend side
  of R17 is satisfied; only the FE's label source is wrong (blocking 4).
- **R17 check 3b:** `Plant.demo_machine_id` is confirmed in BE §3.4.1 and
  `settings.yaml` §3.6 — the FE assumption holds.
- **File ownership:** no file is claimed by two tasks across both plans,
  including the new `T-DOCS` / `T-WEB-E2E` / `T-PERF` nodes and the moved
  `docs/LAB_REPORT.md` (T-DOCS) vs `nodered/README.md` + `docs/media/nodered-*.png`
  (T-NODERED). The only ownership gaps are blocking 15 (`tsx`) and blocking 16
  (`T-PERF`'s numbers).
- **Dependency graphs:** both are acyclic; the merged graph is acyclic; Phase 4
  web tasks depend only on `T-WEB-SHELL` + `make contracts` (blocking 14 is a
  missing edge into `T-WEB-SHELL`, not a cycle); Phase 5 is
  `T-WEB-E2E → T-PERF → T-DOCS` in both plans.
- **Test strategy** meets the bar: backend `--cov-fail-under=85` with an R6-sized
  omit list, component tests named for every interactive element, Playwright
  smoke (Phase 3), per-task specs (Phase 4), journey + perf (Phase 5).
- **Thresholds/percentiles/windows** live only in `config/settings.yaml`;
  `web/src/config.ts` holds UI-only constants (subject to blocking 12 for the
  few backend-owned values the FE still needs a path to).

NEEDS_WORK
