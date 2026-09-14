import type { Explanation, GlobalImportance, ModelComparison } from '@/contracts';
import type { SliceCreator } from './types';

export type ExplanationsSlice = {
  explanations: {
    /** `model_kind: "lgbm"` — the served model. */
    byAlertId: Record<string, Explanation>;
    compareByAlertId: Record<string, ModelComparison>;
    importanceByMachineId: Record<string, GlobalImportance>;
    loading: Record<string, boolean>;
    error: Record<string, string | null>;
  };
  putExplanation: (explanation: Explanation) => void;
  putComparison: (comparison: ModelComparison) => void;
  putImportance: (importance: GlobalImportance) => void;
  setExplanationLoading: (key: string, loading: boolean) => void;
  setExplanationError: (key: string, error: string | null) => void;
};

export const createExplanationsSlice: SliceCreator<ExplanationsSlice> = (set) => ({
  explanations: {
    byAlertId: {},
    compareByAlertId: {},
    importanceByMachineId: {},
    loading: {},
    error: {},
  },
  putExplanation: (explanation) =>
    set((state) => ({
      explanations: {
        ...state.explanations,
        byAlertId: {
          ...state.explanations.byAlertId,
          [explanation.alert_id]: explanation,
        },
      },
    })),
  putComparison: (comparison) =>
    set((state) => ({
      explanations: {
        ...state.explanations,
        compareByAlertId: {
          ...state.explanations.compareByAlertId,
          [comparison.alert_id]: comparison,
        },
      },
    })),
  putImportance: (importance) =>
    set((state) => ({
      explanations: {
        ...state.explanations,
        importanceByMachineId: {
          ...state.explanations.importanceByMachineId,
          [importance.machine_id]: importance,
        },
      },
    })),
  setExplanationLoading: (key, loading) =>
    set((state) => ({
      explanations: {
        ...state.explanations,
        loading: { ...state.explanations.loading, [key]: loading },
      },
    })),
  setExplanationError: (key, error) =>
    set((state) => ({
      explanations: {
        ...state.explanations,
        error: { ...state.explanations.error, [key]: error },
      },
    })),
});
