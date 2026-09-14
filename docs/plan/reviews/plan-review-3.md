# Plan reconciliation review 3 — NEEDS_WORK

Convention: **BE** = `docs/plan/backend.md`, **FE** = `docs/plan/frontend.md`,
**R\*** = `docs/plan/orchestrator-rulings.md`, **item N** = the numbered blocking
item in `docs/plan/reviews/plan-review-2.md`.

Scope of this round, as briefed: (a) verify each of review 2's 17 blocking items
against the *text* of the plan it names (both sides for 12, 14, 15, 16);
(b) a final field-by-field diff of BE §3.4/§3.5 against FE §3.1/§3.2/§3.3;
(c) confirm R16 and R19. Prose and style are not reopened.

## Verification of review 2's 17 blocking items

All 17 are resolved in the revised text (checked in the plans, not in the
changelogs):

| Item | Where verified | Verdict |
|---|---|---|
| 1 (calibrator, R16) | BE §0 row (line 43), §1 (`fits no post-hoc calibrator`), §3.4.3 one-probability bullet, §3.6 (`there is no calibration key`), §3.7 (`neither family ships a calibrator.joblib`), §4 (grep test for `sklearn.calibration`), §6 R16 entry. Risk 3 is gone. `model.evaluation.calibration_bins` retained as the diagnostic | resolved |
| 2 (R16/R17 recorded) | BE header line 18 (R1–R20), §2 ADR register, §4 ADR test, §6 entries for R16–R20 | resolved |
| 3 (ADR collisions) | BE §2 ADR register; ADR-001…ADR-020 = R1…R20, ADR-021…ADR-028 non-ruling. Machine check: every `ADR-\d+` token in BE is in 001–028, no suffixed token, no number carrying two decisions | resolved |
| 4 (roll-up label, R17) | FE §3.1 (`GET /api/models` row no longer claims it), §3.1.1 (`other_contributions_count` + `n_features` added; derivation rewritten), §4.3 shap-viz, §7 item 17 | resolved |
| 5 (`ModelInfo.kind`) | FE §3.1 table row and type block both now `family: "lgbm" \| "rf"`, with the "not unified with `Explanation.model_kind`" note | resolved |
| 6 (`snapshot`) | FE §3.2 row now byte-matches BE §3.5, incl. `run_id` and `MachineSnapshot = MachineSummary & {values}`; no top-level `values` | resolved |
| 7 (`risk` frame) | FE §3.2 `risk` row is `{type, plant_id, ts, updates}`, explicitly "no top-level `dataset_ts`"; `plant_id` added to `telemetry` | resolved |
| 8 (`WhatIfResponse`) | FE §3.3 block now carries `model_kind`, `other_contributions_count`, `n_features`, `provisional`, `caveat`; shared subset extended | resolved |
| 9 (`Alert`) | FE §3.1 has `machine_display_name` + `closed_dataset_ts`; §4.3 alert-feed asserts the announcement uses `machine_display_name` | resolved |
| 10 (`HealthResponse`) | FE §3.1 `run_id: string \| null`, `replay: ReplayState \| null`; §4.4 gate polls on `status === "ok"` **and** `run_id !== null` | resolved |
| 11 (`ReplayCommand.speed`) | BE §3.4.2 `speed: Literal[0.5, 1.0, 5.0, 20.0] \| None`; §3.3 rationale; §3.6 "contract change"; §4 test that the literal set equals `replay.allowed_speeds` | resolved |
| 12 (`ConfigResponse.values`) | BE §3.4.2 full-flattened-tree paragraph + 14-key guaranteed table (both sides of the 2.5× factor named); FE §1.1 derives `WS_SILENCE_TIMEOUT_MS`, `WS_SILENCE_FACTOR = 2.5` is the only constant; FE §4.3 fixture with `ws_ping_seconds = 4` → 10 000 ms | resolved both sides |
| 13 (chart granularity) | FE §1.2 grouping rule is binding, §4.2 defines `telemetry-chart-group-{unit-slug}` + `telemetry-series-{channel_name}`, §4.3 asserts 7 / 4 / negative case, §7 item 16 is a pointer | resolved in FE; see **blocking 2** for the backend input it needs |
| 14 (`GEN --> SHELL`) | FE §5 graph edge present and the SHELL node relabelled; BE §5 `T-WEB-*` row mirrors it | resolved both sides |
| 15 (`tsx`) | FE §2 four-package pre-declaration table; BE §2.1 "T-DOCS must not add a devDependency"; R18 fork recorded on both sides | resolved both sides |
| 16 (`T-PERF` numbers) | FE §4.5 → T-PERF report → T-DOCS → `README.md` + `docs/FINAL_REVIEW.md`; BE §2 T-DOCS responsibility added, T-MODEL note restates the `EVALUATION.md` exclusion | resolved both sides |
| 17 (FE open questions) | FE §7 retitled, opening line states there are none; items 17 and 18 recorded as closed | resolved |

## R16 and R19

- **R16 — confirmed.** No calibrator survives anywhere in either serving path.
  BE mentions calibration only as an evaluation diagnostic (reliability curve,
  Brier, ECE over `model.evaluation.calibration_bins`) and adds a grep test over
  `backend/xpm/pipeline/` for `sklearn.calibration`. FE contains no
  calibration-related string at all. `Alert.probability`,
  `RiskUpdate.probability`, `Explanation.probability`, `Explanation.output_value`
  and `WhatIfResponse.probability` are one number.
- **R19 — confirmed.** One register, BE §2. ADR-001…ADR-020 ↔ R1…R20,
  ADR-021…ADR-028 for non-ruling decisions; every in-text citation in BE §0,
  §3.2.3, §3.3, §6 points inside that range; FE cites no ADR number at all, so
  it cannot drift. (One scoping defect in the *test* for this — non-blocking 1.)

---

## Blocking issues

1. **BE §3.4.1 vs FE §3.1 — `MachineSummary.risk_sparkline` nullability now
   disagrees.** BE adopted review-2 non-blocking 8 and changed the field to
   `risk_sparkline: list[float | None]` ("null entries = ticks the machine was
   not yet scored for … never padded with 0.0"). FE §3.1 still declares
   `risk_sparkline: number[]`, and FE §1.2 / §4.3 describe the sparkline as a
   plain series whose only variable is its length (the fixture case is "30 points
   rather than 60"). The generated `api.ts` will type the field
   `(number | null)[]`, so the FE tile code written from the FE plan does not
   typecheck against the contract, and — worse — the plan gives the sparkline
   renderer no null rule, while FE's own convention (§3, `null` never renders as
   `0`) forbids the obvious fallback.
   *Fix (FE only):* in FE §3.1 change the field to
   `risk_sparkline: Array<number | null>;   // oldest first; LENGTH READ FROM PAYLOAD; null = not yet scored`,
   add one sentence to FE §1.2 stating that a `null` entry renders as a gap in
   the sparkline path (same `NaN`-gap treatment as the telemetry ring buffer,
   never a zero, never an interpolated segment), and add a `T-WEB-PLANT-FLOOR`
   assertion in FE §4.3: "a fixture whose `risk_sparkline` contains leading
   `null`s renders a gap, not a baseline at 0".

2. **BE §3.1 / §3.2.3 vs FE §1.2, §4.2, §4.3 — FE's binding chart-grouping rule
   and its testid depend on two backend-owned values BE never pins:
   per-channel `vibration_like`, and the exact `ChannelSpec.unit` strings.**
   FE §1.2 makes grouping binding on `vibration_like === true` **and** an
   identical `unit`, fixes the testid as `telemetry-chart-group-{unit-slug}`
   derived from the unit string, and states as fact that `ai4i` renders 7 charts
   ("all `vibration_like === false`") and `ims` renders 4 ("six band energies
   sharing `unit === "g²/Hz"` plus three others"), with the literal testid
   `telemetry-chart-group-g-hz` in §4.2 and §4.3. BE defines
   `ChannelSpec.vibration_like: bool` but never says which channels get `true`,
   and gives units only in prose: §3.1 says `vibration_*khz` are `g²/Hz` while
   §3.2.3 calls the band energy `g²/Hz·Hz`, and `vibration_kurtosis` /
   `vibration_crest` are described as "dimensionless" with no statement of what
   string (or empty string) `unit` actually carries. Two concrete divergences
   follow: (a) if the backend builder sets `vibration_like = true` for
   `vibration_rms` / `_kurtosis` / `_crest` and gives kurtosis and crest the same
   unit string, IMS renders **3** charts, not the 4 the FE plan and its tests
   assert; (b) if the emitted unit is `"g²/Hz·Hz"` the testid becomes
   `telemetry-chart-group-g-hz-hz` and every FE selector and e2e query built from
   §4.2 misses.
   *Fix (BE only):* in BE §3.1, replace the prose unit list with an explicit
   per-channel table giving, for all 7 AI4I and all 9 IMS channels, the exact
   `unit` string and the `vibration_like` value — specifically: the six
   `vibration_*khz` band energies are `vibration_like: true`, `unit: "g²/Hz"`
   (one spelling; amend §3.2.3's `g²/Hz·Hz` to match or state plainly that the
   user-visible `unit` is `"g²/Hz"`); `vibration_rms` is
   `vibration_like: true, unit: "g"`; `vibration_kurtosis` and `vibration_crest`
   are `vibration_like: false` with `unit: ""` (and state that an empty `unit`
   prints a bare number, which FE §1.1's `formatUnit` already does for `null`);
   all seven AI4I channels are `vibration_like: false`. Add the corresponding
   assertion to BE §4's contract tests ("`Plant.channels` for `ims` yields
   exactly one group under the frontend's rule"). No FE edit is required if BE
   pins these values; if BE prefers different values, FE §1.2/§4.2/§4.3's chart
   counts and the `g-hz` slug must change with them.

---

## Non-blocking suggestions

1. **BE §4 "docs" — the ADR-existence test cannot pass as scoped.** It asserts
   that "no ADR number outside that range may appear anywhere in `docs/**` or
   `docs/plan/**`" and that "no suffixed ADR identifier … exists anywhere". The
   historical review files under `docs/plan/reviews/` quote the old suffixed
   identifiers verbatim (that is what review 2 item 3 was reporting), so the test
   fails on a clean checkout. Scope it to `docs/DECISIONS.md` plus the BE §2
   register, or exclude `docs/plan/reviews/**` explicitly.
2. `make media` argument path differs between plans: BE §2.1/§2.2 has
   `pnpm -C web exec tsx ../scripts/capture_media.ts` (correct, since `-C web`
   makes `web/` the cwd and the script lives at repo root), FE §2's
   pre-declaration table copies R18's `… tsx scripts/capture_media.ts`. The
   Makefile is T-INFRA's, so align FE's table to `../scripts/capture_media.ts`.
3. BE §2 T-DOCS calls `scripts/capture_media.ts` "a Playwright script" while R18
   and FE §2 fix it as a `tsx`-run script (using the Playwright library, not the
   test runner). One clarifying clause in BE would stop a builder reaching for
   `playwright test`.
4. FE §1.2 (playback) writes `playback.scrubDatasetTs`; the store schema in
   FE §3.3 defines `scrubDatasetTsMs`. Same field, two spellings.
5. FE §4.5's per-component budget row "uPlot `setData` per channel chart … 9
   charts ≤ 9 ms" predates the grouping rule; IMS now renders 4 telemetry charts.
   Restate the budget per chart instance.
6. BE §3.4.2's guaranteed-key table assigns `alerting.probability_threshold` and
   `alerting.watch_threshold` the job of drawing the alert/watch lines on the
   risk chart, but FE §3.1's list of keys it reads omits both and FE's
   `RiskTimeline` spec draws no threshold lines. Decide one: either FE renders
   them (and lists the keys) or BE drops the claim from the "Frontend use"
   column.
7. Field omissions in the FE listings that are harmless under the
   ignore-unknown-fields rule, but which the generated types will carry and FE
   builders may want: `TelemetrySeries.plant_id/n_points/max_points/downsampled`,
   `RiskSeries.model_id/status/n_points/downsampled`, `PlantSnapshot.run_id`,
   `AlertPage.limit`, `HealthResponse.version/db_ok/mqtt_connected/uptime_seconds`,
   `FeatureDisagreement.lgbm_rank/rf_rank`, `ReplayCommand.schema_version/seed/plant_id`
   (all defaulted or optional server-side, so nothing breaks).

## Checks that passed

- **Full field diff, BE §3.4/§3.5 ↔ FE §3.1/§3.2/§3.3.** `Plant`,
  `ChannelSpec`, `MachineSummary` (except blocking 1), `MachineDetail`,
  `AlertMarker`, `Alert`, `GlobalImportance`, `ModelComparison`,
  `FeatureDisagreement`, `ModelInfo`, `PlantSnapshot`, `Explanation`,
  `SentenceSpan`, `ShapContribution`, `WhatIfRequest`/`WhatIfResponse`,
  `HealthResponse`, `ReplayCommand` and `ReplayState` agree on every shared field
  name, type, nullability and enum literal. Enum literals match exactly:
  `plant_id` ∈ {ai4i, ims}; `status` ∈ {healthy, watch, alert, offline};
  `severity` ∈ {medium, high, critical}; `shap_space` = "probability" (closed);
  `framing` ∈ {percentile, threshold, trend, consecutive}; `direction` ∈ {up, down};
  `model_kind` / `ModelInfo.family` ∈ {lgbm, rf} (deliberately un-unified);
  `command` ∈ {play, pause, set_speed, seek, restart}.
- **WS frames.** All nine server frame shapes and the single client `pong` match
  one-for-one, including `hello`, the corrected `snapshot` and `risk`, the
  spread frames (`alert`, `explanation`, `replay_state`, `config`), `ping` and
  `error` (`request_id: string | null`). Positional `values[]` semantics, the
  `api.ws_flush_ms` batching and the drop-oldest backpressure rules are stated
  identically on both sides.
- **REST paths and query params.** All 17 rows of BE §3.4's table appear in
  FE §3.1 with identical paths, methods and query-parameter names; the bare-list
  vs `AlertPage`-envelope split is stated the same way in both.
- **Testids embedding backend values** (FE §4.2): `machine-tile-{machine_id}`,
  `alert-card-{alert_id}` and `risk-alert-marker-{alert_id}` match BE §3.1's id
  regexes; `playback-speed-{0.5|1|5|20}` matches `replay.allowed_speeds` under
  `String(speed)`; `alert-severity-{medium|high|critical}` and the tile status
  treatments match the two separated enums; `telemetry-chart-{channel_name}`,
  `shap-bar-{feature}`, `explanation-link-{feature}`, `whatif-slider-{feature}`
  and `compare-delta-{feature}` use backend names verbatim;
  `compare-prob-lgbm`/`-rf` match the family literals. The only testid with an
  unpinned backend input is `telemetry-chart-group-{unit-slug}` (blocking 2).
- **Config as the single home for thresholds/windows/percentiles.** All 14
  frontend-consumed keys are guaranteed present on `ConfigResponse.values` and
  defaulted identically in BE §3.6; `web/src/config.ts` holds only UI constants,
  and `WS_SILENCE_TIMEOUT_MS` is now derived rather than literal.
- **Task ids (R9), file ownership, dependency graph.** Both plans use the
  canonical `T-*` / `T-WEB-*` ids. No file is claimed by two tasks, including
  `web/package.json` (T-WEB-SHELL only), `scripts/capture_media.ts` (T-DOCS),
  the per-Phase-4 `web/e2e/t-web-*.spec.ts` files and the two Phase-5 specs.
  Both graphs are acyclic and the merged graph is acyclic; `GEN --> SHELL` is
  present on both sides; Phase 4 is genuinely parallel; Phase 5 is
  `T-WEB-E2E → T-PERF → T-DOCS` in both plans.
- **Test strategy** still meets the bar: backend `--cov-fail-under=85` with the
  R6 omit list, enforced frontend `coverage.thresholds` in `vitest.config.ts`,
  a component test named for every interactive element, Playwright smoke /
  per-task / journey / perf.

NEEDS_WORK
