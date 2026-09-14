/**
 * The WebSocket client (frontend.md §1.1, §3.2).
 *
 * Contract, in full: the URL is `/ws?plant_id=<ai4i|ims>` and that query
 * parameter is the complete subscription — there is no `subscribe` frame, no
 * resume, no `seq` cursor and no client-initiated ping (R10, R11). The server
 * sends `hello` then `snapshot` on every connect and the client rebuilds state
 * wholesale from them. The only frame the client ever sends is `pong`.
 */
import { wsSilenceTimeoutMs } from '@/config';
import type { PlantId, ServerFrame } from '@/contracts';
import { parseDatasetTs } from '@/lib/formatters';
import { useStore } from '@/store';
import {
  allocateRings,
  getRiskRing,
  getTelemetryRing,
  pushSample,
} from '@/store/ringBuffer';
import {
  createCommitLoop,
  createStagingBuffer,
  type CommitLoop,
  type StagedCommit,
  type StagingBuffer,
} from './backpressure';
import { backoffDelayMs } from './reconnect';

/** The subset of `WebSocket` this client uses, so tests can supply their own. */
export type SocketLike = {
  send: (data: string) => void;
  close: () => void;
  onopen: ((event: unknown) => void) | null;
  onclose: ((event: unknown) => void) | null;
  onerror: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
};

export type WsClientDeps = {
  socketFactory?: (url: string) => SocketLike;
  /** Absolute or relative base for the socket URL; defaults to the page origin. */
  origin?: string;
  now?: () => number;
  random?: () => number;
  requestFrame?: (callback: FrameRequestCallback) => number;
  cancelFrame?: (handle: number) => void;
};

export type WsClient = {
  connect: (plantId: PlantId) => void;
  /** Close for good: no reconnect, no timers left running. */
  disconnect: () => void;
  /** Commit any staged frames immediately. */
  flush: () => void;
  currentUrl: () => string | null;
};

/** How often liveness is checked; the timeout itself is derived from config. */
const LIVENESS_TICK_MS = 1000;

export function wsUrl(plantId: PlantId, origin?: string): string {
  const base =
    origin ??
    (typeof window === 'undefined' ? 'http://localhost' : window.location.origin);
  const url = new URL('/ws', base);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('plant_id', plantId);
  return url.toString();
}

export function createWsClient(deps: WsClientDeps = {}): WsClient {
  const now = deps.now ?? (() => Date.now());
  const random = deps.random ?? Math.random;
  const socketFactory =
    deps.socketFactory ?? ((url: string) => new WebSocket(url) as unknown as SocketLike);

  const staging: StagingBuffer = createStagingBuffer();
  const loop: CommitLoop = createCommitLoop({
    staging,
    commit: commitBatch,
    ...(deps.requestFrame ? { requestFrame: deps.requestFrame } : {}),
    ...(deps.cancelFrame ? { cancelFrame: deps.cancelFrame } : {}),
  });

  let socket: SocketLike | null = null;
  let url: string | null = null;
  let plant: PlantId | null = null;
  let attempt = 0;
  let closedByUs = false;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let livenessTimer: ReturnType<typeof setInterval> | null = null;

  function clearReconnectTimer(): void {
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  }

  function clearLivenessTimer(): void {
    if (livenessTimer !== null) {
      clearInterval(livenessTimer);
      livenessTimer = null;
    }
  }

  function startLiveness(): void {
    clearLivenessTimer();
    livenessTimer = setInterval(() => {
      const state = useStore.getState();
      const timeout = wsSilenceTimeoutMs(state.config?.values ?? null);
      const since = now() - state.connection.lastMessageAt;
      if (state.connection.lastMessageAt > 0 && since > timeout) {
        // Silence beyond 2.5 heartbeats: the socket is dead even if the browser
        // has not noticed. Drop it and rebuild from a fresh hello + snapshot.
        forceReconnect();
      }
    }, LIVENESS_TICK_MS);
  }

  function forceReconnect(): void {
    if (!socket) return;
    const dying = socket;
    socket = null;
    dying.onopen = null;
    dying.onclose = null;
    dying.onerror = null;
    dying.onmessage = null;
    try {
      dying.close();
    } catch {
      // A socket that throws on close is already gone; the retry path is the same.
    }
    scheduleReconnect();
  }

  function scheduleReconnect(): void {
    if (closedByUs || plant === null) return;
    clearLivenessTimer();
    attempt += 1;
    useStore.getState().setConnectionStatus('reconnecting', attempt);
    const delay = backoffDelayMs(attempt - 1, random);
    clearReconnectTimer();
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      if (plant !== null) open(plant);
    }, delay);
  }

  function open(plantId: PlantId): void {
    url = wsUrl(plantId, deps.origin);
    const next = socketFactory(url);
    socket = next;
    useStore
      .getState()
      .setConnectionStatus(attempt === 0 ? 'connecting' : 'reconnecting', attempt);

    next.onopen = () => {
      attempt = 0;
      const state = useStore.getState();
      state.setConnectionStatus('open', 0);
      state.setConnectionError(null);
      state.noteMessageReceived(now());
      startLiveness();
    };
    next.onmessage = (event) => {
      useStore.getState().noteMessageReceived(now());
      handleRaw(event.data, next);
    };
    next.onclose = () => {
      if (socket !== next) return;
      socket = null;
      if (closedByUs) {
        useStore.getState().setConnectionStatus('closed', 0);
        return;
      }
      scheduleReconnect();
    };
    next.onerror = () => {
      // `close` always follows `error`; reconnecting here would double-schedule.
    };
  }

  function handleRaw(data: unknown, from: SocketLike): void {
    if (typeof data !== 'string') return;
    let parsed: unknown;
    try {
      parsed = JSON.parse(data);
    } catch {
      // A frame that is not JSON is not ours to interpret.
      return;
    }
    if (!isServerFrame(parsed)) {
      // Unknown `type` values are ignored silently: this is what lets the
      // backend add a frame type without a lockstep frontend release (§3.2).
      return;
    }
    handleFrame(parsed, from);
  }

  function handleFrame(frame: ServerFrame, from: SocketLike): void {
    const store = useStore.getState();
    switch (frame.type) {
      case 'hello': {
        store.upsertPlant(frame.plant);
        store.selectPlant(frame.plant.plant_id);
        store.setChannels(frame.plant.channels);
        store.setRunId(frame.run_id);
        return;
      }
      case 'snapshot': {
        const channels = useStore.getState().machines.channels;
        const machineIds = frame.machines.map((machine) => machine.machine_id);
        // Sized from the plant's channel list and the snapshot's machine list —
        // never a hardcoded channel or machine count.
        allocateRings(machineIds, channels.length);
        store.seedMachines(frame.machines);
        store.resetTelemetryRevisions(machineIds);
        store.resetRiskRevisions(machineIds);
        for (const machine of frame.machines) {
          const ring = getTelemetryRing(machine.machine_id);
          const at = parseDatasetTs(machine.dataset_ts);
          // One seed sample per machine, positional against Plant.channels, so
          // the charts have data before the first telemetry frame.
          if (ring && !Number.isNaN(at)) pushSample(ring, at, machine.values);
          const riskRing = getRiskRing(machine.machine_id);
          if (riskRing && !Number.isNaN(at) && machine.probability !== null) {
            pushSample(riskRing, at, [machine.probability]);
          }
        }
        store.bumpTelemetryRevisions(machineIds);
        store.bumpRiskRevisions(machineIds);
        store.resetAlerts();
        store.addAlerts(frame.active_alerts);
        store.setRunId(frame.run_id);
        store.applyReplayState(stripType(frame.replay_state));
        store.setDatasetTsMs(parseDatasetTs(frame.dataset_ts));
        return;
      }
      case 'telemetry': {
        for (const update of frame.updates) {
          const ring = getTelemetryRing(update.machine_id);
          if (!ring) continue;
          const at = parseDatasetTs(update.dataset_ts);
          pushSample(ring, at, update.values);
          staging.markTelemetry(update.machine_id);
          staging.noteDatasetTsMs(at);
        }
        loop.schedule();
        return;
      }
      case 'risk': {
        for (const update of frame.updates) {
          const at = parseDatasetTs(update.dataset_ts);
          const ring = getRiskRing(update.machine_id);
          if (ring) {
            pushSample(ring, at, [update.probability]);
            staging.markRisk(update.machine_id);
          }
          staging.stageRisk(update);
          staging.noteDatasetTsMs(at);
        }
        loop.schedule();
        return;
      }
      case 'alert': {
        staging.stageAlert(stripType(frame));
        loop.schedule();
        return;
      }
      case 'explanation': {
        staging.stageExplanation(stripType(frame));
        loop.schedule();
        return;
      }
      case 'replay_state': {
        store.applyReplayState(stripType(frame));
        return;
      }
      case 'config': {
        store.applyConfig(stripType(frame));
        return;
      }
      case 'ping': {
        // Server-initiated heartbeat, regardless of replay state (R11): a paused
        // replay must never look like a dead socket.
        from.send(JSON.stringify({ type: 'pong', ts: new Date(now()).toISOString() }));
        return;
      }
      case 'error': {
        if (frame.code === 'backpressure_dropped') {
          store.setConnectionDegraded(true);
        } else {
          store.setConnectionError(frame.message);
        }
        return;
      }
      default:
        assertNever(frame);
    }
  }

  return {
    connect: (plantId) => {
      closedByUs = false;
      clearReconnectTimer();
      if (socket) {
        const dying = socket;
        socket = null;
        dying.onclose = null;
        dying.close();
      }
      attempt = 0;
      plant = plantId;
      open(plantId);
    },
    disconnect: () => {
      closedByUs = true;
      plant = null;
      clearReconnectTimer();
      clearLivenessTimer();
      loop.flush();
      loop.dispose();
      if (socket) {
        const dying = socket;
        socket = null;
        dying.close();
      }
      useStore.getState().setConnectionStatus('closed', 0);
    },
    flush: () => loop.flush(),
    currentUrl: () => url,
  };
}

/** Apply one coalesced batch. This is the only place React hears about frames. */
function commitBatch(batch: StagedCommit): void {
  const store = useStore.getState();
  if (batch.telemetryDirty.length > 0) store.bumpTelemetryRevisions(batch.telemetryDirty);
  if (batch.riskDirty.length > 0) store.bumpRiskRevisions(batch.riskDirty);
  if (batch.riskUpdates.length > 0) store.applyRiskUpdates(batch.riskUpdates);
  if (batch.alerts.length > 0) store.addAlerts(batch.alerts, { unseen: true });
  for (const explanation of batch.explanations) store.putExplanation(explanation);
  if (!Number.isNaN(batch.datasetTsMs)) store.setDatasetTsMs(batch.datasetTsMs);
}

/** The ten frame types the protocol defines; anything else is ignored. */
const SERVER_FRAME_TYPES: ReadonlySet<string> = new Set<ServerFrame['type']>([
  'hello',
  'snapshot',
  'telemetry',
  'risk',
  'alert',
  'explanation',
  'replay_state',
  'config',
  'ping',
  'error',
]);

function isServerFrame(value: unknown): value is ServerFrame {
  if (typeof value !== 'object' || value === null) return false;
  const type: unknown = (value as { type?: unknown }).type;
  return typeof type === 'string' && SERVER_FRAME_TYPES.has(type);
}

/** Frames that spread a REST model carry an extra `type`; the store wants the model. */
function stripType<T extends { type: string }>(frame: T): Omit<T, 'type'>;
function stripType<T extends object>(value: T): T;
function stripType(value: object): object {
  if (!('type' in value)) return value;
  const { type: _type, ...rest } = value as { type: string } & Record<string, unknown>;
  return rest;
}

/** Exhaustiveness guard for the handled subset (§3.2.1). */
function assertNever(_frame: never): void {
  // Unreachable: every ServerFrame type is handled above, and anything outside
  // the union never reaches this switch.
}
