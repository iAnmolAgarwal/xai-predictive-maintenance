import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { resetStore, useStore } from '@/store';
import { PLANTS, makeAlert, makeSnapshotMachines } from '@/mock/fixtures';
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
    // Empty states only make sense once boot has succeeded.
    useStore.getState().setPlants(PLANTS);
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
    useStore.getState().seedMachines(makeSnapshotMachines('ims', 0));
    render(<Slot name="floor.grid" />);

    expect(screen.getByTestId('floor-placeholder-grid')).toBeInTheDocument();
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
    const [plant] = PLANTS;
    if (!plant) throw new Error('fixture missing');
    useStore.getState().setPlants([{ ...plant, machine_count: 0 }]);
    render(<Slot name="floor.grid" />);
    expect(screen.getByTestId('empty-floor-grid')).toHaveTextContent('No machines');
  });

  it('holds the region with skeletons until the first descriptor arrives', () => {
    render(<Slot name="floor.grid" />);
    expect(screen.getByTestId('skeleton-floor-grid')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-floor-grid')).not.toBeInTheDocument();
  });

  it('never claims a healthy empty plant while the API is unreachable', async () => {
    const user = userEvent.setup();
    useStore.getState().setConnectionError('Cannot reach the API. Failed to fetch');

    for (const name of SLOT_NAMES) {
      const area = name.replace('.', '-');
      const { unmount } = render(<Slot name={name} />);
      const node = screen.getByTestId(`error-${area}`);
      expect(node).toHaveTextContent(/unreachable|Can't reach the API/);
      expect(screen.queryByTestId(`empty-${area}`)).not.toBeInTheDocument();
      unmount();
    }

    // Every region offers the same recovery, and it goes through the store.
    render(<Slot name="rail.feed" />);
    const before = useStore.getState().connection.bootAttempt;
    await user.click(screen.getByRole('button', { name: 'Retry now' }));
    expect(useStore.getState().connection.bootAttempt).toBe(before + 1);
  });

  it('tells the truth about alerts it holds but cannot render yet', () => {
    useStore.getState().setPlants(PLANTS);
    useStore.getState().addAlerts([makeAlert('ai4i', 'ai4i-03', 6)], { unseen: true });
    render(<Slot name="rail.feed" />);

    const empty = screen.getByTestId('empty-rail-feed');
    expect(empty).toHaveTextContent('1 alert in this run');
    expect(empty).not.toHaveTextContent('No alerts yet');
  });
});
