import type { ReactNode } from 'react';
import styles from './ui.module.css';

export type EmptyStateProps = {
  /** Used for the `empty-{area}` testid (frontend.md §4.2). */
  area: string;
  /**
   * Overrides the derived testid for the handful of states §4.2 names outright
   * (`plant-unavailable`), so a fixed name is rendered verbatim.
   */
  testId?: string | undefined;
  glyph?: string;
  title: string;
  /** Renders the title as a heading when this state is the page's main content. */
  titleAs?: 'p' | 'h1' | 'h2';
  body?: string | undefined;
  action?: ReactNode;
};

/**
 * The designed empty state. Empty is a product state, not a missing screen: it
 * says what would be here, why it is not, and what to do next.
 */
export function EmptyState({
  area,
  testId,
  glyph = '○',
  title,
  titleAs: Title = 'p',
  body,
  action,
}: EmptyStateProps) {
  return (
    <div className={styles.state} data-testid={testId ?? `empty-${area}`}>
      <span className={styles.stateGlyph} aria-hidden="true">
        {glyph}
      </span>
      <Title className={styles.stateTitle}>{title}</Title>
      {body === undefined ? null : <p className={styles.stateBody}>{body}</p>}
      {action}
    </div>
  );
}
