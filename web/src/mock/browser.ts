/**
 * The single entry point into mock code. `main.tsx` imports it dynamically,
 * behind `import.meta.env.VITE_USE_MOCKS === 'true'`, so the entire mock graph is
 * tree-shaken out of any build that does not set the flag.
 */
import { setupWorker } from 'msw/browser';
import { handlers } from './handlers';
import { MOCK_MARKER } from './fixtures';

export async function startMockServer(): Promise<void> {
  const worker = setupWorker(...handlers);
  await worker.start({ onUnhandledRequest: 'bypass', quiet: true });
  console.debug(`${MOCK_MARKER} mock API active`);
}
