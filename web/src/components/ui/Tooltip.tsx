import { useId, useState, type ReactElement, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import styles from './ui.module.css';

export type TooltipProps = {
  content: ReactNode;
  /** The trigger. It receives `aria-describedby` so the tip is announced. */
  children: (props: {
    'aria-describedby': string | undefined;
    onPointerEnter: () => void;
    onPointerLeave: () => void;
    onFocus: () => void;
    onBlur: () => void;
    onKeyDown: (event: { key: string }) => void;
    onPointerMove: (event: { clientX: number; clientY: number }) => void;
  }) => ReactElement;
};

/**
 * Portal tooltip that follows the pointer and closes on Escape. Hover *and*
 * keyboard focus open it, because a hover-only tooltip is invisible to a
 * keyboard user.
 */
export function Tooltip({ content, children }: TooltipProps) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [point, setPoint] = useState({ x: 0, y: 0 });

  const trigger = children({
    'aria-describedby': open ? id : undefined,
    onPointerEnter: () => setOpen(true),
    onPointerLeave: () => setOpen(false),
    onFocus: () => setOpen(true),
    onBlur: () => setOpen(false),
    onKeyDown: (event) => {
      if (event.key === 'Escape') setOpen(false);
    },
    onPointerMove: (event) => setPoint({ x: event.clientX, y: event.clientY }),
  });

  return (
    <>
      {trigger}
      {open && typeof document !== 'undefined'
        ? createPortal(
            <span
              id={id}
              role="tooltip"
              className={styles.tooltip}
              style={{ left: point.x + 12, top: point.y + 16 }}
            >
              {content}
            </span>,
            document.body,
          )
        : null}
    </>
  );
}
