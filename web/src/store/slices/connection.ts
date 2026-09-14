import type { SliceCreator } from './types';

export type ConnStatus = 'connecting' | 'open' | 'reconnecting' | 'closed';

export type ConnectionSlice = {
  connection: {
    status: ConnStatus;
    attempt: number;
    /** epoch-ms; the ONLY liveness signal (R10). */
    lastMessageAt: number;
    /** set by an `error` frame with `code === "backpressure_dropped"`. */
    degraded: boolean;
    error: string | null;
  };
  setConnectionStatus: (status: ConnStatus, attempt?: number) => void;
  noteMessageReceived: (atMs: number) => void;
  setConnectionDegraded: (degraded: boolean) => void;
  setConnectionError: (error: string | null) => void;
};

export const createConnectionSlice: SliceCreator<ConnectionSlice> = (set) => ({
  connection: {
    status: 'connecting',
    attempt: 0,
    lastMessageAt: 0,
    degraded: false,
    error: null,
  },
  setConnectionStatus: (status, attempt) =>
    set((state) => ({
      connection: {
        ...state.connection,
        status,
        attempt: attempt ?? state.connection.attempt,
        // A healthy open clears the degraded treatment; the next error frame
        // sets it again.
        degraded: status === 'open' ? false : state.connection.degraded,
      },
    })),
  noteMessageReceived: (atMs) =>
    set((state) => ({ connection: { ...state.connection, lastMessageAt: atMs } })),
  setConnectionDegraded: (degraded) =>
    set((state) => ({ connection: { ...state.connection, degraded } })),
  setConnectionError: (error) =>
    set((state) => ({ connection: { ...state.connection, error } })),
});
