import styles from './ui.module.css';

export type HealthRingProps = {
  /** `null` renders the designed "not yet scored" state: empty track and "—". */
  probability: number | null;
  size?: number;
  /** The state colour is a CSS custom property name from tokens.css. */
  accent?: string;
  label: string;
  'data-testid'?: string;
};

/** SVG arc driven by `stroke-dashoffset`, so the fill animates on the compositor. */
export function HealthRing({
  probability,
  size = 56,
  accent = 'var(--c-healthy)',
  label,
  ...rest
}: HealthRingProps) {
  const stroke = 4;
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const scored = probability !== null && Number.isFinite(probability);
  const offset = scored ? circumference * (1 - (probability ?? 0)) : circumference;

  return (
    <svg
      className={styles.ring}
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={label}
      {...rest}
    >
      <circle
        className={styles.ringTrack}
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        strokeWidth={stroke}
      />
      {scored ? (
        <circle
          className={styles.ringValue}
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={accent}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      ) : null}
      <text
        className={styles.ringLabel}
        x="50%"
        y="50%"
        dominantBaseline="central"
        textAnchor="middle"
      >
        {scored ? `${Math.round((probability ?? 0) * 100)}%` : '—'}
      </text>
    </svg>
  );
}
