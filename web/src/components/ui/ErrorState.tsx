import type { ReactNode } from 'react';
import styles from './ui.module.css';

export type ErrorStateProps = {
  area: string;
  title: string;
  /** The message as received. The frontend composes no error prose of its own. */
  detail?: string | undefined;
  action?: ReactNode;
};

export function ErrorState({ area, title, detail, action }: ErrorStateProps) {
  return (
    <div
      className={[styles.state, styles.stateError].join(' ')}
      data-testid={`error-${area}`}
      role="alert"
    >
      <span className={styles.stateGlyph} aria-hidden="true">
        ▲
      </span>
      <p className={styles.stateTitle}>{title}</p>
      {detail === undefined ? null : <p className={styles.stateBody}>{detail}</p>}
      {action}
    </div>
  );
}
