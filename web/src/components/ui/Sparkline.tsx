import { useMemo } from 'react';
import styles from './ui.module.css';

export type SparklineProps = {
  /** Oldest first. `null` is a gap, never a zero (frontend.md §1.2). */
  values: ReadonlyArray<number | null>;
  width?: number;
  height?: number;
  /** Fixed domain keeps tiles visually comparable. */
  domain?: [number, number];
  label: string;
  className?: string;
  'data-testid'?: string;
};

/**
 * A minimal SVG sparkline. `null` samples break the path into subpaths rather
 * than interpolating or dropping to the baseline; an all-null series renders no
 * path at all.
 */
export function Sparkline({
  values,
  width = 96,
  height = 24,
  domain = [0, 1],
  label,
  className,
  ...rest
}: SparklineProps) {
  const subpaths = useMemo(
    () => buildSubpaths(values, width, height, domain),
    [values, width, height, domain],
  );
  const hasData = subpaths.length > 0;

  return (
    <svg
      className={[styles.sparkline, className].filter(Boolean).join(' ')}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={label}
      {...rest}
    >
      {hasData ? (
        subpaths.map((d) => (
          <path
            key={d}
            d={d}
            fill="none"
            stroke="currentColor"
            strokeWidth={1.5}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))
      ) : (
        <line
          x1={0}
          x2={width}
          y1={height - 1}
          y2={height - 1}
          stroke="currentColor"
          strokeWidth={1}
          strokeDasharray="2 3"
          opacity={0.5}
        />
      )}
    </svg>
  );
}

function buildSubpaths(
  values: ReadonlyArray<number | null>,
  width: number,
  height: number,
  domain: [number, number],
): string[] {
  const [lo, hi] = domain;
  const span = hi - lo || 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const paths: string[] = [];
  let current: string[] = [];

  values.forEach((value, index) => {
    if (value === null || Number.isNaN(value)) {
      if (current.length > 1) paths.push(current.join(' '));
      current = [];
      return;
    }
    const x = index * step;
    const y = height - ((value - lo) / span) * height;
    current.push(
      `${current.length === 0 ? 'M' : 'L'}${x.toFixed(2)},${clamp(y, 0, height).toFixed(2)}`,
    );
  });
  if (current.length > 1) paths.push(current.join(' '));
  return paths;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
