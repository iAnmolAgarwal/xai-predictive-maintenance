/**
 * Boots the app's data plane and keeps the socket subscribed to the selected
 * plant.
 *
 * Boot order is load-bearing (frontend.md §1.1): `GET /api/config` resolves
 * before the WebSocket opens, because the liveness timeout is derived from
 * `api.ws_ping_seconds`. Switching plant re-subscribes the socket (R8); route
 * changes do not, because this hook lives above the router outlet.
 *
 * The boot effect is idempotent rather than once-only. React StrictMode mounts,
 * unmounts and remounts effects in development, and a `booted` flag that survives
 * the cleanup while the cleanup aborts the requests leaves the app permanently
 * dead. The guard is therefore the store's own state — config and plants — which
 * the aborted attempt never wrote.
 */
import { useEffect, useRef } from 'react';
import { getConfig, getPlants, getReplay } from '@/api/queries';
import type { PlantId } from '@/contracts';
import { useStore } from '@/store';
import { RECONNECT } from '@/config';
import { createWsClient, type WsClient, type WsClientDeps } from './client';
import { backoffDelayMs } from './reconnect';

/** Copy, not a transport string: the raw reason goes in the banner's details. */
const BOOT_ERROR = 'Cannot reach the API.';

export function useWsConnection(deps: WsClientDeps = {}): void {
  const selected = useStore((state) => state.plants.selected);
  const bootAttempt = useStore((state) => state.connection.bootAttempt);
  const depsRef = useRef(deps);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const store = useStore.getState();
    // Already booted: a StrictMode remount must not refetch, and a plant switch
    // must not re-run the boot sequence. The flag is only set once the whole
    // sequence has landed, so a half-finished attempt that StrictMode aborted is
    // correctly retried rather than mistaken for success.
    if (store.connection.booted) return;

    const controller = new AbortController();
    void (async () => {
      try {
        const [config, plants] = await Promise.all([
          getConfig({ signal: controller.signal }),
          getPlants({ signal: controller.signal }),
        ]);
        if (controller.signal.aborted) return;
        store.applyConfig(config);
        store.setPlants(plants);
        store.setConnectionError(null);
        const replay = await getReplay({ signal: controller.signal });
        if (controller.signal.aborted) return;
        store.applyReplayState(replay);
        store.markBooted();
      } catch (error) {
        if (controller.signal.aborted) return;
        const state = useStore.getState();
        // A boot failure is terminal until it succeeds: the socket is never
        // opened, so the pill must say so rather than spin on "connecting".
        state.setConnectionStatus('closed', state.connection.bootAttempt);
        state.setConnectionError(
          error instanceof Error ? `${BOOT_ERROR} ${error.message}` : BOOT_ERROR,
        );
        // Retry on the same backoff schedule the socket uses, so an API that
        // comes up later is picked up without a reload.
        if (retryTimer.current !== null) clearTimeout(retryTimer.current);
        retryTimer.current = setTimeout(
          () => {
            retryTimer.current = null;
            useStore.getState().requestBoot();
          },
          // Full jitter can draw 0, and a boot retry at 0 ms is a hot loop
          // against a down API; the first backoff step is the floor.
          Math.max(
            RECONNECT.baseMs,
            backoffDelayMs(state.connection.bootAttempt, deps.random ?? Math.random),
          ),
        );
      }
    })();

    return () => {
      controller.abort();
      if (retryTimer.current !== null) {
        clearTimeout(retryTimer.current);
        retryTimer.current = null;
      }
    };
    // `bootAttempt` is the retry signal; nothing else re-runs the boot.
  }, [bootAttempt, deps.random]);

  useEffect(() => {
    if (selected === null) return;
    const client: WsClient = createWsClient(depsRef.current);
    client.connect(selected as PlantId);
    return () => client.disconnect();
  }, [selected]);
}
