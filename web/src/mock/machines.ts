/**
 * Machine-level fixtures: the live scalars, the sparkline and the snapshot rows.
 *
 * Three machines carry deliberate null shapes, because "not yet computable" is a
 * designed empty state and never a zero:
 * - `ims-04` is offline — null probability, all-null sparkline, all-null values.
 * - `ai4i-11` was commissioned mid-run (first scored at tick 220), so its
 *   sparkline starts with leading nulls at any tick in 220..279.
 * - `ai4i-09` has a scoring gap at ticks 200..205, an interior run of nulls.
 */
import type { MachineSnapshot, MachineSummary, PlantId } from '@/contracts';
import { openAlertAt } from './alerts';
import {
  SPARKLINE_POINTS,
  baseProbabilityFor,
  makeChannelValues,
  datasetTsFor,
  machineDisplayName,
  machineIdsFor,
  statusFor,
} from './core';

/** The machine that has stopped publishing; its status comes from the backend. */
export const OFFLINE_MACHINE_ID = 'ims-04';
/** Commissioned mid-run: nothing was scored before this tick. */
export const LATE_MACHINE_ID = 'ai4i-11';
export const LATE_MACHINE_FIRST_TICK = 220;
/** A scoring gap, so the sparkline has an interior null run, not a leading one. */
export const GAP_MACHINE_ID = 'ai4i-09';
export const GAP_MACHINE_TICKS: readonly number[] = [200, 201, 202, 203, 204, 205];

/** True when the machine had a scored row at `tick`. */
export function isScored(machineId: string, tick: number): boolean {
  if (tick < 0) return false;
  if (machineId === OFFLINE_MACHINE_ID) return false;
  if (machineId === LATE_MACHINE_ID && tick < LATE_MACHINE_FIRST_TICK) return false;
  if (machineId === GAP_MACHINE_ID && GAP_MACHINE_TICKS.includes(tick)) return false;
  return true;
}

/**
 * A machine's probability at `tick`. When an alert was raised on that exact row
 * the alert's own probability is returned, so a marker on the risk timeline sits
 * on the curve rather than beside it.
 */
export function probabilityFor(machineId: string, tick: number): number {
  const open = openAlertAt(machineId, tick);
  if (
    open &&
    Date.parse(open.dataset_ts) === Date.parse(datasetTsFor(open.plant_id, tick))
  ) {
    return open.probability;
  }
  return baseProbabilityFor(machineId, tick);
}

export function riskSparkline(machineId: string, tick: number): Array<number | null> {
  return Array.from({ length: SPARKLINE_POINTS }, (_, index) => {
    const sampleTick = tick - (SPARKLINE_POINTS - 1) + index;
    return isScored(machineId, sampleTick) ? probabilityFor(machineId, sampleTick) : null;
  });
}

export function makeMachineSummary(
  plantId: PlantId,
  machineId: string,
  tick: number,
): MachineSummary {
  const scored = isScored(machineId, tick);
  const probability = scored ? probabilityFor(machineId, tick) : null;
  const open = machineId === OFFLINE_MACHINE_ID ? null : openAlertAt(machineId, tick);
  return {
    machine_id: machineId,
    plant_id: plantId,
    display_name: machineDisplayName(plantId, machineId),
    status:
      machineId === OFFLINE_MACHINE_ID
        ? 'offline'
        : open !== null
          ? 'alert'
          : statusFor(probability ?? 0),
    probability,
    dataset_ts: datasetTsFor(plantId, tick),
    open_alert_id: open?.alert_id ?? null,
    risk_sparkline: riskSparkline(machineId, tick),
  };
}

export function makeMachineSummaries(plantId: PlantId, tick: number): MachineSummary[] {
  return machineIdsFor(plantId).map((machineId) =>
    makeMachineSummary(plantId, machineId, tick),
  );
}

export function makeSnapshotMachines(plantId: PlantId, tick: number): MachineSnapshot[] {
  return makeMachineSummaries(plantId, tick).map((summary) => ({
    ...summary,
    values: makeChannelValues(plantId, summary.machine_id, tick),
  }));
}
