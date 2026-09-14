# Plan reconciliation review 5 — APPROVED

Convention: **BE** = `docs/plan/backend.md`, **FE** = `docs/plan/frontend.md`,
**review 4** = `docs/plan/reviews/plan-review-4.md`.

Minimal scope, as briefed: verify in the *plan text* only (a) review-4 blocking 1
— the BE §2 ADR register tail — and (b) review-4 non-blocking 1 — the FE §4.5
`setData` perf-budget row. Nothing else was re-reviewed; the findings of
review 4 on all other points stand unchanged.

## Verification

### 1. BE §2 ADR register tail — resolved

`grep -n "does not walk" docs/plan/backend.md` returns one hit, line 516. The
register tail (BE §2, lines 514–517) now reads:

> `ADR-028` is the highest number this plan allocates. The test in §4 asserts
> that `docs/DECISIONS.md` contains exactly `ADR-001` … `ADR-028` and that every
> ADR number cited in this register exists there; it does not walk
> `docs/plan/**` or `docs/plan/reviews/**`, which quote withdrawn identifiers.

The old "no other ADR number appears anywhere in `docs/**` or `docs/plan/**`"
clause is gone. The surviving statement is a both-directions claim over exactly
two inputs — `docs/DECISIONS.md` and this register — which is what BE §4's
**ADR-existence test, and its exact scope** (lines 2062–2073) specifies: same
two inputs, same `ADR-001 … ADR-028` set equality in both directions, `R1`…`R20`
titling, no-suffix check, and the same explicit non-walking of `docs/**`,
`docs/plan/**`, `docs/plan/reviews/**`. The two statements now agree, and the
§2 one is the weaker of the two (it omits the titling and suffix assertions),
so a builder reading either arrives at a test that passes on a clean checkout
despite `plan-review-2.md` quoting withdrawn suffixed identifiers verbatim.

Minor wording note, not a defect: §2 says "does not walk `docs/plan/**`" and
omits `docs/**`, while §4 rules out all three globs. §2 is a narrowing pointer,
not a competing normative scope, and it cannot be read as licensing a `docs/**`
walk, since the sentence already fixes the test's inputs to two named files.

### 2. FE §4.5 `setData` perf-budget row — resolved

`grep -n "setData" docs/plan/frontend.md` returns three hits; only line 1412 is
a budget. It now reads:

> | uPlot `setData` per chart | ≤ 1.5 ms; at most 7 charts (AI4I) or 4 (IMS,
> grouped) per §1.2, so ≤ 10.5 ms |

The "9 charts ≤ 9 ms" aggregate is gone; `grep -rn "9 charts" docs/plan/`
matches only `plan-review-4.md`, i.e. the historical record of the finding, and
no live plan text. The row is consistent with FE §1.2 lines 223–228, which
derive **7** for `ai4i` (all seven channels `vibration_like === false`, so all
ungrouped) and **4** for `ims` (six band energies collapse to one group chart;
the remaining three render per-channel). The aggregate is arithmetically
correct for the worst case: 7 × 1.5 ms = 10.5 ms, and the IMS stack of 4 is
strictly cheaper, so the single number bounds both datasets. T-PERF is now
measured against a chart count that can actually occur.

The other two `setData` mentions (FE line 1232, an instance-reuse assertion in
`T-WEB-MACHINE-DETAIL`; FE line 1759, the uPlot selection rationale, where
"9-channel sensor panel" describes channels, not charts) carry no budget and are
unaffected.

## Blocking issues

None.

## Non-blocking suggestions

1. Carry-over from review 4, non-blocking 2 and 3, both still open and both
   cosmetic: BE §3.2.3 restates the six band channel names that BE §3.1's table
   already pins (one drift surface), and FE §1.2's abstract slug example would
   read better with a parenthetical pointing at BE §3.1 for the concrete
   `g²/Hz` → `g-hz` derivation.
2. BE §2's tail could name `docs/**` alongside `docs/plan/**` for word-for-word
   parity with §4. Not blocking: the sentence already pins the test's inputs to
   two named files, so no wider glob can be inferred from it.

APPROVED
