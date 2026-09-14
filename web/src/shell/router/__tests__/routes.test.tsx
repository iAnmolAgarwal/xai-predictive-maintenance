import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { mockServer } from '@/mock/server';
import { resetStore, useStore } from '@/store';
import { clearRings } from '@/store/ringBuffer';
import { useWsConnection } from '../../ws/useWsConnection';
import type { SocketLike } from '../../ws/client';
import type { FakeSocket } from '../../ws/__tests__/fakeSocket';
import { socketFactory } from '../../ws/__tests__/fakeSocket';
import { clearSlots, registerSlot } from '../../slots';
import { seedStore, stubViewport } from '../../__tests__/testUtils';
import { AppRoutes } from '../routes';

beforeAll(() => mockServer.listen({ onUnhandledRequest: 'bypass' }));
afterEach(() => mockServer.resetHandlers());
afterAll(() => mockServer.close());

beforeEach(() => {
  resetStore();
  clearRings();
  clearSlots();
  stubViewport(true);
});

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );

describe('routing', () => {
  it('renders the plant floor at / with the demo deep link', async () => {
    const user = userEvent.setup();
    seedStore();
    renderAt('/');

    expect(screen.getByTestId('machine-grid')).toBeInTheDocument();
    await user.click(screen.getByTestId('floor-demo-link'));
    await waitFor(() => {
      expect(screen.getByTestId('machine-detail')).toBeInTheDocument();
    });
    expect(useStore.getState().ui.selectedMachineId).toBe('ai4i-03');
  });

  it('selects both machine and alert from a shareable URL', () => {
    seedStore();
    renderAt('/machines/ai4i-03?alert=alt_9f2c71ab40d3e155');

    expect(screen.getByTestId('machine-detail')).toHaveTextContent('ai4i-03');
    expect(useStore.getState().ui).toMatchObject({
      selectedMachineId: 'ai4i-03',
      selectedAlertId: 'alt_9f2c71ab40d3e155',
    });
  });

  it('renders a designed not-found state for an unknown machine', async () => {
    const user = userEvent.setup();
    seedStore();
    renderAt('/machines/ai4i-99');

    expect(screen.getByTestId('empty-machine-not-found')).toHaveTextContent('ai4i-99');
    await user.click(screen.getByRole('button', { name: 'Back to plant floor' }));
    expect(screen.getByTestId('machine-grid')).toBeInTheDocument();
  });

  it('renders a designed not-found state for an unknown route', () => {
    seedStore();
    renderAt('/nowhere');
    expect(screen.getByTestId('empty-route-not-found')).toBeInTheDocument();
  });

  it('renders the plant-unavailable state with the backend reason verbatim', () => {
    seedStore();
    const plant = useStore.getState().plants.byId['ai4i'];
    if (!plant) throw new Error('fixture missing');
    useStore.getState().upsertPlant({
      ...plant,
      available: false,
      unavailable_reason: 'IMS archive download failed after 3 attempts',
    });
    renderAt('/');

    expect(screen.getByTestId('empty-plant-unavailable')).toHaveTextContent(
      'IMS archive download failed after 3 attempts',
    );
    expect(screen.queryByTestId('machine-grid')).not.toBeInTheDocument();
  });

  it('mounts the four detail slots for a known machine', () => {
    seedStore();
    registerSlot('detail.charts', () => <p>charts</p>);
    renderAt('/machines/ai4i-03');

    expect(screen.getByText('charts')).toBeInTheDocument();
    expect(screen.getByTestId('empty-detail-shap')).toBeInTheDocument();
    expect(screen.getByTestId('empty-detail-whatif')).toBeInTheDocument();
    expect(screen.getByTestId('empty-detail-compare')).toBeInTheDocument();
  });

  it('never tears down the WebSocket on a route change', async () => {
    const user = userEvent.setup();
    const sockets: FakeSocket[] = [];
    const factory = socketFactory(sockets);

    function DataPlane() {
      useWsConnection({
        socketFactory: (url: string): SocketLike => factory(url),
        origin: 'http://xpm.test',
      });
      return null;
    }

    render(
      <MemoryRouter initialEntries={['/']}>
        <DataPlane />
        <AppRoutes />
      </MemoryRouter>,
    );

    // The boot sequence resolves GET /api/config, /api/plants and /api/replay
    // before the socket opens.
    await waitFor(() => expect(sockets).toHaveLength(1));
    expect(useStore.getState().config?.values['api.ws_ping_seconds']).toBe(10);

    const socket = sockets[0];
    socket?.open();
    await user.click(screen.getByTestId('floor-demo-link'));
    await waitFor(() => {
      expect(screen.getByTestId('machine-detail')).toBeInTheDocument();
    });

    expect(socket?.closed).toBe(false);
    expect(sockets).toHaveLength(1);
  });
});
