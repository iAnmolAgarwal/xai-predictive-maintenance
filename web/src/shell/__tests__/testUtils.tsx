import { render, type RenderResult } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router';
import { PLANTS, makeConfig, makeSnapshotMachines } from '@/mock/fixtures';
import { useStore } from '@/store';

/** Render inside a router, which every shell surface assumes. */
export function renderWithRouter(
  ui: ReactElement,
  initialEntries: string[] = ['/'],
): RenderResult {
  return render(<MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>);
}

/** Put the store in the state a `hello` + `snapshot` pair would leave it in. */
export function seedStore(plantId: 'ai4i' | 'ims' = 'ai4i'): void {
  const store = useStore.getState();
  const plant = PLANTS.find((entry) => entry.plant_id === plantId);
  if (!plant) throw new Error('fixture missing');
  store.applyConfig(makeConfig());
  store.setPlants(PLANTS);
  store.selectPlant(plantId);
  store.setChannels(plant.channels);
  store.seedMachines(makeSnapshotMachines(plantId, 4));
  store.setRunId('run_1a2b3c4d5e6f');
  store.setConnectionStatus('open', 0);
}

/** Drive the media query the rail breakpoint reads. */
export function stubViewport(matches: boolean): void {
  window.matchMedia = (query: string) => ({
    matches: query.includes('min-width') ? matches : false,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  });
}
