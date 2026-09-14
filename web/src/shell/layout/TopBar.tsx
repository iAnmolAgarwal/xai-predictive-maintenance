import { useNavigate } from 'react-router';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Select } from '@/components/ui/Select';
import { Tooltip } from '@/components/ui/Tooltip';
import { formatDatasetTime } from '@/lib/formatters';
import { useStore } from '@/store';
import { selectedPlant } from '@/store/selectors';
import { Slot } from '../slots';
import styles from './TopBar.module.css';

const STATUS_TREATMENT = {
  connecting: { glyph: '◌', label: 'CONNECTING', tone: 'neutral' },
  open: { glyph: '●', label: 'LIVE', tone: 'healthy' },
  reconnecting: { glyph: '◌', label: 'RECONNECTING', tone: 'watch' },
  closed: { glyph: '○', label: 'OFFLINE', tone: 'offline' },
} as const;

/**
 * The top bar subscribes to `connection`, the selected plant and
 * `playback.runId` — and to nothing that streams, so it never re-renders on
 * telemetry.
 */
export function TopBar({
  railCollapsed,
  onToggleRail,
}: {
  railCollapsed: boolean;
  onToggleRail: () => void;
}) {
  const navigate = useNavigate();
  const status = useStore((state) => state.connection.status);
  const degraded = useStore((state) => state.connection.degraded);
  const lastMessageAt = useStore((state) => state.connection.lastMessageAt);
  const runId = useStore((state) => state.playback.runId);
  const datasetTsMs = useStore((state) => state.playback.datasetTsMs);
  const plants = useStore((state) => state.plants);
  const plant = useStore(selectedPlant);
  const unseenCount = useStore((state) => state.alerts.unseenCount);
  const railOpen = useStore((state) => state.ui.railOpen);
  const selectPlant = useStore((state) => state.selectPlant);

  const treatment = STATUS_TREATMENT[status];
  const options = plants.order.map((id) => {
    const entry = plants.byId[id];
    return {
      value: id,
      label: entry?.display_name ?? id,
      disabled: entry?.available === false,
    };
  });

  return (
    <header className={styles.topBar} data-testid="top-bar">
      <div className={styles.brand}>
        <Button variant="ghost" onClick={() => void navigate('/')}>
          <span aria-hidden="true">▣</span> XPM
        </Button>
        {options.length > 1 ? (
          <Select
            label="Plant"
            data-testid="plant-select"
            value={plants.selected ?? ''}
            onChange={(event) => selectPlant(event.target.value)}
            options={options}
          />
        ) : (
          <span className={styles.singlePlant} data-testid="plant-select">
            {plant?.display_name ?? 'No plant available'}
          </span>
        )}
      </div>

      <div className={styles.transport}>
        <Slot name="topbar.playback" />
      </div>

      <div className={styles.readouts}>
        <span className={styles.clock} data-testid="playback-clock">
          <span className={styles.readoutLabel}>dataset time</span>
          <span className={styles.mono}>{formatDatasetTime(datasetTsMs)}</span>
        </span>
        <span className={styles.readout}>
          <span className={styles.readoutLabel}>run</span>
          <span className={styles.mono} data-testid="run-id">
            {runId ?? '—'}
          </span>
        </span>

        <Tooltip
          content={
            <span>
              {plant ? `${plant.display_name} · ` : ''}
              {lastMessageAt > 0
                ? `last frame received ${new Date(lastMessageAt).toISOString()}`
                : 'no frames received yet'}
            </span>
          }
        >
          {(tooltipProps) => (
            <button
              {...tooltipProps}
              type="button"
              className={styles.pill}
              data-testid="connection-pill"
              data-status={status}
              data-degraded={degraded ? 'true' : 'false'}
            >
              <Badge tone={degraded ? 'watch' : treatment.tone} glyph={treatment.glyph}>
                {degraded ? 'DEGRADED' : treatment.label}
              </Badge>
            </button>
          )}
        </Tooltip>

        {railCollapsed ? (
          <Button
            onClick={onToggleRail}
            aria-expanded={railOpen}
            aria-controls="right-rail"
            data-testid="rail-toggle"
          >
            Alerts
            {unseenCount > 0 ? (
              <Badge tone="count" data-testid="rail-unread-badge">
                {unseenCount}
              </Badge>
            ) : null}
          </Button>
        ) : null}
      </div>
    </header>
  );
}
