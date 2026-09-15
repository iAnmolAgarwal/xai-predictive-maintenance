import type { RefObject } from 'react';
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

/**
 * The dataset clock owns its own subscription, so the rest of the top bar -- the
 * plant select, the pill, the slots -- does not re-render on every commit.
 */
function DatasetClock() {
  const datasetTsMs = useStore((state) => state.playback.datasetTsMs);
  return (
    <span className={styles.clock} data-testid="playback-clock">
      <span className={styles.readoutLabel}>dataset time</span>
      <span className={styles.mono}>{formatDatasetTime(datasetTsMs)}</span>
    </span>
  );
}

/**
 * Read at tooltip-open time rather than subscribed: `lastMessageAt` changes on
 * every inbound frame, and the top bar must not re-render at frame rate.
 */
function ConnectionDetail() {
  const state = useStore.getState();
  const plant = state.plants.selected ? state.plants.byId[state.plants.selected] : null;
  const { lastMessageAt } = state.connection;
  return (
    <span>
      {plant ? `${plant.display_name} · ` : ''}
      {lastMessageAt > 0
        ? `last frame received ${new Date(lastMessageAt).toISOString()}`
        : 'no frames received yet'}
    </span>
  );
}

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
  railToggleRef,
  onToggleRail,
}: {
  railCollapsed: boolean;
  /** The drawer returns focus here when it closes. */
  railToggleRef?: RefObject<HTMLButtonElement | null>;
  onToggleRail: () => void;
}) {
  const navigate = useNavigate();
  const status = useStore((state) => state.connection.status);
  const degraded = useStore((state) => state.connection.degraded);
  const runId = useStore((state) => state.playback.runId);
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
        <Button
          variant="ghost"
          onClick={() => void navigate('/')}
          aria-label="XPM plant floor"
        >
          <span aria-hidden="true">▣</span>
          <span className={styles.brandName}>XPM</span>
        </Button>
        {options.length > 1 ? (
          <Select
            label="Plant"
            className={styles.plantSelect}
            data-testid="plant-select"
            value={plants.selected ?? ''}
            onChange={(event) => selectPlant(event.target.value)}
            options={options}
          />
        ) : (
          // One available plant is a label, not a one-option dropdown. It gets
          // its own testid, so `plant-select` always means a real control.
          <span className={styles.singlePlant} data-testid="plant-readout">
            <span className="visually-hidden">Plant: </span>
            {plant?.display_name ?? 'No plant available'}
          </span>
        )}
      </div>

      <div className={styles.transport}>
        <Slot name="topbar.playback" />
      </div>

      <div className={styles.readouts}>
        <DatasetClock />
        <span className={[styles.readout, styles.runReadout].join(' ')}>
          <span className={styles.readoutLabel}>run</span>
          <span className={styles.mono} data-testid="run-id">
            {runId ?? '—'}
          </span>
        </span>

        <Tooltip content={<ConnectionDetail />}>
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
                <span className={styles.pillLabel}>
                  {degraded ? 'DEGRADED' : treatment.label}
                </span>
              </Badge>
            </button>
          )}
        </Tooltip>

        {railCollapsed ? (
          <Button
            ref={railToggleRef}
            onClick={onToggleRail}
            aria-expanded={railOpen}
            aria-controls="right-rail"
            data-testid="rail-toggle"
            aria-label="Alerts"
          >
            <span aria-hidden="true">▤</span>
            <span className={styles.toggleLabel}>Alerts</span>
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
