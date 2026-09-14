import type { ModelKind, WhatIfResponse } from '@/contracts';
import type { SliceCreator } from './types';

export type WhatIfSlice = {
  whatif: {
    alertId: string | null;
    model: ModelKind;
    overrides: Record<string, number>;
    /** Local linear approximation from the last response's gradients. */
    optimistic: WhatIfResponse | null;
    authoritative: WhatIfResponse | null;
    gradients: Record<string, number>;
    inFlight: boolean;
    /** CLIENT-measured round trip — the GOAL definition-of-done number. */
    lastLatencyMs: number | null;
    /** Server-reported `WhatIfResponse.compute_ms`. */
    lastComputeMs: number | null;
    error: string | null;
  };
  setWhatIfAlert: (alertId: string | null, model?: ModelKind) => void;
  setWhatIfOverride: (feature: string, value: number) => void;
  clearWhatIfOverride: (feature: string) => void;
  resetWhatIfOverrides: () => void;
  setWhatIfOptimistic: (response: WhatIfResponse | null) => void;
  setWhatIfAuthoritative: (response: WhatIfResponse, latencyMs: number) => void;
  setWhatIfInFlight: (inFlight: boolean) => void;
  setWhatIfError: (error: string | null) => void;
};

const emptyWhatIf = (model: ModelKind): WhatIfSlice['whatif'] => ({
  alertId: null,
  model,
  overrides: {},
  optimistic: null,
  authoritative: null,
  gradients: {},
  inFlight: false,
  lastLatencyMs: null,
  lastComputeMs: null,
  error: null,
});

export const createWhatIfSlice: SliceCreator<WhatIfSlice> = (set) => ({
  whatif: emptyWhatIf('lgbm'),
  setWhatIfAlert: (alertId, model) =>
    set((state) => ({
      whatif: { ...emptyWhatIf(model ?? state.whatif.model), alertId },
    })),
  setWhatIfOverride: (feature, value) =>
    set((state) => ({
      whatif: {
        ...state.whatif,
        overrides: { ...state.whatif.overrides, [feature]: value },
      },
    })),
  clearWhatIfOverride: (feature) =>
    set((state) => {
      const overrides = { ...state.whatif.overrides };
      delete overrides[feature];
      return { whatif: { ...state.whatif, overrides } };
    }),
  resetWhatIfOverrides: () =>
    set((state) => ({ whatif: { ...state.whatif, overrides: {} } })),
  setWhatIfOptimistic: (response) =>
    set((state) => ({ whatif: { ...state.whatif, optimistic: response } })),
  setWhatIfAuthoritative: (response, latencyMs) =>
    set((state) => ({
      whatif: {
        ...state.whatif,
        authoritative: response,
        optimistic: null,
        gradients: response.gradients,
        lastLatencyMs: latencyMs,
        lastComputeMs: response.compute_ms,
        inFlight: false,
        error: null,
      },
    })),
  setWhatIfInFlight: (inFlight) =>
    set((state) => ({ whatif: { ...state.whatif, inFlight } })),
  setWhatIfError: (error) =>
    set((state) => ({ whatif: { ...state.whatif, error, inFlight: false } })),
});
