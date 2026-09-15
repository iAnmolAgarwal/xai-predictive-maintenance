import type { SelectHTMLAttributes } from 'react';
import styles from './ui.module.css';

export type SelectOption = { value: string; label: string; disabled?: boolean };

export type SelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'children'> & {
  label: string;
  options: readonly SelectOption[];
};

/**
 * A native `<select>` under the hood: free keyboard support, free screen-reader
 * semantics, no listbox to re-implement badly.
 */
export function Select({ label, options, className, ...rest }: SelectProps) {
  return (
    <span className={styles.selectWrap}>
      <select
        aria-label={label}
        className={[styles.select, className].filter(Boolean).join(' ')}
        {...rest}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
      <span className={styles.selectChevron} aria-hidden="true">
        ▾
      </span>
    </span>
  );
}
