import type { ReactNode } from 'react';
import styles from './ui.module.css';

export type EmptyStateProps = {
  /** Used for the `empty-{area}` testid (frontend.md §4.2). */
  area: string;
  glyph?: string;
  title: string;
  body?: string | undefined;
  action?: ReactNode;
};

/**
 * The designed empty state. Empty is a product state, not a missing screen: it
 * says what would be here, why it is not, and what to do next.
 */
export function EmptyState({ area, glyph = '○', title, body, action }: EmptyStateProps) {
  return (
    <div className={styles.state} data-testid={`empty-${area}`}>
      <span className={styles.stateGlyph} aria-hidden="true">
        {glyph}
      </span>
      <p className={styles.stateTitle}>{title}</p>
      {body === undefined ? null : <p className={styles.stateBody}>{body}</p>}
      {action}
    </div>
  );
}
