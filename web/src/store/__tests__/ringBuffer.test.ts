import { beforeEach, describe, expect, it } from 'vitest';
import { makePlant } from '@/mock/fixtures';
import {
  allocateRings,
  clearRings,
  createRing,
  getRiskRing,
  getTelemetryRing,
  lastValue,
  pushSample,
  readLast,
  ringMachineIds,
} from '../ringBuffer';

beforeEach(() => {
  clearRings();
});

describe('ring buffer', () => {
  it('wraps around and saturates count at cap', () => {
    const ring = createRing(1, 4);
    for (let i = 0; i < 6; i += 1) pushSample(ring, 1000 + i, [i]);

    expect(ring.count).toBe(4);
    expect(ring.write).toBe(2);
    expect(lastValue(ring, 0)).toBe(5);
  });

  it('reads the last N in chronological order across the wrap boundary', () => {
    const ring = createRing(2, 4);
    for (let i = 0; i < 6; i += 1) pushSample(ring, 1000 + i, [i, i * 10]);

    const { datasetTsMs, series } = readLast(ring, 4);
    expect([...datasetTsMs]).toEqual([1002, 1003, 1004, 1005]);
    expect([...(series[0] ?? [])]).toEqual([2, 3, 4, 5]);
    expect([...(series[1] ?? [])]).toEqual([20, 30, 40, 50]);
  });

  it('reads fewer samples than requested when the ring is not full', () => {
    const ring = createRing(1, 8);
    pushSample(ring, 10, [1]);
    pushSample(ring, 20, [2]);

    const { datasetTsMs } = readLast(ring, 5);
    expect([...datasetTsMs]).toEqual([10, 20]);
    expect(readLast(ring, 0).datasetTsMs).toHaveLength(0);
  });

  it('writes null as NaN so charts draw a gap, never a zero', () => {
    const ring = createRing(2, 4);
    pushSample(ring, 10, [1, null]);
    pushSample(ring, 20, [null, 2]);

    const { series } = readLast(ring, 2);
    expect(Number.isNaN(series[1]?.[0] ?? 0)).toBe(true);
    expect(Number.isNaN(series[0]?.[1] ?? 0)).toBe(true);
    expect(series[0]?.[0]).toBe(1);
  });

  it('writes NaN for channels the frame did not carry', () => {
    const ring = createRing(3, 2);
    pushSample(ring, 10, [1]);
    expect(Number.isNaN(lastValue(ring, 2))).toBe(true);
    expect(Number.isNaN(lastValue(ring, 99))).toBe(true);
  });

  it('returns NaN for the last value of an empty ring', () => {
    expect(Number.isNaN(lastValue(createRing(1, 4), 0))).toBe(true);
  });

  it('sizes from plant.channels.length, not a hardcoded channel count', () => {
    for (const plantId of ['ai4i', 'ims'] as const) {
      const plant = makePlant(plantId);
      const machineIds = Array.from(
        { length: plant.machine_count },
        (_, index) => `${plantId}-${String(index + 1).padStart(2, '0')}`,
      );
      allocateRings(machineIds, plant.channels.length, 16);

      expect(ringMachineIds()).toHaveLength(plant.machine_count);
      const first = machineIds[0] ?? '';
      expect(getTelemetryRing(first)?.series).toHaveLength(plant.channels.length);
      expect(getRiskRing(first)?.series).toHaveLength(1);
    }
    // The two plants really do differ, so the assertion above has teeth.
    expect(makePlant('ai4i').channels.length).not.toBe(makePlant('ims').channels.length);
  });

  it('allocates nothing per push: 10 000 samples, same array identities', () => {
    const ring = createRing(3, 128);
    const identities = ring.series.map((series) => series);
    const stamps = ring.datasetTsMs;

    for (let i = 0; i < 10_000; i += 1) pushSample(ring, i, [i, i + 1, i + 2]);

    expect(ring.datasetTsMs).toBe(stamps);
    ring.series.forEach((series, index) => expect(series).toBe(identities[index]));
    expect(ring.count).toBe(128);
  });

  it('drops every buffer on clear', () => {
    allocateRings(['ai4i-01'], 7, 8);
    clearRings();
    expect(getTelemetryRing('ai4i-01')).toBeUndefined();
    expect(getRiskRing('ai4i-01')).toBeUndefined();
  });
});
