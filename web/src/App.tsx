import { BrowserRouter } from 'react-router';
import { ErrorBoundary } from '@/shell/errors/ErrorBoundary';
import { AppRoutes } from '@/shell/router/routes';
import { useWsConnection } from '@/shell/ws/useWsConnection';

/**
 * Application root. The socket and the store live here, above the router, so a
 * route change never tears either down.
 */
export function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <DataPlane />
        <AppRoutes />
      </ErrorBoundary>
    </BrowserRouter>
  );
}

/** Renders nothing: it owns the boot sequence and the WebSocket lifecycle. */
function DataPlane() {
  useWsConnection();
  return null;
}
