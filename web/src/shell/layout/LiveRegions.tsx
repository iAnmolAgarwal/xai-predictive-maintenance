import { useEffect, useState } from 'react';
import { subscribeToAnnouncements, type Politeness } from '@/lib/a11y';

/**
 * Exactly one polite and one assertive live region for the whole app, mounted by
 * the shell. Features announce through `lib/a11y`, so a screen reader never has
 * to arbitrate between competing regions.
 */
export function LiveRegions() {
  const [messages, setMessages] = useState<Record<Politeness, string>>({
    polite: '',
    assertive: '',
  });

  useEffect(
    () =>
      subscribeToAnnouncements((message, politeness) => {
        setMessages((previous) => ({ ...previous, [politeness]: message }));
      }),
    [],
  );

  return (
    <>
      <div className="visually-hidden" aria-live="polite" data-testid="live-polite">
        {messages.polite}
      </div>
      <div className="visually-hidden" aria-live="assertive" data-testid="live-assertive">
        {messages.assertive}
      </div>
    </>
  );
}
