import { Button } from '@/components/ui/Button';
import { useStore } from '@/store';
import styles from './ConnectionBanner.module.css';

/**
 * One in-flow banner for connection-level problems. It sits in the chrome rather
 * than floating over the view, so it can never cover a title row.
 *
 * Backpressure is deliberately *not* an error here: it shows as the degraded
 * treatment on the connection pill (frontend.md §1.1). The copy is ours; the
 * transport's own words (an HTTP reason phrase, a DOM exception) are kept in a
 * details disclosure for whoever is debugging.
 */
export function ConnectionBanner() {
  const error = useStore((state) => state.connection.error);
  const requestBoot = useStore((state) => state.requestBoot);

  if (error === null) return null;

  return (
    <div className={styles.banner} role="alert" data-testid="error-connection">
      <span className={styles.glyph} aria-hidden="true">
        ▲
      </span>
      <div className={styles.copy}>
        <p className={styles.title}>Can&rsquo;t reach the API</p>
        <p className={styles.body}>
          Live data is paused. The dashboard keeps retrying on its own.
        </p>
        <details className={styles.details}>
          <summary>Technical detail</summary>
          <span data-testid="error-connection-detail">{error}</span>
        </details>
      </div>
      <Button onClick={() => requestBoot()} data-testid="error-connection-retry">
        Retry now
      </Button>
    </div>
  );
}
