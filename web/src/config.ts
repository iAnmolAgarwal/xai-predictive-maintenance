/**
 * Frontend-only constants (frontend.md §1.1). Nothing the backend owns lives
 * here: allowed speeds, top-k, thresholds, sparkline length, severity bands and
 * channel units are all read from `GET /api/config` at runtime.
 *
 * No magic numbers in feature code — if a number is not on the wire, it is here.
 */
import type { ConfigResponse } from '@/contracts';

/** Samples held per machine per channel in the telemetry/risk ring buffers. */
export const CAPACITY = 3600;

/** Alerts retained in the rail before the oldest is evicted. */
export const ALERT_CAP = 500;

/**
 * Tolerate two missed heartbeats plus half a period of jitter before declaring
 * the socket dead. The timeout itself is derived, never a literal — see
 * {@link wsSilenceTimeoutMs}.
 */
export const WS_SILENCE_FACTOR = 2.5;

/** Exponential backoff with full jitter for WebSocket reconnects. */
export const RECONNECT = {
  baseMs: 500,
  factor: 1.8,
  capMs: 15_000,
} as const;

/** Leading+trailing throttle on what-if slider input. */
export const WHATIF_THROTTLE_MS = 60;

/** Round trip beyond this shows a non-blocking "recomputing" affordance. */
export const WHATIF_SLOW_AFFORDANCE_MS = 400;

/** Below this viewport width the alert rail becomes an overlay drawer (R8). */
export const RAIL_BREAKPOINT_PX = 1440;

/** Hard cap on beeswarm points; the legend surfaces the cap when it bites. */
export const BEESWARM_MAX_POINTS = 2000;

/** Hard cap on points handed to a telemetry chart after decimation. */
export const TELEMETRY_MAX_POINTS = 2000;

/** The backend key the liveness timeout is derived from. */
const WS_PING_SECONDS_KEY = 'api.ws_ping_seconds';

/** Fallback used only before `GET /api/config` resolves: the documented default. */
const WS_PING_SECONDS_FALLBACK = 10;

/**
 * `WS_SILENCE_TIMEOUT_MS` is derived at runtime from `ConfigResponse.values`
 * (frontend.md §1.1, review 2 item 12), never written as a literal: at the
 * default `api.ws_ping_seconds = 10` it is 25 000 ms, and a backend that pings
 * every 4 s moves it to 10 000 ms with no frontend change.
 */
export function wsSilenceTimeoutMs(values: ConfigResponse['values'] | null): number {
  const raw = values?.[WS_PING_SECONDS_KEY];
  const seconds = typeof raw === 'number' && raw > 0 ? raw : WS_PING_SECONDS_FALLBACK;
  return Math.round(WS_SILENCE_FACTOR * seconds * 1000);
}
