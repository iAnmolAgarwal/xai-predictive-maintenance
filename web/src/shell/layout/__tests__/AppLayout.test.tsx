import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it } from 'vitest';
import { axe } from 'vitest-axe';
import { Route, Routes } from 'react-router';
import { resetStore, useStore } from '@/store';
import { clearSlots } from '../../slots';
import { renderWithRouter, seedStore, stubViewport } from '../../__tests__/testUtils';
import { AppLayout } from '../AppLayout';

const renderLayout = (wide: boolean) => {
  stubViewport(wide);
  return renderWithRouter(
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<p>floor</p>} />
      </Route>
    </Routes>,
  );
};

beforeEach(() => {
  resetStore();
  clearSlots();
});

describe('AppLayout', () => {
  it('renders the three regions docked at 1440 px and up', () => {
    seedStore();
    renderLayout(true);

    expect(screen.getByTestId('app-shell')).toHaveAttribute('data-rail', 'docked');
    expect(screen.getByTestId('top-bar')).toBeInTheDocument();
    expect(screen.getByTestId('main-region')).toHaveTextContent('floor');
    expect(screen.getByTestId('right-rail')).toHaveAttribute('data-overlay', 'false');
    // No rail toggle is needed while the rail is docked.
    expect(screen.queryByTestId('rail-toggle')).not.toBeInTheDocument();
  });

  it('collapses the rail into a keyboard-operable drawer below 1440 px', async () => {
    const user = userEvent.setup();
    seedStore();
    renderLayout(false);

    expect(screen.getByTestId('app-shell')).toHaveAttribute('data-rail', 'overlay');
    expect(screen.queryByTestId('right-rail')).not.toBeInTheDocument();

    const toggle = screen.getByTestId('rail-toggle');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    toggle.focus();
    expect(toggle).toHaveFocus();
    await user.keyboard('{Enter}');

    const rail = await screen.findByTestId('right-rail');
    expect(rail).toHaveAttribute('data-overlay', 'true');
    expect(screen.getByTestId('rail-toggle')).toHaveAttribute('aria-expanded', 'true');

    // Escape closes the overlay, and focus starts on its close button.
    expect(screen.getByRole('button', { name: 'Close alerts' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('right-rail')).not.toBeInTheDocument();
  });

  it('shows an unread badge on the collapsed toggle so live alerts are not missed', async () => {
    const user = userEvent.setup();
    seedStore();
    renderLayout(false);

    useStore.getState().addAlerts(
      [
        {
          alert_id: 'alt_9f2c71ab40d3e155',
          run_id: 'run_1a2b3c4d5e6f',
          plant_id: 'ai4i',
          machine_id: 'ai4i-03',
          machine_display_name: 'Mill 03',
          ts: '2026-01-01T00:20:00.000Z',
          dataset_ts: '2026-01-01T00:20:00.000Z',
          model_id: 'lgbm@1.0.0',
          probability: 0.88,
          severity: 'high',
          headline: 'Torque above p95 for 4 h',
          top_feature: 'torque_p95_4h',
          explanation_id: 'exp_31c0a7f9b2d4e680',
          closed_dataset_ts: null,
        },
      ],
      { unseen: true },
    );

    const toggle = await screen.findByTestId('rail-toggle');
    expect(within(toggle).getByTestId('rail-unread-badge')).toHaveTextContent('1');

    // Opening the rail is what marks them seen.
    await user.click(toggle);
    expect(useStore.getState().alerts.unseenCount).toBe(0);
  });

  it('mirrors prefers-reduced-motion into the store', () => {
    seedStore();
    window.matchMedia = (query: string) => ({
      matches: query.includes('reduced-motion'),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    });

    renderWithRouter(
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<p>floor</p>} />
        </Route>
      </Routes>,
    );
    expect(useStore.getState().ui.reducedMotion).toBe(true);
  });

  it('has no axe violations', async () => {
    seedStore();
    const { container } = renderLayout(true);
    await expect(axe(container)).resolves.toHaveNoViolations();
  });
});
