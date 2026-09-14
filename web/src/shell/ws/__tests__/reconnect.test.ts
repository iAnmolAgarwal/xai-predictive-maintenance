import { describe, expect, it } from 'vitest';
import { RECONNECT } from '@/config';
import { backoffCeilingMs, backoffDelayMs } from '../reconnect';

describe('reconnect backoff', () => {
  it('grows by the configured factor from the configured base', () => {
    expect(backoffCeilingMs(0)).toBe(RECONNECT.baseMs);
    expect(backoffCeilingMs(1)).toBe(Math.round(RECONNECT.baseMs * RECONNECT.factor));
    expect(backoffCeilingMs(2)).toBe(
      Math.round(RECONNECT.baseMs * RECONNECT.factor ** 2),
    );
  });

  it('caps at 15 s no matter how many attempts have failed', () => {
    expect(backoffCeilingMs(20)).toBe(RECONNECT.capMs);
    expect(backoffCeilingMs(1000)).toBe(RECONNECT.capMs);
  });

  it('applies full jitter: a seeded RNG gives the whole schedule', () => {
    const half = (): number => 0.5;
    const schedule = [0, 1, 2, 3, 4, 5, 6, 7, 8].map((attempt) =>
      backoffDelayMs(attempt, half),
    );
    expect(schedule).toEqual([250, 450, 810, 1458, 2625, 4724, 7500, 7500, 7500]);

    expect(backoffDelayMs(3, () => 0)).toBe(0);
    expect(backoffDelayMs(3, () => 1)).toBe(backoffCeilingMs(3));
  });

  it('treats a negative attempt as the first one', () => {
    expect(backoffCeilingMs(-5)).toBe(RECONNECT.baseMs);
  });
});
