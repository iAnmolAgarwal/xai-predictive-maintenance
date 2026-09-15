/**
 * Fixture invariants. These are the properties the SHAP views, the alert rail and
 * the scrubber are allowed to rely on; if one of them breaks, a feature test that
 * uses the mock would fail for a reason that has nothing to do with the feature.
 */
import { describe, expect, it } from 'vitest';
import type {
  Alert,
  Explanation,
  GlobalImportance,
  ModelComparison,
  ModelInfo,
  PlantSnapshot,
  RiskSeries,
  TelemetrySeries,
  WhatIfResponse,
} from '@/contracts';
import {
  CURRENT_TICK,
  DEMO_ALERT_ID,
  DEMO_ALERT_TICK,
  IMS_DEMO_ALERT_ID,
  MUTABLE_KEYS,
  N_FEATURES,
  SPARKLINE_POINTS,
  TOP_K,
  allAlerts,
  catalogFor,
  datasetTsFor,
  findAlert,
  makeComparison,
  makeConfig,
  makeExplanation,
  makeImportance,
  makeMachineSummary,
  makeModels,
  makeRiskSeries,
  makeStateAt,
  makeTelemetrySeries,
  makeWhatIf,
  overridableFeatures,
  formatNumber,
  renderClause,
} from '../fixtures';

const demo = (): Alert => {
  const alert = findAlert(DEMO_ALERT_ID);
  if (!alert) throw new Error('the demo alert must exist in the corpus');
  return alert;
};

/* The fixture builders are checked against the generated contract types at
 * compile time: `satisfies` here fails `tsc --noEmit` if a payload ever drifts
 * from `contracts/openapi.json`. */
export const contractCheck = {
  telemetry: makeTelemetrySeries('ai4i', 'ai4i-03', {}) satisfies TelemetrySeries,
  risk: makeRiskSeries('ai4i', 'ai4i-03', {}) satisfies RiskSeries,
  explanation: makeExplanation(demo()) satisfies Explanation,
  comparison: makeComparison(demo()) satisfies ModelComparison,
  importance: makeImportance('ai4i', 'ai4i-03', {}) satisfies GlobalImportance,
  snapshot: makeStateAt('ai4i', datasetTsFor('ai4i', CURRENT_TICK)) satisfies PlantSnapshot,
  models: makeModels() satisfies ModelInfo[],
  whatIf: makeWhatIf(demo(), {
    alert_id: DEMO_ALERT_ID,
    model: 'lgbm',
    overrides: {},
  }) satisfies WhatIfResponse,
};

describe('contract shapes', () => {
  it('builds every payload as the generated contract type', () => {
    expect(Object.keys(contractCheck)).toHaveLength(8);
  });
});

describe('explanation closure', () => {
  it('closes from base value to the probability on screen, for every alert', () => {
    for (const alert of allAlerts()) {
      for (const kind of ['lgbm', 'rf'] as const) {
        const explanation = makeExplanation(alert, kind);
        const sum = explanation.contributions.reduce((total, c) => total + c.shap, 0);
        const closed = explanation.base_value + sum + explanation.other_contributions_shap;
        expect(Math.abs(closed - explanation.output_value)).toBeLessThan(1e-9);
        expect(Math.abs(explanation.output_value - explanation.probability)).toBeLessThan(
          1e-9,
        );
        expect(explanation.shap_space).toBe('probability');
        expect(explanation.probability).toBeGreaterThan(0);
        expect(explanation.probability).toBeLessThan(1);
      }
    }
  });

  it('rolls the tail up as n_features minus the rendered contributions', () => {
    const explanation = makeExplanation(demo());
    expect(explanation.contributions).toHaveLength(TOP_K);
    expect(explanation.n_features).toBe(N_FEATURES);
    expect(explanation.other_contributions_count).toBe(
      explanation.n_features - explanation.contributions.length,
    );
    expect(explanation.other_contributions_count).toBe(146);
  });

  it('keeps the caveat out of the sentence', () => {
    const explanation = makeExplanation(demo());
    expect(explanation.caveat).toContain('not proof of physical cause');
    expect(explanation.sentence).not.toContain(explanation.caveat);
  });
});

describe('the R24 rendering invariants', () => {
  it('reports direction as the sign of the shap value, corpus-wide', () => {
    const mismatches: string[] = [];
    let contributions = 0;
    for (const alert of allAlerts()) {
      for (const kind of ['lgbm', 'rf'] as const) {
        for (const entry of makeExplanation(alert, kind).contributions) {
          contributions += 1;
          if (entry.shap > 0 !== (entry.direction === 'up'))
            mismatches.push(`${alert.alert_id}/${kind}/${entry.feature}`);
        }
      }
    }
    // The force plot puts `up` right with a ▲ while the waterfall bar's side
    // comes from the signed shap: disagreement draws the bar under the wrong
    // glyph, and a feature task cannot patch it from outside `src/mock`.
    expect(mismatches).toEqual([]);
    expect(contributions).toBe(allAlerts().length * 2 * TOP_K);
  });

  it('claims a threshold crossing only where the value really crossed', () => {
    const inconsistent: string[] = [];
    for (const alert of allAlerts()) {
      for (const kind of ['lgbm', 'rf'] as const) {
        for (const entry of makeExplanation(alert, kind).contributions) {
          if (entry.framing !== 'threshold') continue;
          const { value, threshold, direction, sentence } = entry;
          if (value === null || threshold === null) {
            inconsistent.push(`${entry.feature}: threshold framing needs both numbers`);
            continue;
          }
          const crossed = direction === 'up' ? value > threshold : value < threshold;
          const worded = direction === 'up' ? 'normal ceiling' : 'normal floor';
          if (!crossed) inconsistent.push(`${entry.feature}: ${value} vs ${threshold}`);
          if (!sentence.includes(worded))
            inconsistent.push(`${entry.feature}: ${sentence}`);
          // The rendered numbers are the ones being compared, and neither of them
          // collapses to `0` on the way to the screen.
          if (!sentence.includes(formatNumber(value)))
            inconsistent.push(`${entry.feature}: value missing from "${sentence}"`);
          if (!sentence.includes(formatNumber(threshold)))
            inconsistent.push(`${entry.feature}: threshold missing from "${sentence}"`);
        }
      }
    }
    expect(inconsistent).toEqual([]);
  });

  it('prints a sub-unit magnitude to three significant digits, never as 0', () => {
    expect(formatNumber(0.0004)).toBe('0.0004');
    expect(formatNumber(0.00042361)).toBe('0.000424');
    expect(formatNumber(0.031)).toBe('0.031');
    expect(formatNumber(0)).toBe('0');
    expect(formatNumber(-0.0042)).toBe('-0.0042');
    expect(formatNumber(48.1)).toBe('48.1');
    expect(formatNumber(2540)).toBe('2,540');
  });

  it('drops the percentile phrase when the feature has no rank yet', () => {
    const ranked = catalogFor('ims')[1];
    if (!ranked) throw new Error('the ims catalogue must carry a ranked feature');
    expect(ranked.framing).toBe('percentile');
    expect(renderClause('ims', ranked)).toContain('percentile');
    const unranked = { ...ranked, percentile: null };
    const clause = renderClause('ims', unranked);
    expect(clause).not.toContain('percentile');
    expect(clause).toContain('no rank over this machine');
  });
});

describe('sentence spans', () => {
  it('slices the opening display name of each clause, by offset', () => {
    for (const alertId of [DEMO_ALERT_ID, IMS_DEMO_ALERT_ID]) {
      const alert = findAlert(alertId);
      if (!alert) throw new Error(`missing ${alertId}`);
      const explanation = makeExplanation(alert);
      expect(explanation.sentence_spans).toHaveLength(2);

      for (const span of explanation.sentence_spans) {
        const clause = explanation.contributions.find(
          (entry) => entry.feature === span.feature,
        )?.sentence;
        expect(clause).toBeDefined();
        const slice = explanation.sentence.slice(span.start, span.end);
        // The span is the clause's leading `{display}` and nothing more…
        expect(clause?.startsWith(slice)).toBe(true);
        expect(slice.length).toBeGreaterThan(0);
        // …and the whole clause sits at that offset in the sentence.
        expect(
          explanation.sentence.slice(span.start, span.start + (clause?.length ?? 0)),
        ).toBe(clause);
      }
    }
  });

  it('disambiguates two features whose display names share a prefix', () => {
    const explanation = makeExplanation(demo());
    const [first, second] = explanation.sentence_spans;
    expect(first?.feature).toBe('torque_p95_4h');
    expect(second?.feature).toBe('torque');
    // Both clauses open with the same channel display name, so a string match
    // would resolve both spans to the same offset. The offsets differ.
    expect(explanation.sentence.slice(first?.start ?? 0, first?.end ?? 0)).toBe('Torque');
    expect(explanation.sentence.slice(second?.start ?? 0, second?.end ?? 0)).toBe('Torque');
    expect(first?.start).not.toBe(second?.start);

    const names = explanation.contributions.map((entry) => entry.display_name);
    expect(names).toContain('Torque');
    expect(names).toContain('Torque — 95th pct over 4 h');
  });

  it('renders every framing, direction and null state on the demo explanation', () => {
    const contributions = makeExplanation(demo()).contributions;
    const byFeature = (feature: string) =>
      contributions.find((entry) => entry.feature === feature);

    expect(byFeature('power_slope_1h')?.value).toBeNull();
    expect(byFeature('tool_wear')?.percentile).toBeNull();
    expect(contributions.some((entry) => entry.direction === 'down')).toBe(true);
    expect(new Set(contributions.map((entry) => entry.framing))).toEqual(
      new Set(['consecutive', 'threshold', 'trend', 'percentile']),
    );

    // The zero-window-mean trend falls back to absolute units per hour and never
    // divides by zero.
    const zeroMean = byFeature('power_slope_1h')?.sentence ?? '';
    expect(zeroMean).toContain('+18.4 W per hour');
    expect(zeroMean).not.toMatch(/NaN|Infinity|%/);
    // The non-zero-mean trend uses the percent-of-window-mean form.
    expect(byFeature('temp_diff_slope_1h')?.sentence).toContain('% per hour');
  });
});

describe('alert corpus', () => {
  it('spans machines, severities and features, and resolves some alerts', () => {
    const alerts = allAlerts();
    expect(alerts.length).toBeGreaterThanOrEqual(60);
    expect(new Set(alerts.map((alert) => alert.severity))).toEqual(
      new Set(['medium', 'high', 'critical']),
    );
    expect(new Set(alerts.map((alert) => alert.machine_id)).size).toBeGreaterThan(10);
    expect(new Set(alerts.map((alert) => alert.top_feature)).size).toBeGreaterThan(5);
    expect(alerts.some((alert) => alert.closed_dataset_ts !== null)).toBe(true);
    expect(alerts.some((alert) => alert.closed_dataset_ts === null)).toBe(true);
  });

  it('keeps at most one alert open per machine at any dataset instant', () => {
    for (const tick of [0, 60, 120, DEMO_ALERT_TICK, CURRENT_TICK]) {
      const open = new Map<string, number>();
      for (const alert of allAlerts()) {
        const at = Date.parse(datasetTsFor(alert.plant_id, tick));
        const opened = Date.parse(alert.dataset_ts) <= at;
        const closed =
          alert.closed_dataset_ts !== null && Date.parse(alert.closed_dataset_ts) <= at;
        if (opened && !closed) {
          open.set(alert.machine_id, (open.get(alert.machine_id) ?? 0) + 1);
        }
      }
      expect([...open.values()].every((count) => count === 1)).toBe(true);
    }
  });

  it('cuts the headline from the first clause of the explanation', () => {
    const alert = demo();
    const explanation = makeExplanation(alert);
    expect(alert.headline).toBe(`${explanation.contributions[0]?.sentence}.`);
    expect(alert.top_feature).toBe(explanation.contributions[0]?.feature);
    expect(alert.explanation_id).toBe(explanation.explanation_id);
  });
});

describe('machine summaries', () => {
  it('sizes the sparkline from api.sparkline_points', () => {
    const config = makeConfig();
    expect(config.values['api.sparkline_points']).toBe(SPARKLINE_POINTS);
    expect(makeMachineSummary('ai4i', 'ai4i-03', CURRENT_TICK).risk_sparkline).toHaveLength(
      SPARKLINE_POINTS,
    );
  });

  it('carries leading nulls, an interior null run and a fully offline machine', () => {
    const late = makeMachineSummary('ai4i', 'ai4i-11', CURRENT_TICK).risk_sparkline;
    expect(late[0]).toBeNull();
    expect(late[late.length - 1]).not.toBeNull();

    const gap = makeMachineSummary('ai4i', 'ai4i-09', CURRENT_TICK).risk_sparkline;
    const nulls = gap.flatMap((value, index) => (value === null ? [index] : []));
    expect(nulls.length).toBeGreaterThan(0);
    expect(Math.min(...nulls)).toBeGreaterThan(0);
    expect(Math.max(...nulls)).toBeLessThan(gap.length - 1);

    const offline = makeMachineSummary('ims', 'ims-04', CURRENT_TICK);
    expect(offline.status).toBe('offline');
    expect(offline.probability).toBeNull();
    expect(offline.risk_sparkline.every((value) => value === null)).toBe(true);
  });

  it('points the demo machine at its open alert', () => {
    expect(makeMachineSummary('ai4i', 'ai4i-03', CURRENT_TICK).open_alert_id).toBe(
      DEMO_ALERT_ID,
    );
    expect(makeMachineSummary('ims', 'ims-01', CURRENT_TICK).open_alert_id).toBe(
      IMS_DEMO_ALERT_ID,
    );
  });
});

describe('determinism', () => {
  it('produces identical payloads for identical requests', () => {
    expect(JSON.stringify(makeExplanation(demo()))).toBe(
      JSON.stringify(makeExplanation(demo())),
    );
    expect(JSON.stringify(makeTelemetrySeries('ai4i', 'ai4i-03', {}))).toBe(
      JSON.stringify(makeTelemetrySeries('ai4i', 'ai4i-03', {})),
    );
    expect(JSON.stringify(allAlerts())).toBe(JSON.stringify(allAlerts()));
  });
});

describe('config tree', () => {
  it('carries every leaf the frontend reads, and marks only the patchable ones', () => {
    const { values, mutable_keys: mutable } = makeConfig();
    for (const key of [
      'explanation.top_k',
      'explanation.top_k_whatif',
      'explanation.top_k_preview',
      'alerting.severity_bands.medium',
      'alerting.severity_bands.high',
      'alerting.severity_bands.critical',
      'alerting.probability_threshold',
      'alerting.watch_threshold',
      'replay.allowed_speeds',
      'api.sparkline_points',
      'api.ws_ping_seconds',
      'api.ws_flush_ms',
      'api.max_series_points',
      'api.offline_after_seconds',
    ]) {
      expect(values, `missing ${key}`).toHaveProperty(key);
    }
    expect(mutable).toEqual(MUTABLE_KEYS);
    expect(mutable).not.toContain('replay.speed');
    expect(values).toHaveProperty('replay.allowed_speeds', [0.5, 1, 5, 20]);
  });
});

describe('what-if inputs', () => {
  it('offers only features whose current value is a number', () => {
    const explanation = makeExplanation(demo());
    for (const feature of overridableFeatures(explanation)) {
      const contribution = explanation.contributions.find(
        (entry) => entry.feature === feature,
      );
      expect(contribution?.value).not.toBeNull();
    }
    expect(overridableFeatures(explanation)).toHaveLength(5);
  });
});

describe('feature catalogue', () => {
  it('ranks at least twenty features per plant for the beeswarm', () => {
    expect(catalogFor('ai4i').length).toBeGreaterThanOrEqual(20);
    expect(catalogFor('ims').length).toBeGreaterThanOrEqual(20);
  });
});
