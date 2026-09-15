import { describe, expect, it, vi } from 'vitest';
import { announce, subscribeToAnnouncements } from '../a11y';

describe('announcer', () => {
  it('delivers to every subscriber with the requested politeness', () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToAnnouncements(listener);

    announce('critical on Mill 03: torque spike', 'assertive');
    announce('medium on Bearing 01: drift');

    expect(listener).toHaveBeenNthCalledWith(
      1,
      'critical on Mill 03: torque spike',
      'assertive',
    );
    expect(listener).toHaveBeenNthCalledWith(2, 'medium on Bearing 01: drift', 'polite');

    unsubscribe();
    announce('ignored');
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
