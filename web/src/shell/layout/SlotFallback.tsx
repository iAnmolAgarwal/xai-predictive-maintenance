import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { ErrorState } from '@/components/ui/ErrorState';
import { Skeleton } from '@/components/ui/Skeleton';
import { useStore } from '@/store';
import { selectedPlant } from '@/store/selectors';
import type { SlotName } from '../slots';
import styles from './SlotFallback.module.css';

type FallbackCopy = { glyph: string; title: string; body: string };

/**
 * The production empty state for each slot. These are the words a user sees if
 * a panel has nothing to show — honest about what is missing and why, never a
 * placeholder and never a "coming soon".
 */
const COPY: Record<SlotName, FallbackCopy> = {
  'topbar.playback': {
    glyph: '⏸',
    title: 'Transport unavailable',
    body: 'Replay controls appear once the publisher announces a run.',
  },
  'rail.feed': {
    glyph: '○',
    title: 'No alerts yet',
    body: 'Alerts arrive here as the model flags machines. Nothing has crossed the threshold in this run.',
  },
  'detail.charts': {
    glyph: '∿',
    title: 'Waiting for telemetry',
    body: 'Channel traces draw as soon as this machine publishes its next row.',
  },
  'detail.shap': {
    glyph: 'ⓘ',
    title: 'No explanation active at this time',
    body: 'Select an alert to see which features drove its score.',
  },
  'detail.whatif': {
    glyph: '⇄',
    title: 'Nothing to explore yet',
    body: 'What-if sliders open on the features of a selected alert.',
  },
  'detail.compare': {
    glyph: '⇆',
    title: 'No comparison available',
    body: 'Model comparison needs an alert with explanations from both models.',
  },
  'floor.grid': {
    glyph: '▦',
    title: 'No machines in this plant',
    body: 'The plant descriptor reports no machines to display.',
  },
};

/**
 * What a region says when nothing has registered for it.
 *
 * Order matters: unreachable beats empty. A monitoring panel that renders "no
 * alerts" while it cannot reach the API is lying about the plant, so as long as
 * boot has not succeeded every region says so instead.
 */
export function SlotFallback({ name }: { name: SlotName }) {
  const area = name.replace('.', '-');
  const unreachable = useStore(
    (state) => state.plants.order.length === 0 && state.connection.error !== null,
  );
  const booting = useStore(
    (state) => state.plants.order.length === 0 && state.connection.error === null,
  );

  if (unreachable) return <UnreachableState area={area} name={name} />;
  if (booting) return <BootingState area={area} name={name} />;
  if (name === 'floor.grid') return <FloorGridFallback area={area} />;
  if (name === 'rail.feed') return <RailFeedFallback area={area} />;
  // The top bar is 56 px tall: its empty state is one quiet line, not a panel.
  if (name === 'topbar.playback') {
    const copy = COPY[name];
    // 56 px of chrome: the title alone, with the explanation on hover, so this
    // never becomes the loudest thing in the bar.
    return (
      <p className={styles.inline} data-testid={`empty-${area}`} title={copy.body}>
        <span aria-hidden="true">{copy.glyph}</span> {copy.title}
      </p>
    );
  }
  const copy = COPY[name];
  return <EmptyState area={area} glyph={copy.glyph} title={copy.title} body={copy.body} />;
}

/** Copy per region for the "cannot reach the API" state. */
const UNREACHABLE: Record<SlotName, string> = {
  'topbar.playback': 'Transport state is unknown while the API is unreachable.',
  'rail.feed': 'Alerts cannot be loaded while the API is unreachable.',
  'detail.charts': 'Telemetry cannot be loaded while the API is unreachable.',
  'detail.shap': 'Explanations cannot be loaded while the API is unreachable.',
  'detail.whatif': 'What-if needs the API, which is unreachable.',
  'detail.compare': 'Model comparison needs the API, which is unreachable.',
  'floor.grid': 'Machines cannot be listed while the API is unreachable.',
};

/** The honest state when boot failed: no data, and the panel says exactly that. */
function UnreachableState({ area, name }: { area: string; name: SlotName }) {
  const requestBoot = useStore((state) => state.requestBoot);
  if (name === 'topbar.playback') {
    return (
      <p className={styles.inline} data-testid={`error-${area}`}>
        <span aria-hidden="true">▲</span> API unreachable
      </p>
    );
  }
  return (
    <ErrorState
      area={area}
      title="Can't reach the API"
      detail={UNREACHABLE[name]}
      action={<Button onClick={() => requestBoot()}>Retry now</Button>}
    />
  );
}

/** Before the first descriptor arrives the region holds its shape, silently. */
function BootingState({ area, name }: { area: string; name: SlotName }) {
  if (name === 'topbar.playback') {
    return (
      <p className={styles.inline} data-testid={`skeleton-${area}`}>
        Connecting…
      </p>
    );
  }
  return (
    <div className={styles.loading} data-testid={`skeleton-${area}`}>
      <Skeleton area={`${area}-line-1`} height={12} width="40%" />
      <Skeleton area={`${area}-line-2`} height={160} />
    </div>
  );
}

/**
 * The rail before the feed is available. The copy is read from the store rather
 * than assumed, so it can never claim "no alerts yet" while the header beside it
 * shows an unread badge.
 */
function RailFeedFallback({ area }: { area: string }) {
  const alertCount = useStore((state) => state.alerts.order.length);
  const copy = COPY['rail.feed'];

  if (alertCount === 0) {
    return (
      <EmptyState area={area} glyph={copy.glyph} title={copy.title} body={copy.body} />
    );
  }

  return (
    <EmptyState
      area={area}
      glyph="▲"
      title={
        alertCount === 1
          ? '1 alert in this run'
          : `${String(alertCount)} alerts in this run`
      }
      body="They are held in the store and render here as soon as the feed is available."
    />
  );
}

/**
 * The plant floor before its tiles have anything to draw: the grid still occupies
 * its final geometry, one placeholder per machine the plant descriptor reports,
 * so the layout does not jump when data arrives.
 */
function FloorGridFallback({ area }: { area: string }) {
  const plant = useStore(selectedPlant);
  const order = useStore((state) => state.machines.order);
  const byId = useStore((state) => state.machines.byId);
  const count = plant?.machine_count ?? 0;

  if (count === 0) {
    const copy = COPY['floor.grid'];
    return (
      <EmptyState area={area} glyph={copy.glyph} title={copy.title} body={copy.body} />
    );
  }

  // Before the first snapshot there are no machine ids, and inventing some would
  // put fake data on screen. Skeletons hold the exact final geometry instead.
  if (order.length === 0) {
    return (
      <div className={styles.floor} data-testid="floor-placeholder-grid">
        <p className={styles.floorNote} data-testid={`empty-${area}`}>
          {`${String(count)} machines in this plant. Waiting for the first snapshot.`}
        </p>
        <ul className={styles.grid}>
          {Array.from({ length: count }, (_, index) => (
            <li key={index} className={styles.tile}>
              <Skeleton area={`floor-tile-${String(index + 1)}`} height={100} />
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className={styles.floor} data-testid="floor-placeholder-grid">
      <p className={styles.floorNote} data-testid={`empty-${area}`}>
        {`${String(count)} machines in this plant. Tiles are waiting for their first scored row.`}
      </p>
      <ul className={styles.grid}>
        {order.map((id) => {
          const machine = byId[id];
          return (
            <li
              key={id}
              className={styles.tile}
              data-testid={`floor-placeholder-tile-${id}`}
            >
              <div className={styles.tileHead}>
                {/* The ring and sparkline boxes are reserved now, at the size the
                    real tile uses, so the grid does not jump when it lands. */}
                <span className={styles.tileRing} aria-hidden="true" />
                <span className={styles.tileId}>{machine?.display_name ?? id}</span>
              </div>
              <span className={styles.tileSpark} aria-hidden="true" />
              <span className={styles.tileMeta}>{machine?.machine_id ?? id}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
