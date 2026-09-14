import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { resetStore, useStore } from '@/store';
import { PLANTS } from '@/mock/fixtures';
import { Slot, SLOT_NAMES, clearSlots, getSlotComponent, registerSlot } from '../slots';

beforeEach(() => {
  resetStore();
  clearSlots();
});

afterEach(() => {
  clearSlots();
});

describe('slot registry', () => {
  it('fixes the seven slot names in Phase 3', () => {
    expect([...SLOT_NAMES]).toEqual([
      'topbar.playback',
      'rail.feed',
      'detail.shap',
      'detail.whatif',
      'detail.compare',
      'floor.grid',
      'detail.charts',
    ]);
  });

  it('renders a registered feature and passes its props through', () => {
    registerSlot('rail.feed', (props) => (
      <p data-testid="registered-feed">{String(props.machineId)}</p>
    ));
    expect(getSlotComponent('rail.feed')).toBeDefined();

    render(<Slot name="rail.feed" machineId="ai4i-03" />);
    expect(screen.getByTestId('registered-feed')).toHaveTextContent('ai4i-03');
  });

  it('renders the designed empty state for every unfilled slot', () => {
    for (const name of SLOT_NAMES) {
      if (name === 'floor.grid') continue;
      const { unmount } = render(<Slot name={name} />);
      const empty = screen.getByTestId(`empty-${name.replace('.', '-')}`);
      expect(empty.textContent?.length ?? 0).toBeGreaterThan(10);
      unmount();
    }
  });

  it('draws one placeholder per machine_count before the grid feature lands', () => {
    useStore.getState().setPlants(PLANTS);
    useStore.getState().selectPlant('ims');
    render(<Slot name="floor.grid" />);

    expect(screen.getByTestId('machine-grid')).toBeInTheDocument();
    expect(screen.getAllByTestId(/^floor-placeholder-tile-/)).toHaveLength(4);
    expect(screen.getByTestId('empty-floor-grid')).toHaveTextContent('4 machines');
  });

  it('names each placeholder from the snapshot once machines are known', () => {
    useStore.getState().setPlants(PLANTS);
    useStore.getState().selectPlant('ai4i');
    useStore.getState().seedMachines([
      {
        machine_id: 'ai4i-01',
        plant_id: 'ai4i',
        display_name: 'Mill 01',
        status: 'healthy',
        probability: 0.1,
        dataset_ts: '2026-01-01T00:00:00.000Z',
        open_alert_id: null,
        risk_sparkline: [],
        values: [],
      },
    ]);
    render(<Slot name="floor.grid" />);
    expect(screen.getByTestId('floor-placeholder-tile-ai4i-01')).toHaveTextContent(
      'Mill 01',
    );
  });

  it('says so plainly when the plant reports no machines', () => {
    render(<Slot name="floor.grid" />);
    expect(screen.getByTestId('empty-floor-grid')).toHaveTextContent('No machines');
  });
});
