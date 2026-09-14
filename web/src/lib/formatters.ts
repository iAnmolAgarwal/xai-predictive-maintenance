/**
 * Pure rendering helpers. No domain knowledge beyond the contract field they
 * format, and — critically — no unit table: `ChannelSpec.unit` and
 * `ShapContribution.unit` are printed verbatim (frontend.md §1.1).
 */

/** U+2009 THIN SPACE: separates a number from its unit without a full space. */
const THIN_SPACE = ' ';

/**
 * Render a value with the backend's unit string verbatim. `null` (a
 * dimensionless SHAP feature) and `""` (a dimensionless channel) both print the
 * bare number. No conversion, no re-mapping, ever.
 */
export function formatUnit(value: number | null, unit: string | null): string {
  const shown = value === null || Number.isNaN(value) ? '—' : formatNumber(value);
  if (unit === null || unit === '') return shown;
  return `${shown}${THIN_SPACE}${unit}`;
}

/** Instrument-panel number formatting: enough precision to be useful, no jitter. */
export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return '—';
  const magnitude = Math.abs(value);
  if (magnitude === 0) return '0';
  if (magnitude >= 1000) return value.toFixed(0);
  if (magnitude >= 10) return value.toFixed(1);
  if (magnitude >= 1) return value.toFixed(2);
  if (magnitude >= 0.001) return value.toFixed(3);
  return value.toExponential(2);
}

/** `1 → "1 h"`, `4 → "4 h"`, `24 → "24 h"`, `null → ""` — the only mapping. */
export function formatWindow(windowHours: number | null): string {
  return windowHours === null ? '' : `${windowHours}${THIN_SPACE}h`;
}

/** The waterfall roll-up label, read off the payload being drawn (R17). */
export function formatOtherFeatures(count: number): string {
  return count === 1 ? '1 other feature' : `${count} other features`;
}

/** Probabilities are `[0,1]` on the wire and percentages only at render time. */
export function formatProbability(probability: number | null): string {
  if (probability === null || !Number.isFinite(probability)) return '—';
  return `${(probability * 100).toFixed(0)}%`;
}

/** Signed contribution string with an explicit sign, for waterfall value slots. */
export function formatSigned(value: number, digits = 2): string {
  if (!Number.isFinite(value)) return '—';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${Math.abs(value).toFixed(digits)}`;
}

/** `0-100` within the machine's own history; `null` omits the row entirely. */
export function formatPercentile(percentile: number | null): string | null {
  if (percentile === null || !Number.isFinite(percentile)) return null;
  return `${percentile.toFixed(0)}th percentile`;
}

/**
 * Dataset time is the displayed time everywhere (R8). Rendered in UTC so the
 * same replay reads identically on every machine.
 */
export function formatDatasetTime(datasetTsMs: number | null): string {
  if (datasetTsMs === null || !Number.isFinite(datasetTsMs)) return '—';
  const d = new Date(datasetTsMs);
  const pad = (n: number): string => String(n).padStart(2, '0');
  return (
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ` +
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`
  );
}

/** Clock-only form for dense readouts (alert cards, tile footers). */
export function formatDatasetClock(datasetTsMs: number | null): string {
  const full = formatDatasetTime(datasetTsMs);
  return full === '—' ? full : full.slice(11, 16);
}

/**
 * ISO-8601 → epoch milliseconds, done once at decode time. Nothing downstream
 * re-parses a timestamp string.
 */
export function parseDatasetTs(iso: string | null): number {
  if (iso === null) return Number.NaN;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? Number.NaN : ms;
}

/**
 * Slug of a backend unit string: lowercased, runs of non-`[a-z0-9]` collapsed to
 * a single `-`, trimmed. The single implementation of the transform; no slug
 * literal exists anywhere in `web/src/` (frontend.md §1.2).
 */
export function unitSlug(unit: string): string {
  return unit
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}
