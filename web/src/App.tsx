import { BrowserRouter } from 'react-router';
import { ErrorBoundary } from '@/shell/errors/ErrorBoundary';
import { AppRoutes } from '@/shell/router/routes';
import { useWsConnection } from '@/shell/ws/useWsConnection';
import { useStore } from '@/store';
import styles from './App.module.css';

/**
 * Application root. The socket and the store live here, above the router, so a
 * route change never tears either down.
 */
export function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <DataPlane />
        <ConnectionBanner />
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

/**
 * A single banner for connection-level problems. Backpressure is *not* an error:
 * it shows as the degraded treatment on the connection pill instead (§1.1).
 */
function ConnectionBanner() {
  const error = useStore((state) => state.connection.error);
  const setConnectionError = useStore((state) => state.setConnectionError);
  if (error === null) return null;
  return (
    <div className={styles.banner} role="alert" data-testid="error-connection">
      <span aria-hidden="true">▲</span>
      <span>{error}</span>
      <button
        type="button"
        className={styles.bannerDismiss}
        onClick={() => setConnectionError(null)}
      >
        Dismiss
      </button>
    </div>
  );
}
