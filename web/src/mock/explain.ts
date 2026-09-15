/**
 * Explanations, model comparisons and what-if recomputation.
 *
 * The sentences follow the template grammar in backend.md §3.9 literally: one
 * template per framing × direction, `{display}` is the SOURCE CHANNEL's display
 * name (not the feature's), the final sentence composes the top
 * `explanation.max_sentence_features` (2) clauses with `", and "`, and each
 * clause's opening `{display}` is recorded as a `SentenceSpan`. Two features off
 * the same channel therefore open with the same words, which is exactly why the
 * spans are character offsets and not string matches.
 *
 * Every explanation closes by construction: `other_contributions_shap` is
 * computed as `probability - base_value - Σ shap`, so
 * `base + Σ shap + other == output_value == probability` to the last bit.
 */
import type {
  Alert,
  Explanation,
  FeatureDisagreement,
  ModelComparison,
  ModelKind,
  PlantId,
  SentenceSpan,
  ShapContribution,
  WhatIfRequest,
  WhatIfResponse,
} from '@/contracts';
import { catalogFor, featureMeta, pinnedFor, type FeatureMeta } from './catalog';
import {
  CAVEAT,
  channelSpec,
  DEMO_ALERT_ID,
  DEMO_EXPLANATION_ID,
  demoMachineId,
  hexId,
  IMS_DEMO_ALERT_ID,
  MAX_SENTENCE_FEATURES,
  MODEL_ID,
  N_FEATURES,
  RF_MODEL_ID,
  SLOPE_ZERO_EPS,
  seededRandom,
  TOP_K,
  TOP_K_WHATIF,
} from './core';

/** Background mean predicted probability per model family, probability space. */
export const LGBM_BASE_VALUE = 0.0824;
export const RF_BASE_VALUE = 0.0917;

/** Share of the base→probability gap carried by the top-k of a generated alert. */
const TOP_K_SHARE = 0.92;

/**
 * Rescale a top-k to carry `TOP_K_SHARE` of the base→probability gap in TOTAL
 * MAGNITUDE. Scaling by the signed sum (as an earlier version did) makes the
 * factor negative whenever the down-features outweigh the up-features, which
 * silently inverts every sign in the explanation; dividing by Σ|shap| and taking
 * the gap's magnitude leaves each contribution's sign exactly where the feature's
 * declared direction put it. The residual goes to `other_contributions_shap`, so
 * the waterfall still closes to the last bit.
 */
function rescale(entries: Weighted[], base: number, probability: number): Weighted[] {
  const magnitude = entries.reduce((sum, entry) => sum + Math.abs(entry.shap), 0);
  if (magnitude === 0) return entries.map((entry) => ({ meta: entry.meta, shap: 0 }));
  const scale = (Math.abs(probability - base) * TOP_K_SHARE) / magnitude;
  return entries.map((entry) => ({ meta: entry.meta, shap: entry.shap * scale }));
}

/* ── Number and clause rendering ───────────────────────────────────────────── */

function trimZeros(rendered: string): string {
  return rendered.includes('.') ? rendered.replace(/\.?0+$/, '') : rendered;
}

/** Thousands separators without `Intl`, so the rendering is locale-independent. */
function group(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/**
 * `backend/xpm/explain/templates.py:format_number` rendered in TypeScript: comma
 * grouping at 1000, two decimals above 1, and three SIGNIFICANT digits below it
 * so a band energy prints `0.0004 g²/Hz` rather than collapsing to `0`. Trailing
 * zeros are trimmed and scientific notation is never produced, so every value in
 * the catalogue renders identically forever.
 */
export function formatNumber(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1000) return group(value.toFixed(0));
  if (abs >= 1) return trimZeros(value.toFixed(2));
  if (abs === 0) return '0';
  return trimZeros(value.toPrecision(3));
}

function withUnit(value: number, unit: string | null): string {
  return unit === null || unit === ''
    ? formatNumber(value)
    : `${formatNumber(value)} ${unit}`;
}

function ordinal(value: number): string {
  const n = Math.round(value);
  const tens = n % 100;
  if (tens >= 11 && tens <= 13) return `${n}th`;
  const suffix = ['th', 'st', 'nd', 'rd'][n % 10] ?? 'th';
  return `${n}${suffix}`;
}

function humanWindow(hours: number | null): string {
  if (hours === null) return 'hour';
  return hours === 1 ? '1 hour' : `${hours} hours`;
}

/**
 * Percent of the window mean per hour, falling back to absolute channel units per
 * hour when the window mean is zero or too close to it (backend.md §3.9). The
 * fallback exists so a zero-mean window can never divide by zero or print `inf`.
 */
function renderRate(meta: FeatureMeta): string {
  const magnitude = Math.abs(meta.rate_per_hour);
  const sign = meta.direction === 'down' ? '-' : '+';
  if (Math.abs(meta.window_mean) > SLOPE_ZERO_EPS) {
    return `${sign}${formatNumber((100 * magnitude) / Math.abs(meta.window_mean))}% per hour`;
  }
  return `${sign}${withUnit(magnitude, meta.unit)} per hour`;
}

/** The rendered clause for one contribution — `ShapContribution.sentence`. */
export function renderClause(plantId: PlantId, meta: FeatureMeta): string {
  const display = channelSpec(plantId, meta.channel)?.display_name ?? meta.display_name;
  const window = humanWindow(meta.window_hours);
  const value = meta.value === null ? '—' : withUnit(meta.value, meta.unit);
  const up = meta.direction === 'up';

  switch (meta.framing) {
    case 'percentile':
      // No rank yet (too little history): the clause drops the percentile phrase
      // rather than inventing a median, which `?? 50` would have rendered.
      if (meta.percentile === null)
        return up
          ? `${display} over the last ${window} sat at ${value}, with no rank over this machine's own history yet`
          : `${display} over the last ${window} fell to ${value}, with no rank over this machine's own history yet`;
      return up
        ? `${display} over the last ${window} sat at the ${ordinal(meta.percentile)} percentile of this machine's own history (${value})`
        : `${display} over the last ${window} fell to the ${ordinal(meta.percentile)} percentile of this machine's own history (${value})`;
    case 'consecutive':
      return up
        ? `${display} stayed above its ${meta.streak_percentile}th percentile for ${formatNumber(meta.consecutive_hours ?? 0)} consecutive hours (peaking at ${value})`
        : `${display} stayed below its ${meta.streak_percentile}th percentile for ${formatNumber(meta.consecutive_hours ?? 0)} consecutive hours (bottoming at ${value})`;
    case 'trend':
      return up
        ? `${display} has been climbing at ${renderRate(meta)} over the last ${window}`
        : `${display} has been falling at ${renderRate(meta)} over the last ${window}`;
    case 'threshold':
      return up
        ? `${display} reached ${value}, above the ${withUnit(meta.threshold ?? 0, meta.unit)} normal ceiling`
        : `${display} dropped to ${value}, below the ${withUnit(meta.threshold ?? 0, meta.unit)} normal floor`;
  }
}

/** The character length of the clause's opening `{display}`, for its span. */
function displayLength(plantId: PlantId, meta: FeatureMeta): number {
  return (channelSpec(plantId, meta.channel)?.display_name ?? meta.display_name).length;
}

/**
 * R24: `ShapContribution.direction` is the SIGN of the SHAP value — it drives the
 * ▲/▼ glyph and the side of the force plot, and the waterfall bar's side comes
 * from `shap` itself, so the two can never be allowed to disagree. The clause
 * wording keeps using the feature's own declared direction, which R24 allows to
 * differ.
 */
export function directionOf(shap: number): ShapContribution['direction'] {
  return shap >= 0 ? 'up' : 'down';
}

function toContribution(
  plantId: PlantId,
  meta: FeatureMeta,
  shap: number,
): ShapContribution {
  return {
    feature: meta.feature,
    display_name: meta.display_name,
    shap,
    value: meta.value,
    unit: meta.unit,
    percentile: meta.percentile,
    window_hours: meta.window_hours,
    stat: meta.stat,
    framing: meta.framing,
    consecutive_hours: meta.consecutive_hours,
    threshold: meta.threshold,
    direction: directionOf(shap),
    sentence: renderClause(plantId, meta),
  };
}

/* ── Sentence composition ──────────────────────────────────────────────────── */

type Composed = { sentence: string; sentence_spans: SentenceSpan[]; headline: string };

/**
 * `"{machine} was flagged at {p:.0%} risk because {clause_1}, and {clause_2}."`
 * Spans are the offsets of each clause's opening `{display}` inside that string.
 */
export function composeSentence(
  plantId: PlantId,
  machineDisplay: string,
  probability: number,
  metas: FeatureMeta[],
): Composed {
  const used = metas.slice(0, MAX_SENTENCE_FEATURES);
  const prefix = `${machineDisplay} was flagged at ${Math.round(probability * 100)}% risk because `;
  const clauses = used.map((meta) => renderClause(plantId, meta));

  let cursor = prefix.length;
  const spans: SentenceSpan[] = [];
  for (const [index, clause] of clauses.entries()) {
    const meta = used[index];
    if (meta)
      spans.push({
        start: cursor,
        end: cursor + displayLength(plantId, meta),
        feature: meta.feature,
      });
    cursor += clause.length + ', and '.length;
  }

  const first = clauses[0] ?? '';
  return {
    sentence: `${prefix}${clauses.join(', and ')}.`,
    sentence_spans: spans,
    headline: `${first.charAt(0).toUpperCase()}${first.slice(1)}.`,
  };
}

/* ── Contribution selection ────────────────────────────────────────────────── */

/**
 * Every alert the plant's demo machine raises is explained with the pinned
 * feature set, so the demo machine always tells the same story (and its
 * `top_feature` is stable); only the headline alert keeps the pinned SHAP
 * magnitudes verbatim, the rest are rescaled to their own probability.
 */
export function usesPinnedFeatures(alert: Alert): boolean {
  return alert.machine_id === demoMachineId(alert.plant_id);
}

export function isHeadlineAlert(alertId: string): boolean {
  return alertId === DEMO_ALERT_ID || alertId === IMS_DEMO_ALERT_ID;
}

/** The rf probability for an alert: always a different number from lgbm's. */
export function rfProbabilityFor(alert: Alert): number {
  const random = seededRandom(hashOf(alert.alert_id));
  const delta = 0.03 + random() * 0.06;
  const signed = random() > 0.35 ? -delta : delta;
  return Math.min(0.985, Math.max(0.04, alert.probability + signed));
}

function hashOf(value: string): number {
  let h = 0x811c9dc5;
  for (const char of value) h = Math.imul(h ^ char.charCodeAt(0), 0x01000193) >>> 0;
  return h >>> 0;
}

type Weighted = { meta: FeatureMeta; shap: number };

function demoWeights(alert: Alert, kind: ModelKind): Weighted[] {
  const pinned = pinnedFor(alert.plant_id);
  let entries: Weighted[];
  if (kind === 'lgbm') {
    entries = pinned.map((meta) => ({ meta, shap: meta.demo_shap ?? 0 }));
  } else {
    // The random forest keeps the same story but re-weights it, drops the weakest
    // feature and promotes one the LightGBM top-k never mentions — so the compare
    // view always has a rank-only disagreement to draw.
    const random = seededRandom(hashOf(`${alert.alert_id}:rf`));
    entries = pinned.slice(0, pinned.length - 1).map((meta) => ({
      meta,
      shap: Number(((meta.demo_shap ?? 0) * (0.55 + random() * 0.9)).toFixed(4)),
    }));
    const extra = catalogFor(alert.plant_id)[pinned.length];
    if (extra) {
      // The promoted feature pushes the probability the way the feature itself
      // points: a `down` feature may not arrive with a positive SHAP.
      const magnitude = Number((0.02 + random() * 0.05).toFixed(4));
      entries.push({
        meta: extra,
        shap: extra.direction === 'down' ? -magnitude : magnitude,
      });
    }
  }
  if (isHeadlineAlert(alert.alert_id)) return entries;

  const base = kind === 'lgbm' ? LGBM_BASE_VALUE : RF_BASE_VALUE;
  const probability = kind === 'lgbm' ? alert.probability : rfProbabilityFor(alert);
  return rescale(entries, base, probability);
}

function generatedWeights(alert: Alert, kind: ModelKind): Weighted[] {
  const catalog = catalogFor(alert.plant_id);
  const random = seededRandom(hashOf(`${alert.alert_id}:${kind}`));
  const ordered = catalog
    .map((meta) => ({ meta, key: random() }))
    .sort((a, b) => a.key - b.key)
    .slice(0, TOP_K)
    .map((entry) => entry.meta);

  const raw = ordered.map((meta, index) => {
    const magnitude = Math.pow(0.66, index) * (0.6 + random() * 0.4);
    return { meta, shap: meta.direction === 'down' ? -magnitude : magnitude };
  });
  const base = kind === 'lgbm' ? LGBM_BASE_VALUE : RF_BASE_VALUE;
  const probability = kind === 'lgbm' ? alert.probability : rfProbabilityFor(alert);
  return rescale(raw, base, probability);
}

function weightsFor(alert: Alert, kind: ModelKind): Weighted[] {
  const weights = usesPinnedFeatures(alert)
    ? demoWeights(alert, kind)
    : generatedWeights(alert, kind);
  return [...weights].sort((a, b) => Math.abs(b.shap) - Math.abs(a.shap));
}

/* ── Explanation ───────────────────────────────────────────────────────────── */

export function makeExplanation(alert: Alert, kind: ModelKind = 'lgbm'): Explanation {
  const plantId = alert.plant_id;
  const weights = weightsFor(alert, kind);
  const contributions = weights.map((entry) =>
    toContribution(plantId, entry.meta, entry.shap),
  );
  const base_value = kind === 'lgbm' ? LGBM_BASE_VALUE : RF_BASE_VALUE;
  const probability = kind === 'lgbm' ? alert.probability : rfProbabilityFor(alert);
  const sum = contributions.reduce((total, entry) => total + entry.shap, 0);
  const composed = composeSentence(
    plantId,
    alert.machine_display_name,
    probability,
    weights.map((entry) => entry.meta),
  );

  return {
    explanation_id: explanationIdFor(alert, kind),
    alert_id: alert.alert_id,
    machine_id: alert.machine_id,
    model_id: kind === 'lgbm' ? MODEL_ID : RF_MODEL_ID,
    model_kind: kind,
    dataset_ts: alert.dataset_ts,
    shap_space: 'probability',
    base_value,
    output_value: probability,
    probability,
    contributions,
    other_contributions_shap: probability - base_value - sum,
    other_contributions_count: N_FEATURES - contributions.length,
    n_features: N_FEATURES,
    sentence: composed.sentence,
    sentence_spans: composed.sentence_spans,
    caveat: CAVEAT,
  };
}

export function explanationIdFor(alert: Alert, kind: ModelKind): string {
  if (kind === 'lgbm' && alert.alert_id === DEMO_ALERT_ID) return DEMO_EXPLANATION_ID;
  return hexId('exp_', 16, alert.alert_id, kind);
}

/** The clause a fresh alert's `headline` is cut from: clause 1, capitalised. */
export function headlineFor(alert: Alert): { headline: string; topFeature: string } {
  const weights = weightsFor(alert, 'lgbm');
  const composed = composeSentence(
    alert.plant_id,
    alert.machine_display_name,
    alert.probability,
    weights.map((entry) => entry.meta),
  );
  return { headline: composed.headline, topFeature: weights[0]?.meta.feature ?? '' };
}

/** The three `{feature, shap}` entries a `risk` frame carries per machine. */
export function topFeaturesFor(
  alert: Alert,
  count = 3,
): Array<{ feature: string; shap: number }> {
  return weightsFor(alert, 'lgbm')
    .slice(0, count)
    .map((entry) => ({ feature: entry.meta.feature, shap: Number(entry.shap.toFixed(4)) }));
}

/* ── Model comparison ──────────────────────────────────────────────────────── */

function spearman(a: number[], b: number[]): number {
  const n = a.length;
  if (n < 2) return 0;
  const mean = (values: number[]): number => values.reduce((s, v) => s + v, 0) / n;
  const [ma, mb] = [mean(a), mean(b)];
  let cov = 0;
  let va = 0;
  let vb = 0;
  for (let i = 0; i < n; i += 1) {
    const da = (a[i] ?? 0) - ma;
    const db = (b[i] ?? 0) - mb;
    cov += da * db;
    va += da * da;
    vb += db * db;
  }
  if (va === 0 || vb === 0) return 0;
  return cov / Math.sqrt(va * vb);
}

export function makeComparison(alert: Alert): ModelComparison {
  const lgbm = makeExplanation(alert, 'lgbm');
  const rf = makeExplanation(alert, 'rf');

  const rankOf = (explanation: Explanation, feature: string): number | null => {
    const index = explanation.contributions.findIndex((entry) => entry.feature === feature);
    return index === -1 ? null : index + 1;
  };
  const shapOf = (explanation: Explanation, feature: string): number =>
    explanation.contributions.find((entry) => entry.feature === feature)?.shap ?? 0;

  const union = [
    ...new Set([
      ...lgbm.contributions.map((entry) => entry.feature),
      ...rf.contributions.map((entry) => entry.feature),
    ]),
  ];
  // A feature outside a model's top-k is ranked just past the end of that list,
  // which is what makes the correlation finite over the union rather than NaN.
  const missing = TOP_K + 1;
  const correlation = spearman(
    union.map((feature) => rankOf(lgbm, feature) ?? missing),
    union.map((feature) => rankOf(rf, feature) ?? missing),
  );

  const disagreements: FeatureDisagreement[] = union
    .map((feature) => {
      const lgbmShap = shapOf(lgbm, feature);
      const rfShap = shapOf(rf, feature);
      return {
        feature,
        display_name: featureMeta(alert.plant_id, feature)?.display_name ?? feature,
        lgbm_shap: lgbmShap,
        rf_shap: rfShap,
        delta: lgbmShap - rfShap,
        lgbm_rank: rankOf(lgbm, feature),
        rf_rank: rankOf(rf, feature),
      };
    })
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
    .slice(0, 6);

  const widest = disagreements[0];
  const leader = lgbm.contributions[0];
  const agree = rf.contributions[0]?.feature === leader?.feature;
  const commentary =
    `The two models ${agree ? 'agree on' : 'disagree about'} the dominant driver ` +
    `(Spearman ρ = ${formatNumber(correlation)} over ${union.length} features). ` +
    `${widest ? `The largest gap is ${widest.display_name}: LightGBM gives it ${formatNumber(widest.lgbm_shap)} against the random forest's ${formatNumber(widest.rf_shap)}.` : 'No feature differs measurably between them.'}`;

  return {
    alert_id: alert.alert_id,
    lgbm,
    rf,
    probability_delta: lgbm.probability - rf.probability,
    rank_correlation: correlation,
    disagreements,
    commentary,
  };
}

/* ── What-if ───────────────────────────────────────────────────────────────── */

/** The features a what-if request may override: the explanation's top `top_k_whatif`. */
export function overridableFeatures(explanation: Explanation): string[] {
  return explanation.contributions.slice(0, TOP_K_WHATIF).map((entry) => entry.feature);
}

/**
 * ∂p/∂x per overridable feature. The backend computes a central finite difference
 * with `h = 0.01 * (nominal_max - nominal_min)` of the source channel; the mock
 * uses the same step base so the magnitudes are in the right ballpark for the
 * client's optimistic sub-frame approximation (R7).
 */
export function whatIfGradients(
  plantId: PlantId,
  explanation: Explanation,
): Record<string, number> {
  const gradients: Record<string, number> = {};
  for (const feature of overridableFeatures(explanation)) {
    const meta = featureMeta(plantId, feature);
    const contribution = explanation.contributions.find(
      (entry) => entry.feature === feature,
    );
    if (!meta || !contribution) continue;
    const step = 0.01 * meta.nominal_span;
    gradients[feature] = step === 0 ? 0 : contribution.shap / (50 * step);
  }
  return gradients;
}

export class WhatIfValidationError extends Error {
  readonly invalid: string[];

  constructor(invalid: string[]) {
    super(`overrides must be a subset of the top ${TOP_K_WHATIF} features`);
    this.name = 'WhatIfValidationError';
    this.invalid = invalid;
  }
}

export function makeWhatIf(alert: Alert, request: WhatIfRequest): WhatIfResponse {
  const kind: ModelKind = request.model ?? 'lgbm';
  const plantId = alert.plant_id;
  const explanation = makeExplanation(alert, kind);
  const allowed = new Set(overridableFeatures(explanation));
  const overrides = request.overrides ?? {};
  const invalid = Object.keys(overrides).filter((feature) => !allowed.has(feature));
  if (invalid.length > 0) throw new WhatIfValidationError(invalid);

  const gradients = whatIfGradients(plantId, explanation);
  const contributions = explanation.contributions.map((contribution) => {
    const override = overrides[contribution.feature];
    if (override === undefined) return contribution;
    const meta = featureMeta(plantId, contribution.feature);
    const delta = override - (contribution.value ?? 0);
    const shap = contribution.shap + (gradients[contribution.feature] ?? 0) * delta;
    const direction = directionOf(shap);
    if (!meta) return { ...contribution, shap, direction, value: override };
    const moved: FeatureMeta = { ...meta, value: override };
    return {
      ...contribution,
      shap,
      direction,
      value: override,
      sentence: renderClause(plantId, moved),
    };
  });
  contributions.sort((a, b) => Math.abs(b.shap) - Math.abs(a.shap));

  const sum = contributions.reduce((total, entry) => total + entry.shap, 0);
  const probability = Math.min(
    0.999,
    Math.max(0.001, explanation.base_value + sum + explanation.other_contributions_shap),
  );
  const metas = contributions
    .map((entry) => {
      const meta = featureMeta(plantId, entry.feature);
      return meta ? { ...meta, value: entry.value } : undefined;
    })
    .filter((meta): meta is FeatureMeta => meta !== undefined);
  const composed = composeSentence(plantId, alert.machine_display_name, probability, metas);
  const random = seededRandom(
    hashOf(`${alert.alert_id}:whatif:${Object.keys(overrides).join(',')}`),
  );

  return {
    alert_id: alert.alert_id,
    model_id: explanation.model_id,
    model_kind: kind,
    shap_space: 'probability',
    baseline_probability: alert.probability,
    probability,
    base_value: explanation.base_value,
    output_value: probability,
    contributions,
    other_contributions_shap: probability - explanation.base_value - sum,
    other_contributions_count: explanation.other_contributions_count,
    n_features: explanation.n_features,
    sentence: composed.sentence,
    sentence_spans: composed.sentence_spans,
    provisional: true,
    caveat: explanation.caveat,
    gradients,
    compute_ms: Number((4 + random() * 9).toFixed(1)),
  };
}
