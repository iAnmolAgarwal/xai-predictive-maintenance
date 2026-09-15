import type { ReactNode } from 'react';
import styles from './ui.module.css';

export type BadgeTone = 'neutral' | 'healthy' | 'watch' | 'danger' | 'offline' | 'count';

const TONE_CLASS: Record<BadgeTone, string> = {
  neutral: '',
  healthy: styles.badgeHealthy ?? '',
  watch: styles.badgeWatch ?? '',
  danger: styles.badgeDanger ?? '',
  offline: styles.badgeOffline ?? '',
  count: styles.badgeCount ?? '',
};

export type BadgeProps = {
  tone?: BadgeTone;
  /** Non-colour signal: every badge carries a glyph as well as a hue. */
  glyph?: string;
  children: ReactNode;
  className?: string;
  'data-testid'?: string;
};

export function Badge({
  tone = 'neutral',
  glyph,
  children,
  className,
  ...rest
}: BadgeProps) {
  return (
    <span
      className={[styles.badge, TONE_CLASS[tone], className].filter(Boolean).join(' ')}
      {...rest}
    >
      {glyph === undefined ? null : <span aria-hidden="true">{glyph}</span>}
      {children}
    </span>
  );
}
