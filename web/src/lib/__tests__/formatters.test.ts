import { describe, expect, it } from 'vitest';
import { AI4I_CHANNELS, IMS_CHANNELS } from '@/mock/fixtures';
import {
  formatDatasetClock,
  formatDatasetTime,
  formatNumber,
  formatOtherFeatures,
  formatPercentile,
  formatProbability,
  formatSigned,
  formatUnit,
  formatWindow,
  parseDatasetTs,
  unitSlug,
} from '../formatters';

describe('formatUnit', () => {
  it('prints every backend unit string verbatim and converts nothing', () => {
    // Property test over the units on the ChannelSpec fixtures, so no unit
    // literal appears in this test.
    for (const channel of [...AI4I_CHANNELS, ...IMS_CHANNELS]) {
      const rendered = formatUnit(12.5, channel.unit);
      expect(rendered.startsWith('12.5')).toBe(true);
      if (channel.unit === '') {
        expect(rendered).toBe('12.5');
      } else {
        expect(rendered.endsWith(channel.unit)).toBe(true);
        expect(rendered).toContain(' ');
      }
    }
  });

  it('prints a bare number for both null and the empty string', () => {
    expect(formatUnit(3, null)).toBe('3.00');
    expect(formatUnit(3, '')).toBe('3.00');
    expect(formatUnit(3, null)).not.toContain('\u2009');
  });

  it('renders a null value as an em dash', () => {
    const dimensionless = IMS_CHANNELS.find((channel) => channel.unit === '');
    expect(dimensionless).toBeDefined();
    expect(formatUnit(null, dimensionless?.unit ?? '')).toBe('—');
  });
});

describe('formatWindow', () => {
  it.each([
    [1, '1 h'],
    [4, '4 h'],
    [24, '24 h'],
  ])('formats %s hours', (hours, expected) => {
    expect(formatWindow(hours)).toBe(expected);
  });

  it('renders no chip for a raw channel', () => {
    expect(formatWindow(null)).toBe('');
  });
});

describe('formatOtherFeatures', () => {
  it('handles the singular case', () => {
    expect(formatOtherFeatures(1)).toBe('1 other feature');
  });

  it('handles the plural case', () => {
    expect(formatOtherFeatures(146)).toBe('146 other features');
  });
});

describe('number formatting', () => {
  it('scales precision with magnitude', () => {
    expect(formatNumber(0)).toBe('0');
    expect(formatNumber(1503)).toBe('1503');
    expect(formatNumber(48.14)).toBe('48.1');
    expect(formatNumber(1.234)).toBe('1.23');
    expect(formatNumber(0.0123)).toBe('0.012');
    expect(formatNumber(0.00001)).toBe('1.00e-5');
    expect(formatNumber(Number.POSITIVE_INFINITY)).toBe('—');
  });

  it('renders probabilities as percentages only at render time', () => {
    expect(formatProbability(0.74)).toBe('74%');
    expect(formatProbability(null)).toBe('—');
  });

  it('signs contributions explicitly', () => {
    expect(formatSigned(0.31)).toBe('+0.31');
    expect(formatSigned(-0.06)).toBe('−0.06');
    expect(formatSigned(0)).toBe('0.00');
    expect(formatSigned(Number.NaN)).toBe('—');
  });

  it('omits a null percentile rather than showing 0th', () => {
    expect(formatPercentile(97)).toBe('97th percentile');
    expect(formatPercentile(null)).toBeNull();
  });
});

describe('dataset time', () => {
  it('parses once, to epoch milliseconds', () => {
    expect(parseDatasetTs('2026-01-02T10:45:00.000Z')).toBe(
      Date.parse('2026-01-02T10:45:00.000Z'),
    );
    expect(Number.isNaN(parseDatasetTs(null))).toBe(true);
    expect(Number.isNaN(parseDatasetTs('not a timestamp'))).toBe(true);
  });

  it('renders UTC dataset time, not wall-clock local time', () => {
    const ms = Date.parse('2026-01-02T10:45:00.000Z');
    expect(formatDatasetTime(ms)).toBe('2026-01-02 10:45:00');
    expect(formatDatasetClock(ms)).toBe('10:45');
    expect(formatDatasetTime(Number.NaN)).toBe('—');
    expect(formatDatasetClock(null)).toBe('—');
  });
});

describe('unitSlug', () => {
  it('derives every slug from the backend string, never a literal', () => {
    for (const channel of [...AI4I_CHANNELS, ...IMS_CHANNELS]) {
      const slug = unitSlug(channel.unit);
      expect(slug).toBe(
        channel.unit
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '-')
          .replace(/^-+|-+$/g, ''),
      );
      expect(slug).not.toMatch(/^-|-$/);
    }
  });
});
