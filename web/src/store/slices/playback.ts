import type { Explanation, MachineSummary, ReplayState, Speed } from '@/contracts';
import { parseDatasetTs } from '@/lib/formatters';
import type { SliceCreator } from './types';

export type HistoricalState = {
  datasetTsMs: number;
  machines: Record<string, MachineSummary>;
  /** Derived client-side from a `PlantSnapshot` (frontend.md §3.1). */
  explanationByMachineId: Record<string, Explanation | null>;
};

export type PlaybackSlice = {
  playback: {
    /** From `hello` / `replay_state`; a loop increments it (R12). */
    runId: string | null;
    playing: boolean;
    speed: Speed;
    datasetTsMs: number;
    spanMs: { start: number; end: number };
    scrubbing: boolean;
    /** Local and optimistic while dragging. */
    scrubDatasetTsMs: number | null;
    historical: HistoricalState | null;
  };
  setRunId: (runId: string) => void;
  /** Reconcile optimistic transport state against the authoritative frame. */
  applyReplayState: (replayState: ReplayState) => void;
  setPlayingOptimistic: (playing: boolean) => void;
  setSpeedOptimistic: (speed: Speed) => void;
  setDatasetTsMs: (datasetTsMs: number) => void;
  setScrubbing: (scrubbing: boolean, datasetTsMs?: number | null) => void;
  setHistorical: (historical: HistoricalState | null) => void;
};

export const createPlaybackSlice: SliceCreator<PlaybackSlice> = (set) => ({
  playback: {
    runId: null,
    playing: false,
    speed: 1,
    datasetTsMs: Number.NaN,
    spanMs: { start: Number.NaN, end: Number.NaN },
    scrubbing: false,
    scrubDatasetTsMs: null,
    historical: null,
  },
  setRunId: (runId) => set((state) => ({ playback: { ...state.playback, runId } })),
  applyReplayState: (replayState) =>
    set((state) => ({
      playback: {
        ...state.playback,
        runId: replayState.run_id,
        playing: replayState.playing,
        speed: replayState.speed,
        datasetTsMs: parseDatasetTs(replayState.dataset_ts),
        spanMs: {
          start: parseDatasetTs(replayState.dataset_start),
          end: parseDatasetTs(replayState.dataset_end),
        },
      },
    })),
  setPlayingOptimistic: (playing) =>
    set((state) => ({ playback: { ...state.playback, playing } })),
  setSpeedOptimistic: (speed) =>
    set((state) => ({ playback: { ...state.playback, speed } })),
  setDatasetTsMs: (datasetTsMs) =>
    set((state) =>
      // The dataset clock only ever moves forward from a risk update while the
      // user is not scrubbing.
      state.playback.scrubbing ? {} : { playback: { ...state.playback, datasetTsMs } },
    ),
  setScrubbing: (scrubbing, datasetTsMs) =>
    set((state) => ({
      playback: {
        ...state.playback,
        scrubbing,
        scrubDatasetTsMs:
          datasetTsMs === undefined ? state.playback.scrubDatasetTsMs : datasetTsMs,
      },
    })),
  setHistorical: (historical) =>
    set((state) => ({ playback: { ...state.playback, historical } })),
});
