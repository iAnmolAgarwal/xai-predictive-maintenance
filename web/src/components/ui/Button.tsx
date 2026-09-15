import type { ButtonHTMLAttributes, ReactNode, Ref } from 'react';
import styles from './ui.module.css';

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'default' | 'ghost' | 'primary';
  children: ReactNode;
  /** React 19 passes `ref` as a plain prop; the rail drawer focuses its opener. */
  ref?: Ref<HTMLButtonElement> | undefined;
};

/** A real `<button>`. Every interactive surface in the app is one of these. */
export function Button({
  variant = 'default',
  className,
  type = 'button',
  children,
  ...rest
}: ButtonProps) {
  const variantClass =
    variant === 'ghost'
      ? styles.buttonGhost
      : variant === 'primary'
        ? styles.buttonPrimary
        : '';
  return (
    <button
      type={type}
      className={[styles.button, variantClass, className].filter(Boolean).join(' ')}
      {...rest}
    >
      {children}
    </button>
  );
}
