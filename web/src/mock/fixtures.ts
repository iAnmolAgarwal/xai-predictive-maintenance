/**
 * The fixture barrel. `@/mock/fixtures` is the only import path the rest of the
 * test suite uses, so the fixtures can be split by concern without every test
 * following the refactor:
 *
 * - `core`     plants, channels, the seeded PRNG, the dataset clock, the
 *              settings tree and the mutable replay/config state
 * - `catalog`  the feature catalogue and its framing metadata
 * - `explain`  clause grammar, explanations, comparisons, what-if
 * - `alerts`   the 63-alert corpus with filtering and cursor paging
 * - `machines` live scalars, sparklines, snapshot rows
 * - `series`   columnar telemetry/risk, beeswarm, `state_at`, model registry
 *
 * This module graph is mock-only and must never reach a production bundle; the
 * `MOCK_MARKER` re-exported here is what `no-mock-in-prod` greps for.
 */
export * from './core';
export * from './catalog';
export * from './explain';
export * from './alerts';
export * from './machines';
export * from './series';
