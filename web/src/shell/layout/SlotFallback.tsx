import { EmptyState } from '@/components/ui/EmptyState';
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

/** The empty state rendered by a slot no feature has registered for. */
export function SlotFallback({ name }: { name: SlotName }) {
  const area = name.replace('.', '-');
  if (name === 'floor.grid') return <FloorGridFallback area={area} />;
  // The top bar is 56 px tall: its empty state is one quiet line, not a panel.
  if (name === 'topbar.playback') {
    const copy = COPY[name];
    return (
      <p className={styles.inline} data-testid={`empty-${area}`}>
        <span aria-hidden="true">{copy.glyph}</span> {copy.title} — {copy.body}
      </p>
    );
  }
  const copy = COPY[name];
  return <EmptyState area={area} glyph={copy.glyph} title={copy.title} body={copy.body} />;
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

  const ids =
    order.length > 0
      ? order
      : Array.from({ length: count }, (_, index) => `machine-${index + 1}`);

  return (
    <div className={styles.floor} data-testid="machine-grid">
      <p className={styles.floorNote} data-testid={`empty-${area}`}>
        {order.length > 0
          ? `${String(count)} machines in this plant. Tiles are waiting for their first scored row.`
          : `${String(count)} machines in this plant. Waiting for the first snapshot.`}
      </p>
      <ul className={styles.grid}>
        {ids.map((id) => {
          const machine = byId[id];
          return (
            <li
              key={id}
              className={styles.tile}
              data-testid={`floor-placeholder-tile-${id}`}
            >
              <span className={styles.tileId}>{machine?.display_name ?? id}</span>
              <span className={styles.tileMeta}>
                {machine ? machine.machine_id : 'awaiting snapshot'}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
