import type { ConfigResponse } from '@/contracts';
import type { SliceCreator } from './types';

/**
 * The backend-owned numbers the shell reads at runtime: `api.ws_ping_seconds`
 * (→ the derived liveness timeout), `api.sparkline_points`, `explanation.top_k`,
 * `replay.allowed_speeds`, the severity bands, and the rest of the flattened
 * settings tree. None of them is a frontend constant (frontend.md §1.1).
 */
export type ConfigSlice = {
  config: ConfigResponse | null;
  applyConfig: (config: ConfigResponse) => void;
};

export const createConfigSlice: SliceCreator<ConfigSlice> = (set) => ({
  config: null,
  applyConfig: (config) => set({ config }),
});
