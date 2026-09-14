/**
 * Exponential backoff with full jitter (frontend.md §1.1): base 500 ms,
 * factor 1.8, cap 15 s. Pure, with an injectable RNG, so the schedule is
 * asserted in a test rather than eyeballed in a log.
 */
import { RECONNECT } from '@/config';

export type BackoffConfig = { baseMs: number; factor: number; capMs: number };

/** Ceiling for `attempt` (0-based) before jitter is applied. */
export function backoffCeilingMs(
  attempt: number,
  config: BackoffConfig = RECONNECT,
): number {
  const raw = config.baseMs * Math.pow(config.factor, Math.max(0, attempt));
  return Math.min(config.capMs, Math.round(raw));
}

/**
 * Full jitter: a uniform draw in `[0, ceiling]`. Two clients that drop together
 * do not reconnect together.
 */
export function backoffDelayMs(
  attempt: number,
  random: () => number = Math.random,
  config: BackoffConfig = RECONNECT,
): number {
  return Math.round(random() * backoffCeilingMs(attempt, config));
}
