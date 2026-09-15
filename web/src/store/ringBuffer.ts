/**
 * Pre-allocated typed-array ring buffers, held outside the React store
 * (frontend.md §1.1, §3.3). A telemetry frame never allocates, never produces a
 * new array identity and never invalidates a memo other than the chart that owns
 * the buffer it wrote into. The store carries only an integer revision.
 */
import { CAPACITY } from '@/config';

export type Ring = {
  datasetTsMs: Float64Array;
  series: Float64Array[];
  cap: number;
  /** Index the next sample will be written to. */
  write: number;
  /** Samples written so far, saturating at `cap`. */
  count: number;
};

/** Allocate a ring for `seriesCount` parallel series. Never grown afterwards. */
export function createRing(seriesCount: number, cap: number = CAPACITY): Ring {
  const series: Float64Array[] = [];
  for (let i = 0; i < seriesCount; i += 1) series.push(new Float64Array(cap));
  return { datasetTsMs: new Float64Array(cap), series, cap, write: 0, count: 0 };
}

/**
 * Append one sample. `null` is written as `NaN` so charts draw a gap — never a
 * zero, never an interpolation (frontend.md §6.4). Values beyond the ring's
 * series count are ignored; missing ones are written as `NaN`.
 */
export function pushSample(
  ring: Ring,
  datasetTsMs: number,
  values: readonly (number | null)[],
): void {
  const at = ring.write;
  ring.datasetTsMs[at] = datasetTsMs;
  for (let i = 0; i < ring.series.length; i += 1) {
    const target = ring.series[i];
    if (!target) continue;
    const value = i < values.length ? values[i] : null;
    target[at] = value === null || value === undefined ? Number.NaN : value;
  }
  ring.write = (at + 1) % ring.cap;
  if (ring.count < ring.cap) ring.count += 1;
}

/** The most recent value of one series, or `NaN` when the ring is empty. */
export function lastValue(ring: Ring, seriesIndex: number): number {
  const series = ring.series[seriesIndex];
  if (!series || ring.count === 0) return Number.NaN;
  const at = (ring.write - 1 + ring.cap) % ring.cap;
  return series[at] ?? Number.NaN;
}

/**
 * Copy the last `n` samples out in chronological order, unwrapping the buffer.
 * Reading allocates (charts need contiguous arrays); writing never does.
 */
export function readLast(
  ring: Ring,
  n: number,
): { datasetTsMs: Float64Array; series: Float64Array[] } {
  const take = Math.max(0, Math.min(n, ring.count));
  const start = (ring.write - take + ring.cap) % ring.cap;
  const stamps = new Float64Array(take);
  copyRange(ring.datasetTsMs, stamps, start, take, ring.cap);
  const series = ring.series.map((source) => {
    const out = new Float64Array(take);
    copyRange(source, out, start, take, ring.cap);
    return out;
  });
  return { datasetTsMs: stamps, series };
}

function copyRange(
  source: Float64Array,
  target: Float64Array,
  start: number,
  take: number,
  cap: number,
): void {
  const head = Math.min(take, cap - start);
  target.set(source.subarray(start, start + head), 0);
  if (head < take) target.set(source.subarray(0, take - head), head);
}

const telemetryRings = new Map<string, Ring>();
const riskRings = new Map<string, Ring>();

/**
 * (Re)allocate every machine's buffers. Called on `hello`, sized from
 * `plant.channels.length` and `plant.machine_count` — never a hardcoded channel
 * count — and on every reconnect, because a reconnect rebuilds state wholesale
 * from the new snapshot rather than stitching (R10).
 */
export function allocateRings(
  machineIds: readonly string[],
  channelCount: number,
  cap: number = CAPACITY,
): void {
  telemetryRings.clear();
  riskRings.clear();
  for (const machineId of machineIds) {
    telemetryRings.set(machineId, createRing(channelCount, cap));
    riskRings.set(machineId, createRing(1, cap));
  }
}

/** The telemetry ring for a machine, or `undefined` before `hello` sized them. */
export function getTelemetryRing(machineId: string): Ring | undefined {
  return telemetryRings.get(machineId);
}

/** The risk ring (a single `probability` series) for a machine. */
export function getRiskRing(machineId: string): Ring | undefined {
  return riskRings.get(machineId);
}

/** Drop every buffer. Used on plant switch and by tests. */
export function clearRings(): void {
  telemetryRings.clear();
  riskRings.clear();
}

/** Machine ids that currently have buffers, in insertion order. */
export function ringMachineIds(): string[] {
  return [...telemetryRings.keys()];
}
