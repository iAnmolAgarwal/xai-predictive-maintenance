/**
 * Boots the app's data plane exactly once and keeps the socket subscribed to the
 * selected plant.
 *
 * Boot order is load-bearing (frontend.md §1.1): `GET /api/config` resolves
 * before the WebSocket opens, because the liveness timeout is derived from
 * `api.ws_ping_seconds`. Switching plant re-subscribes the socket (R8); route
 * changes do not, because this hook lives above the router outlet.
 */
import { useEffect, useRef } from 'react';
import { getConfig, getPlants, getReplay } from '@/api/queries';
import type { PlantId } from '@/contracts';
import { useStore } from '@/store';
import { createWsClient, type WsClient, type WsClientDeps } from './client';

export function useWsConnection(deps: WsClientDeps = {}): void {
  const selected = useStore((state) => state.plants.selected);
  const booted = useRef(false);
  const depsRef = useRef(deps);

  useEffect(() => {
    if (booted.current) return;
    booted.current = true;
    const controller = new AbortController();
    const store = useStore.getState();
    void (async () => {
      try {
        const [config, plants] = await Promise.all([
          getConfig({ signal: controller.signal }),
          getPlants({ signal: controller.signal }),
        ]);
        store.applyConfig(config);
        store.setPlants(plants);
        const replay = await getReplay({ signal: controller.signal });
        store.applyReplayState(replay);
      } catch (error) {
        if (controller.signal.aborted) return;
        store.setConnectionError(
          error instanceof Error ? error.message : 'Failed to reach the API',
        );
      }
    })();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (selected === null) return;
    const client: WsClient = createWsClient(depsRef.current);
    client.connect(selected as PlantId);
    return () => client.disconnect();
  }, [selected]);
}
