import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';
import styles from './ui.module.css';

export type IconButtonProps = Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> & {
  /** Required: an icon-only control still needs an accessible name. */
  label: string;
  glyph: ReactNode;
  /** React 19 passes `ref` as a plain prop; the rail focuses its close button. */
  ref?: Ref<HTMLButtonElement> | undefined;
};

export function IconButton({ label, glyph, className, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={[styles.button, styles.iconButton, className].filter(Boolean).join(' ')}
      {...rest}
    >
      <span aria-hidden="true">{glyph}</span>
    </button>
  );
}
