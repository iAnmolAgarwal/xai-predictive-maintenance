import { describe, expect, it, vi } from 'vitest';
import type { RiskUpdate } from '@/contracts';
import { createCommitLoop, createStagingBuffer } from '../backpressure';

const riskUpdate = (machineId: string, probability: number): RiskUpdate => ({
  machine_id: machineId,
  dataset_ts: '2026-01-01T00:00:00.000Z',
  probability,
  status: 'watch',
  alert_id: null,
  model_id: 'lgbm@1.0.0',
  top_features: [],
});

describe('staging buffer', () => {
  it('coalesces per machine: last value wins for scalars', () => {
    const staging = createStagingBuffer();
    staging.stageRisk(riskUpdate('ai4i-01', 0.1));
    staging.stageRisk(riskUpdate('ai4i-01', 0.9));
    staging.stageRisk(riskUpdate('ai4i-02', 0.2));

    const batch = staging.take();
    expect(batch.riskUpdates).toHaveLength(2);
    expect(batch.riskUpdates[0]?.probability).toBe(0.9);
    expect(staging.isEmpty()).toBe(true);
  });

  it('dedupes dirty machines and keeps the newest dataset clock', () => {
    const staging = createStagingBuffer();
    for (let i = 0; i < 500; i += 1) staging.markTelemetry('ai4i-01');
    staging.markTelemetry('ai4i-02');
    staging.markRisk('ai4i-01');
    staging.noteDatasetTsMs(10);
    staging.noteDatasetTsMs(5);
    staging.noteDatasetTsMs(20);

    const batch = staging.take();
    expect(batch.telemetryDirty).toEqual(['ai4i-01', 'ai4i-02']);
    expect(batch.riskDirty).toEqual(['ai4i-01']);
    expect(batch.datasetTsMs).toBe(20);
  });

  it('collects alerts and explanations in arrival order', () => {
    const staging = createStagingBuffer();
    expect(staging.isEmpty()).toBe(true);
    staging.stageAlert({ alert_id: 'alt_1' } as never);
    staging.stageExplanation({ alert_id: 'alt_1' } as never);
    expect(staging.isEmpty()).toBe(false);

    const batch = staging.take();
    expect(batch.alerts).toHaveLength(1);
    expect(batch.explanations).toHaveLength(1);
    expect(Number.isNaN(batch.datasetTsMs)).toBe(true);
  });
});

describe('commit loop', () => {
  function harness() {
    const frames: FrameRequestCallback[] = [];
    const staging = createStagingBuffer();
    const commit = vi.fn();
    const listeners = new Map<string, EventListener>();
    const visibility = {
      visibilityState: 'visible' as DocumentVisibilityState,
      addEventListener: (type: string, listener: EventListener) =>
        listeners.set(type, listener),
      removeEventListener: (type: string) => listeners.delete(type),
    };
    const loop = createCommitLoop({
      staging,
      commit,
      requestFrame: (callback) => frames.push(callback),
      cancelFrame: () => frames.splice(0, frames.length),
      visibility,
    });
    const runFrame = (): void => {
      const pending = frames.splice(0, frames.length);
      pending.forEach((callback) => callback(0));
    };
    return { loop, staging, commit, runFrame, listeners, visibility, frames };
  }

  it('commits exactly once for 500 updates inside one animation frame', () => {
    const { loop, staging, commit, runFrame } = harness();
    for (let i = 0; i < 500; i += 1) {
      staging.markTelemetry(`ai4i-${String((i % 12) + 1).padStart(2, '0')}`);
      loop.schedule();
    }
    expect(commit).not.toHaveBeenCalled();

    runFrame();
    expect(commit).toHaveBeenCalledTimes(1);
    expect(commit.mock.calls[0]?.[0].telemetryDirty).toHaveLength(12);
  });

  it('does not commit an empty batch', () => {
    const { loop, commit, runFrame } = harness();
    loop.schedule();
    runFrame();
    expect(commit).not.toHaveBeenCalled();

    loop.flush();
    expect(commit).not.toHaveBeenCalled();
  });

  it('commits once when a hidden tab becomes visible again', () => {
    const { loop, staging, commit, listeners, visibility, frames } = harness();
    // A hidden tab fires no animation frames, so the staging buffer just grows —
    // boundedly, because the ring buffers behind it are fixed size.
    staging.markTelemetry('ai4i-01');
    loop.schedule();
    expect(frames).toHaveLength(1);

    visibility.visibilityState = 'visible';
    listeners.get('visibilitychange')?.(new Event('visibilitychange'));
    expect(commit).toHaveBeenCalledTimes(1);
  });

  it('ignores a visibilitychange to hidden', () => {
    const { loop, staging, commit, listeners, visibility } = harness();
    staging.markTelemetry('ai4i-01');
    loop.schedule();
    visibility.visibilityState = 'hidden';
    listeners.get('visibilitychange')?.(new Event('visibilitychange'));
    expect(commit).not.toHaveBeenCalled();
  });

  it('stops scheduling and unsubscribes on dispose', () => {
    const { loop, staging, commit, listeners, runFrame } = harness();
    staging.markTelemetry('ai4i-01');
    loop.schedule();
    loop.dispose();
    expect(listeners.size).toBe(0);
    runFrame();
    expect(commit).not.toHaveBeenCalled();
  });
});
