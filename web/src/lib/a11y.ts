/**
 * The single live-region announcer. One polite region and one assertive region
 * are mounted by the shell; everything that needs to speak goes through here, so
 * there is never more than one live region per politeness level.
 */

export type Politeness = 'polite' | 'assertive';

type Listener = (message: string, politeness: Politeness) => void;

const listeners = new Set<Listener>();

/** Announce `message`; `critical` severities use `assertive` (frontend.md §6.6). */
export function announce(message: string, politeness: Politeness = 'polite'): void {
  for (const listener of listeners) listener(message, politeness);
}

/** Subscribe the mounted live regions. Returns an unsubscribe function. */
export function subscribeToAnnouncements(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
