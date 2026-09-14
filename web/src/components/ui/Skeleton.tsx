import styles from './ui.module.css';

export type SkeletonProps = {
  /** Skeletons match the final geometry exactly (frontend.md §6.4). */
  width?: number | string;
  height?: number | string;
  radius?: string;
  area: string;
};

export function Skeleton({ width = '100%', height = 16, radius, area }: SkeletonProps) {
  return (
    <span
      className={styles.skeleton}
      data-testid={`skeleton-${area}`}
      aria-hidden="true"
      style={{ display: 'block', width, height, borderRadius: radius }}
    />
  );
}
