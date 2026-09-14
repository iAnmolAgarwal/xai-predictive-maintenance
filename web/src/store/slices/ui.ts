import type { SliceCreator } from './types';

export type UiSlice = {
  ui: {
    selectedMachineId: string | null;
    selectedAlertId: string | null;
    /** Shared by the waterfall, the force plot and the sentence links. */
    hoveredFeature: string | null;
    railOpen: boolean;
    compareOpen: boolean;
    reducedMotion: boolean;
  };
  setSelectedMachineId: (machineId: string | null) => void;
  setSelectedAlertId: (alertId: string | null) => void;
  setHoveredFeature: (feature: string | null) => void;
  setRailOpen: (open: boolean) => void;
  toggleRail: () => void;
  setCompareOpen: (open: boolean) => void;
  setReducedMotion: (reduced: boolean) => void;
};

export const createUiSlice: SliceCreator<UiSlice> = (set) => ({
  ui: {
    selectedMachineId: null,
    selectedAlertId: null,
    hoveredFeature: null,
    railOpen: true,
    compareOpen: false,
    reducedMotion: false,
  },
  setSelectedMachineId: (machineId) =>
    set((state) => ({ ui: { ...state.ui, selectedMachineId: machineId } })),
  setSelectedAlertId: (alertId) =>
    set((state) => ({ ui: { ...state.ui, selectedAlertId: alertId } })),
  setHoveredFeature: (feature) =>
    set((state) => ({ ui: { ...state.ui, hoveredFeature: feature } })),
  setRailOpen: (open) => set((state) => ({ ui: { ...state.ui, railOpen: open } })),
  toggleRail: () => set((state) => ({ ui: { ...state.ui, railOpen: !state.ui.railOpen } })),
  setCompareOpen: (open) => set((state) => ({ ui: { ...state.ui, compareOpen: open } })),
  setReducedMotion: (reduced) =>
    set((state) => ({ ui: { ...state.ui, reducedMotion: reduced } })),
});
