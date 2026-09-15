import type { InputHTMLAttributes } from 'react';
import styles from './ui.module.css';

export type SliderProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> & {
  label: string;
  /** Spoken value, e.g. "48.1 N·m" — the unit string is the backend's, verbatim. */
  valueText: string;
  hint?: string;
};

/** Built on `<input type="range">`, so arrow keys, Home/End and PageUp work. */
export function Slider({ label, valueText, hint, className, ...rest }: SliderProps) {
  return (
    <span className={styles.sliderRow}>
      <span className={styles.sliderLabel}>
        <span>{label}</span>
        <span>{valueText}</span>
      </span>
      <input
        type="range"
        aria-label={label}
        aria-valuetext={valueText}
        className={[styles.slider, className].filter(Boolean).join(' ')}
        {...rest}
      />
      {hint === undefined ? null : <span className={styles.sliderLabel}>{hint}</span>}
    </span>
  );
}
