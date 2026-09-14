/**
 * The staging buffer and the single rAF commit loop (frontend.md §1.1).
 *
 * Inbound frames are decoded and written synchronously — telemetry and risk
 * samples go straight into the pre-allocated ring buffers, which never allocate
 * — while everything React needs to know about is coalesced here and committed
 * from one `requestAnimationFrame` callback. At 20x with 12 machines the socket
 * delivers ~10 batched frames a second; React hears about them at most once per
 * frame.
 */
import type { Alert, Explanation, RiskUpdate } from '@/contracts';

export type StagedCommit = {
  /** Machines whose telemetry ring was written since the last commit. */
  telemetryDirty: string[];
  /** Machines whose risk ring was written since the last commit. */
  riskDirty: string[];
  /** Last risk update per machine — scalars are last-value-wins. */
  riskUpdates: RiskUpdate[];
  alerts: Alert[];
  explanations: Explanation[];
  /** Newest dataset clock seen in this batch, epoch-ms, or NaN. */
  datasetTsMs: number;
};

export type StagingBuffer = {
  markTelemetry: (machineId: string) => void;
  markRisk: (machineId: string) => void;
  stageRisk: (update: RiskUpdate) => void;
  stageAlert: (alert: Alert) => void;
  stageExplanation: (explanation: Explanation) => void;
  noteDatasetTsMs: (datasetTsMs: number) => void;
  isEmpty: () => boolean;
  /** Drain the buffer. The returned object is the only allocation per commit. */
  take: () => StagedCommit;
};

export function createStagingBuffer(): StagingBuffer {
  const telemetryDirty = new Set<string>();
  const riskDirty = new Set<string>();
  const riskUpdates = new Map<string, RiskUpdate>();
  let alerts: Alert[] = [];
  let explanations: Explanation[] = [];
  let datasetTsMs = Number.NaN;

  return {
    markTelemetry: (machineId) => telemetryDirty.add(machineId),
    markRisk: (machineId) => riskDirty.add(machineId),
    stageRisk: (update) => riskUpdates.set(update.machine_id, update),
    stageAlert: (alert) => alerts.push(alert),
    stageExplanation: (explanation) => explanations.push(explanation),
    noteDatasetTsMs: (value) => {
      if (Number.isNaN(datasetTsMs) || value > datasetTsMs) datasetTsMs = value;
    },
    isEmpty: () =>
      telemetryDirty.size === 0 &&
      riskDirty.size === 0 &&
      riskUpdates.size === 0 &&
      alerts.length === 0 &&
      explanations.length === 0,
    take: () => {
      const commit: StagedCommit = {
        telemetryDirty: [...telemetryDirty],
        riskDirty: [...riskDirty],
        riskUpdates: [...riskUpdates.values()],
        alerts,
        explanations,
        datasetTsMs,
      };
      telemetryDirty.clear();
      riskDirty.clear();
      riskUpdates.clear();
      alerts = [];
      explanations = [];
      datasetTsMs = Number.NaN;
      return commit;
    },
  };
}

export type CommitLoop = {
  /** Ask for a commit on the next animation frame; repeated calls coalesce. */
  schedule: () => void;
  /** Commit now, synchronously. Used on `visibilitychange` and on teardown. */
  flush: () => void;
  dispose: () => void;
};

export type CommitLoopDeps = {
  staging: StagingBuffer;
  commit: (batch: StagedCommit) => void;
  requestFrame?: (callback: FrameRequestCallback) => number;
  cancelFrame?: (handle: number) => void;
  /** Injected so the hidden-tab path is testable without a real document. */
  visibility?: Pick<Document, 'addEventListener' | 'removeEventListener'> & {
    visibilityState: DocumentVisibilityState;
  };
};

/**
 * One commit per animation frame. When the tab is hidden the browser stops
 * firing rAF, so the staging buffer coalesces unboundedly-but-boundedly (the
 * ring buffers are fixed size, so memory stays flat) and one commit happens on
 * the way back to visible.
 */
export function createCommitLoop(deps: CommitLoopDeps): CommitLoop {
  const requestFrame =
    deps.requestFrame ?? ((callback: FrameRequestCallback) => requestAnimationFrame(callback));
  const cancelFrame = deps.cancelFrame ?? ((handle: number) => cancelAnimationFrame(handle));
  const visibility =
    deps.visibility ?? (typeof document === 'undefined' ? undefined : document);
  let handle: number | null = null;

  const run = (): void => {
    handle = null;
    if (deps.staging.isEmpty()) return;
    deps.commit(deps.staging.take());
  };

  const schedule = (): void => {
    if (handle !== null) return;
    handle = requestFrame(run);
  };

  const flush = (): void => {
    if (handle !== null) {
      cancelFrame(handle);
      handle = null;
    }
    if (!deps.staging.isEmpty()) deps.commit(deps.staging.take());
  };

  const onVisibilityChange = (): void => {
    if (visibility && visibility.visibilityState === 'visible') flush();
  };

  visibility?.addEventListener('visibilitychange', onVisibilityChange);

  return {
    schedule,
    flush,
    dispose: () => {
      if (handle !== null) {
        cancelFrame(handle);
        handle = null;
      }
      visibility?.removeEventListener('visibilitychange', onVisibilityChange);
    },
  };
}
