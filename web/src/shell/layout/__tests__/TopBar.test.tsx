import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PLANTS } from '@/mock/fixtures';
import { resetStore, useStore } from '@/store';
import { clearSlots, registerSlot } from '../../slots';
import { renderWithRouter, seedStore } from '../../__tests__/testUtils';
import { TopBar } from '../TopBar';

beforeEach(() => {
  resetStore();
  clearSlots();
});

describe('TopBar', () => {
  it('renders the run id, dataset clock and live connection pill', () => {
    seedStore();
    useStore.getState().setDatasetTsMs(Date.parse('2026-01-02T10:45:00.000Z'));
    renderWithRouter(<TopBar railCollapsed={false} onToggleRail={() => {}} />);

    expect(screen.getByTestId('run-id')).toHaveTextContent('run_1a2b3c4d5e6f');
    expect(screen.getByTestId('playback-clock')).toHaveTextContent('2026-01-02 10:45:00');
    expect(screen.getByTestId('connection-pill')).toHaveTextContent('LIVE');
  });

  it('shows an em dash for the run id before the first replay tick', () => {
    useStore.getState().setPlants(PLANTS);
    renderWithRouter(<TopBar railCollapsed={false} onToggleRail={() => {}} />);
    expect(screen.getByTestId('run-id')).toHaveTextContent('—');
  });

  it('switches plant through the selector, which re-subscribes the socket', async () => {
    const user = userEvent.setup();
    seedStore();
    renderWithRouter(<TopBar railCollapsed={false} onToggleRail={() => {}} />);

    await user.selectOptions(screen.getByTestId('plant-select'), 'ims');
    expect(useStore.getState().plants.selected).toBe('ims');
  });

  it('renders a static label rather than a broken dropdown for one plant', () => {
    const [plant] = PLANTS;
    if (!plant) throw new Error('fixture missing');
    useStore.getState().setPlants([plant]);
    renderWithRouter(<TopBar railCollapsed={false} onToggleRail={() => {}} />);

    expect(screen.getByTestId('plant-select')).toHaveTextContent(plant.display_name);
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('reads degraded from the backpressure flag, not from an error', () => {
    seedStore();
    useStore.getState().setConnectionDegraded(true);
    renderWithRouter(<TopBar railCollapsed={false} onToggleRail={() => {}} />);

    const pill = screen.getByTestId('connection-pill');
    expect(pill).toHaveTextContent('DEGRADED');
    expect(pill).toHaveAttribute('data-degraded', 'true');
  });

  it('exposes the wall-clock receive time only in the pill tooltip', async () => {
    const user = userEvent.setup();
    seedStore();
    useStore.getState().noteMessageReceived(Date.parse('2026-05-01T09:00:00.000Z'));
    renderWithRouter(<TopBar railCollapsed={false} onToggleRail={() => {}} />);

    await user.hover(screen.getByTestId('connection-pill'));
    expect(screen.getByRole('tooltip')).toHaveTextContent('2026-05-01T09:00:00.000Z');
  });

  it('renders whatever fills the playback slot', () => {
    seedStore();
    registerSlot('topbar.playback', () => <button type="button">Pause</button>);
    renderWithRouter(<TopBar railCollapsed={false} onToggleRail={() => {}} />);
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument();
  });

  it('offers the rail toggle only when the rail is collapsed', async () => {
    const user = userEvent.setup();
    const onToggleRail = vi.fn();
    seedStore();
    renderWithRouter(<TopBar railCollapsed onToggleRail={onToggleRail} />);

    await user.click(screen.getByTestId('rail-toggle'));
    expect(onToggleRail).toHaveBeenCalledOnce();
  });
});
