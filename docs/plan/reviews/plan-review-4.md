# Plan reconciliation review 4 — NEEDS_WORK

Convention: **BE** = `docs/plan/backend.md`, **FE** = `docs/plan/frontend.md`,
**review 3** = `docs/plan/reviews/plan-review-3.md`.

Narrow scope, as briefed: verify in the *plan text* (not in the changelogs)
(1) review-3 blocking 1, (2) review-3 blocking 2 including the derived chart
counts, the fixture-derived FE test, the `g²/Hz` spelling and the ownership of
the two new files, (3) the scope of the ADR-existence test, (4) `make media`
and `scrubDatasetTsMs` consistency. Nothing else was re-reviewed.

## Verification

### 1. Review-3 blocking 1 — `risk_sparkline` — resolved

- FE §3.1 (line 644): `risk_sparkline: Array<number | null>;   // oldest first;
  LENGTH READ FROM PAYLOAD; null = not yet scored at that tick`. Byte-compatible
  with BE §3.4.1 (line 1031) `list[float | None]`, same "never padded with 0.0"
  semantics.
- FE §1.2 (lines 164–178) states the null rule: a `null` sample is a **gap** in
  the path, the same `NaN`-gap treatment as the telemetry ring buffer (§3.3),
  never `0`, never on the baseline, never interpolated; y-domain fixed `[0, 1]`;
  an all-`null` series renders the `Sparkline` empty state, not a flat line at 0.
  It also separates the health ring, which reads `probability` and shows the
  `—` "not yet scored" state — closing the obvious second way a builder could
  have leaked a `0`.
- FE §4.3 `T-WEB-PLANT-FLOOR` (lines 1219–1226) carries the assertion review 3
  asked for, and goes further than asked: leading-null gap (asserted on captured
  2-D-context draw calls, first plotted sample at the first non-null index, no
  coordinate at `y = 0` for a null index), interior-null splitting the path into
  two subpaths, all-null empty state, and the health ring in each case.

### 2. Review-3 blocking 2 — channel tables and grouping — resolved

- **BE §3.1** now carries two binding per-channel tables (AI4I 7 rows, IMS
  9 rows) with `name`, `display_name`, exact `unit`, `vibration_like`,
  `nominal_min`, `nominal_max`, declared to be the canonical order statement.
  Exact-character notes pin `N·m` (U+00B7) and `g²/Hz` (U+00B2, ASCII solidus,
  no space, no trailing `·Hz`), and `unit: ""` for the two dimensionless
  channels ("never `null`, never `-`, never `dimensionless`").
- **Counts check, done independently against FE §1.2's rule** (lines 207–234:
  `vibration_like === true` **and** identical `unit` ⇒ one chart; a group of one
  renders ungrouped). `ai4i`: all 7 rows `vibration_like: false` → 7 per-channel
  charts, and the three `K` channels correctly stay ungrouped because of the
  `vibration_like` conjunct. `ims`: six `g²/Hz` bands → one group;
  `vibration_rms` is `vibration_like: true, unit: "g"`, a group of one → renders
  ungrouped; `vibration_kurtosis` / `vibration_crest` are `false` → per-channel.
  Total 4. Both numbers match what BE §3.1 and FE §1.2 state.
- **Slug check.** BE's `_unit_slug` (`re.sub(r"[^a-z0-9]+", "-", unit.lower())
  .strip("-")`) and FE §1.2 / §4.2's word-for-word identical transform both map
  `"g²/Hz"` → `g-hz`, so BE §4's literal `telemetry-chart-group-g-hz` and FE's
  derived selector agree. The group y-domain `0.0 … 0.05` is `max(nominal_max)`
  over the six band rows. Correct.
- **BE §4's `_chart_ids` mirror is sound.** `groups[c.unit]` is only indexed
  under `c.vibration_like`, so the two `unit: ""` channels never raise; the
  ordered expectation `[group-g-hz, vibration_rms, vibration_kurtosis,
  vibration_crest]` is what the rule produces. It also asserts no
  `vibration_like` channel carries `unit == ""`, which keeps the empty string
  out of `unitSlug`.
- **FE derives, does not restate.** FE §4.2 (lines 1147–1152) drops the slug
  literal and says plainly that no slug literal appears in the plan, in
  `web/src/`, or in any selector. FE §4.3 (lines 1235–1251) takes the `ai4i` and
  `ims` `ChannelSpec[]` fixtures verbatim from `contracts/openapi.json`,
  *computes* the expected chart-id set by applying the §1.2 rule, and asserts
  set equality plus per-group y-domains — with three anti-tautology guards
  (`ims` ≥ 1 group of ≥ 2 members, `ai4i` zero groups, and a hand-built
  different-`unit` negative case). FE §1.2 labels 7 / 4 a *consequence* of the
  BE table, and FE §7 item 16 is a pointer. `formatUnit`'s property test reads
  the unit list from the fixture, so no unit literal survives in FE.
- **`g²/Hz` consistently.** BE §3.2.3 (lines 790–798) replaces `g²/Hz·Hz` with a
  physical definition — band-mean PSD, `∫PSD dHz` ÷ band width — that makes
  `g²/Hz` the correct unit, states the user-visible `ChannelSpec.unit` is
  exactly `g²/Hz`, and explicitly withdraws the old spelling. `g²/Hz·Hz` no
  longer appears anywhere outside the §9 changelog's description of its own
  withdrawal. The two prose examples at BE lines 1766 and 1789 already use
  `g²/Hz`.
- **Ownership.** `backend/xpm/contracts/channels.py` (BE line 205) and
  `tests/contracts/test_channel_specs.py` (BE line 214) appear in exactly one
  file-ownership block, **T-CONTRACTS**, and nowhere else in either plan. BE
  states channels.py is the only place the 16 rows are written down and that
  `xpm.api` / `xpm.data` import it rather than re-declaring. No new file
  collision, and no change to the dependency graph is implied (T-CONTRACTS is
  already upstream of both).
- **FE `ChannelSpec` type** (FE lines 625–633) matches BE's model field for
  field and documents `"" = dimensionless, prints bare`, with the exact strings
  marked backend-owned.

### 3. ADR-existence test scope — see blocking 1

BE §4 (lines 2062–2072) is correct: exactly two inputs, both directions,
R1–R20 titling, no-suffix check, and an explicit statement that it does **not**
walk `docs/**`, `docs/plan/**` or `docs/plan/reviews/**`. But a second,
contradicting statement of the same test survives in BE §2 — blocking 1 below.

### 4. `make media` and `scrubDatasetTsMs` — resolved

- Every occurrence of the invocation in both plans is now
  `pnpm -C web exec tsx ../scripts/capture_media.ts` (BE lines 543, 566, 571;
  FE §2 pre-declaration table line 458). BE §2.2 (lines 571–575) states it once
  as the authority, explains the parent-relative argument, and declares any
  other spelling superseded. No bare `scripts/capture_media.ts` survives as an
  invocation argument; BE line 431 and 464 are the *path* of the file, which is
  correct. BE §2 T-DOCS (line 464) now calls it "a plain Node/TypeScript script
  run by `tsx`", with `playwright test` ruled out.
- `scrubDatasetTs` no longer appears. The only spelling in FE is
  `scrubDatasetTsMs` (§1.2 line 274, §3.3 store schema line 983, §4.3
  line 1304).

---

## Blocking issues

1. **BE §2, ADR register tail (lines 514–516) contradicts BE §4's re-scoped
   ADR-existence test.** §4 now says the test reads exactly `docs/DECISIONS.md`
   and the §2 register and does **not** walk `docs/**` or `docs/plan/**`. The
   closing sentence of the §2 register still says the opposite: "The test in §4
   asserts that `docs/DECISIONS.md` contains exactly `ADR-001` … `ADR-028` and
   that **no other ADR number appears anywhere in `docs/**` or
   `docs/plan/**`**." A builder implementing T-DOCS from §2 writes the wide
   glob, and that test fails on a clean checkout for exactly the reason
   review-3 non-blocking 1 gave: `docs/plan/reviews/plan-review-2.md` quotes the
   withdrawn suffixed ADR identifiers verbatim as historical record. Two
   normative statements of one test's scope must not disagree.
   *Fix (BE only, one sentence):* replace that sentence with a pointer, e.g.
   "The test in §4 asserts that `docs/DECISIONS.md` contains exactly `ADR-001` …
   `ADR-028` and matches this register in both directions; its scope is exactly
   those two inputs — see §4, **docs**."

## Non-blocking suggestions

1. Carry-over, review-3 non-blocking 5, still open and acknowledged as
   out-of-round in FE §10: FE §4.5's budget table (line 1412) still reads
   "uPlot `setData` per channel chart | ≤ 1.5 ms; 9 charts ≤ 9 ms". Under the
   grouping rule IMS renders 4 telemetry charts, so the aggregate is stale.
   Restate per chart instance (e.g. "≤ 1.5 ms per instance; ≤ 6 ms for the
   worst-case stack") so T-PERF is not measured against a chart count that
   cannot occur.
2. BE §3.1's per-channel tables are now the canonical-order statement *and*
   BE §3.2.3 separately lists "Bands and channel names (exact, user-visible)".
   Two lists of the same six names is one drift surface; consider making §3.2.3
   cite §3.1's table for the names and keep only the Hz band edges.
3. FE §1.2's abstract slug example (`"A/B²"` → `a-b`) is good de-literalisation,
   but a reader checking the rule against reality has to do the `g²/Hz`
   derivation in their head. A parenthetical "(BE §3.1 works the concrete case
   through)" would cost nothing and save that step.

NEEDS_WORK
