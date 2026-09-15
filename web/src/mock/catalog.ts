/**
 * The mock feature catalogue: the windowed features the models are trained on,
 * with the framing metadata `xpm.explain.framing` derives from `(stat, channel)`
 * (backend.md §3.9). The eight pinned features per plant are the demo machine's
 * top-k and are hand-written so every null state, framing and rendering trap the
 * SHAP views must survive is present in one payload:
 *
 * - `ai4i`: `torque` / `torque_p95_4h` are a display-name substring pair, both in
 *   the sentence; `tool_wear` has `percentile: null`; `power_slope_1h` has
 *   `value: null` and a zero window mean (the absolute-rate fallback);
 *   `rot_speed_mean_24h` and `air_temp_std_4h` point `down`.
 * - `ims`: `vibration_rms` / `vibration_rms_mean_4h` are the substring pair;
 *   `vibration_crest` has `percentile: null`; `vibration_0k5khz_slope_1h` has
 *   `value: null` and a zero window mean; two features point `down`.
 *
 * Everything after the pinned eight is generated from the channel table so the
 * beeswarm has ~20 features per machine to rank.
 */
import type { PlantId, ShapContribution } from '@/contracts';
import { channelsFor } from './core';

export type FeatureMeta = {
  feature: string;
  display_name: string;
  /** Source channel name; its display name is what the clause template opens with. */
  channel: string;
  unit: string | null;
  value: number | null;
  percentile: number | null;
  window_hours: number | null;
  stat: string | null;
  framing: ShapContribution['framing'];
  direction: ShapContribution['direction'];
  consecutive_hours: number | null;
  threshold: number | null;
  /** Percentile the consecutive-exceedance streak was measured against. */
  streak_percentile: number;
  /** Mean of the source channel over the window; 0 forces the absolute rate form. */
  window_mean: number;
  /** Slope in channel units per hour, for `trend` framings. */
  rate_per_hour: number;
  /** Nominal span of the source channel: the finite-difference step base for `gradients`. */
  nominal_span: number;
  /** The pinned SHAP weight of the demo machine's explanation, probability space. */
  demo_shap?: number;
};

type PinnedFeature = Omit<FeatureMeta, 'nominal_span'>;

const AI4I_PINNED: PinnedFeature[] = [
  {
    feature: 'torque_p95_4h',
    display_name: 'Torque — 95th pct over 4 h',
    channel: 'torque',
    unit: 'N·m',
    value: 48.1,
    percentile: 97,
    window_hours: 4,
    stat: 'p95',
    framing: 'consecutive',
    direction: 'up',
    consecutive_hours: 4,
    threshold: 46.2,
    streak_percentile: 95,
    window_mean: 41.8,
    rate_per_hour: 0,
    demo_shap: 0.3142,
  },
  {
    feature: 'torque',
    display_name: 'Torque',
    channel: 'torque',
    unit: 'N·m',
    value: 62.4,
    percentile: 88,
    window_hours: null,
    stat: null,
    framing: 'threshold',
    direction: 'up',
    consecutive_hours: null,
    threshold: 60,
    streak_percentile: 95,
    window_mean: 41.8,
    rate_per_hour: 0,
    demo_shap: 0.1875,
  },
  {
    feature: 'temp_diff_slope_1h',
    display_name: 'Temperature Difference — slope over 1 h',
    channel: 'temp_diff',
    unit: 'K',
    value: 0.31,
    percentile: 91,
    window_hours: 1,
    stat: 'slope',
    framing: 'trend',
    direction: 'up',
    consecutive_hours: null,
    threshold: null,
    streak_percentile: 95,
    window_mean: 8.6,
    rate_per_hour: 0.31,
    demo_shap: 0.0921,
  },
  {
    feature: 'rot_speed_mean_24h',
    display_name: 'Rotational Speed — mean over 24 h',
    channel: 'rot_speed',
    unit: 'rpm',
    value: 1503,
    percentile: 38,
    window_hours: 24,
    stat: 'mean',
    framing: 'percentile',
    direction: 'down',
    consecutive_hours: null,
    threshold: null,
    streak_percentile: 95,
    window_mean: 1620,
    rate_per_hour: 0,
    demo_shap: -0.062,
  },
  {
    feature: 'process_temp_p95_1h',
    display_name: 'Process Temperature — 95th pct over 1 h',
    channel: 'process_temp',
    unit: 'K',
    value: 311.2,
    percentile: 73,
    window_hours: 1,
    stat: 'p95',
    framing: 'percentile',
    direction: 'up',
    consecutive_hours: null,
    threshold: null,
    streak_percentile: 95,
    window_mean: 309.4,
    rate_per_hour: 0,
    demo_shap: 0.0614,
  },
  {
    feature: 'tool_wear',
    display_name: 'Tool Wear',
    channel: 'tool_wear',
    unit: 'min',
    // No percentile yet: this machine's tool has been changed too recently for a
    // rank over its own history to mean anything.
    value: 211,
    percentile: null,
    window_hours: null,
    stat: null,
    framing: 'threshold',
    direction: 'up',
    consecutive_hours: null,
    threshold: 200,
    streak_percentile: 95,
    window_mean: 138,
    rate_per_hour: 0,
    demo_shap: 0.0435,
  },
  {
    feature: 'air_temp_std_4h',
    display_name: 'Air Temperature — std over 4 h',
    channel: 'air_temp',
    unit: 'K',
    value: 0.42,
    percentile: 22,
    window_hours: 4,
    stat: 'std',
    framing: 'threshold',
    direction: 'down',
    consecutive_hours: null,
    threshold: 0.9,
    streak_percentile: 95,
    window_mean: 299.1,
    rate_per_hour: 0,
    demo_shap: -0.0288,
  },
  {
    feature: 'power_slope_1h',
    display_name: 'Mechanical Power — slope over 1 h',
    channel: 'power',
    unit: 'W',
    // The raw value is not computable at this row, and the window mean is zero,
    // so the trend clause must fall back to absolute units per hour.
    value: null,
    percentile: 64,
    window_hours: 1,
    stat: 'slope',
    framing: 'trend',
    direction: 'up',
    consecutive_hours: null,
    threshold: null,
    streak_percentile: 95,
    window_mean: 0,
    rate_per_hour: 18.4,
    demo_shap: 0.0176,
  },
];

const IMS_PINNED: PinnedFeature[] = [
  {
    feature: 'vibration_3khz_p95_4h',
    display_name: 'Vibration @ 3 kHz — 95th pct over 4 h',
    channel: 'vibration_3khz',
    unit: 'g²/Hz',
    value: 0.031,
    percentile: 99,
    window_hours: 4,
    stat: 'p95',
    framing: 'consecutive',
    direction: 'up',
    consecutive_hours: 4,
    threshold: 0.024,
    streak_percentile: 95,
    window_mean: 0.019,
    rate_per_hour: 0,
    demo_shap: 0.341,
  },
  {
    feature: 'vibration_rms_mean_4h',
    display_name: 'Vibration RMS — mean over 4 h',
    channel: 'vibration_rms',
    unit: 'g',
    value: 0.21,
    percentile: 97,
    window_hours: 4,
    stat: 'mean',
    framing: 'percentile',
    direction: 'up',
    consecutive_hours: null,
    threshold: null,
    streak_percentile: 95,
    window_mean: 0.18,
    rate_per_hour: 0,
    demo_shap: 0.2015,
  },
  {
    feature: 'vibration_rms',
    display_name: 'Vibration RMS',
    channel: 'vibration_rms',
    unit: 'g',
    value: 0.26,
    percentile: 95,
    window_hours: null,
    stat: null,
    framing: 'threshold',
    direction: 'up',
    consecutive_hours: null,
    threshold: 0.2,
    streak_percentile: 95,
    window_mean: 0.18,
    rate_per_hour: 0,
    demo_shap: 0.0884,
  },
  {
    feature: 'vibration_kurtosis_slope_1h',
    display_name: 'Vibration Kurtosis — slope over 1 h',
    channel: 'vibration_kurtosis',
    unit: null,
    value: 0.62,
    percentile: 92,
    window_hours: 1,
    stat: 'slope',
    framing: 'trend',
    direction: 'up',
    consecutive_hours: null,
    threshold: null,
    streak_percentile: 95,
    window_mean: 4.1,
    rate_per_hour: 0.62,
    demo_shap: 0.0723,
  },
  {
    feature: 'vibration_8khz_mean_24h',
    display_name: 'Vibration @ 8 kHz — mean over 24 h',
    channel: 'vibration_8khz',
    unit: 'g²/Hz',
    value: 0.0042,
    percentile: 31,
    window_hours: 24,
    stat: 'mean',
    framing: 'percentile',
    direction: 'down',
    consecutive_hours: null,
    threshold: null,
    streak_percentile: 95,
    window_mean: 0.0051,
    rate_per_hour: 0,
    demo_shap: -0.0551,
  },
  {
    feature: 'vibration_crest',
    display_name: 'Vibration Crest Factor',
    channel: 'vibration_crest',
    unit: null,
    value: 7.4,
    percentile: null,
    window_hours: null,
    stat: null,
    framing: 'threshold',
    direction: 'up',
    consecutive_hours: null,
    threshold: 6.5,
    streak_percentile: 95,
    window_mean: 5.9,
    rate_per_hour: 0,
    demo_shap: 0.0402,
  },
  {
    feature: 'vibration_1khz_std_4h',
    display_name: 'Vibration @ 1 kHz — std over 4 h',
    channel: 'vibration_1khz',
    unit: 'g²/Hz',
    value: 0.0031,
    percentile: 18,
    window_hours: 4,
    stat: 'std',
    framing: 'threshold',
    direction: 'down',
    consecutive_hours: null,
    threshold: 0.006,
    streak_percentile: 95,
    window_mean: 0.021,
    rate_per_hour: 0,
    demo_shap: -0.0244,
  },
  {
    feature: 'vibration_0k5khz_slope_1h',
    display_name: 'Vibration @ 0.5 kHz — slope over 1 h',
    channel: 'vibration_0k5khz',
    unit: 'g²/Hz',
    value: null,
    percentile: 58,
    window_hours: 1,
    stat: 'slope',
    framing: 'trend',
    direction: 'up',
    consecutive_hours: null,
    threshold: null,
    streak_percentile: 95,
    window_mean: 0,
    rate_per_hour: 0.004,
    demo_shap: 0.0169,
  },
];

const PINNED: Record<PlantId, PinnedFeature[]> = { ai4i: AI4I_PINNED, ims: IMS_PINNED };

/** `(stat, channel)` -> framing, exactly the table in backend.md §3.9. */
const GENERATED_STATS = [
  {
    suffix: '_p95_4h',
    stat: 'p95',
    window: 4,
    framing: 'percentile' as const,
    label: '95th pct',
  },
  {
    suffix: '_mean_24h',
    stat: 'mean',
    window: 24,
    framing: 'percentile' as const,
    label: 'mean',
  },
  {
    suffix: '_slope_1h',
    stat: 'slope',
    window: 1,
    framing: 'trend' as const,
    label: 'slope',
  },
  {
    suffix: '_std_4h',
    stat: 'std',
    window: 4,
    framing: 'threshold' as const,
    label: 'std',
  },
];

function windowLabel(hours: number): string {
  return `${hours} h`;
}

/**
 * The nominal band of a generated `std` feature, as a fraction of the source
 * channel's nominal span: a dispersion that small is normal, one that large is
 * not. `threshold` framing asserts a REAL crossing (R24), so the ceiling is what
 * an `up` feature sits above and the floor is what a `down` feature sits below —
 * the value is placed on the side its direction claims, never inside the band.
 */
const STD_BAND_CEILING = 0.06;
const STD_BAND_FLOOR = 0.01;
const STD_CROSSING = 0.25;

function buildCatalog(plantId: PlantId): FeatureMeta[] {
  const channels = channelsFor(plantId);
  const spanOf = (name: string): number => {
    const channel = channels.find((entry) => entry.name === name);
    return channel ? channel.nominal_max - channel.nominal_min : 1;
  };

  const pinned: FeatureMeta[] = PINNED[plantId].map((meta) => ({
    ...meta,
    nominal_span: spanOf(meta.channel),
  }));
  const taken = new Set(pinned.map((meta) => meta.feature));

  const generated: FeatureMeta[] = [];
  for (const channel of channels) {
    const span = channel.nominal_max - channel.nominal_min;
    const mid = channel.nominal_min + span / 2;
    for (const [index, spec] of GENERATED_STATS.entries()) {
      const feature = `${channel.name}${spec.suffix}`;
      if (taken.has(feature)) continue;
      const skew = ((index + 1) * 17) % 7;
      const direction = skew % 3 === 0 ? 'down' : 'up';
      // A `std` feature is a dispersion, so it is measured against the dispersion
      // band, not against the channel's own mid-scale.
      const edge = span * (direction === 'down' ? STD_BAND_FLOOR : STD_BAND_CEILING);
      const crossed =
        direction === 'down' ? edge * (1 - STD_CROSSING) : edge * (1 + STD_CROSSING);
      generated.push({
        feature,
        display_name: `${channel.display_name} — ${spec.label} over ${windowLabel(spec.window)}`,
        channel: channel.name,
        unit: channel.unit === '' ? null : channel.unit,
        value: spec.stat === 'std' ? crossed : mid + span * (skew / 40),
        percentile: 12 + skew * 11,
        window_hours: spec.window,
        stat: spec.stat,
        framing: spec.framing,
        direction,
        consecutive_hours: null,
        threshold: spec.framing === 'threshold' ? edge : null,
        streak_percentile: 95,
        window_mean: mid,
        rate_per_hour: span * 0.004 * (skew % 3 === 0 ? -1 : 1),
        nominal_span: span,
      });
    }
  }
  return [...pinned, ...generated];
}

const CATALOG: Record<PlantId, FeatureMeta[]> = {
  ai4i: buildCatalog('ai4i'),
  ims: buildCatalog('ims'),
};

/** Every feature the mock models know about for a plant; pinned eight first. */
export function catalogFor(plantId: PlantId): FeatureMeta[] {
  return CATALOG[plantId];
}

/** The demo machine's pinned top-k, in |shap| descending order. */
export function pinnedFor(plantId: PlantId): FeatureMeta[] {
  return CATALOG[plantId].slice(0, PINNED[plantId].length);
}

export function featureMeta(plantId: PlantId, feature: string): FeatureMeta | undefined {
  return CATALOG[plantId].find((meta) => meta.feature === feature);
}
