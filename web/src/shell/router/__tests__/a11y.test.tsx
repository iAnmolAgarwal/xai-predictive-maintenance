import { render } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { beforeEach, describe, expect, it } from 'vitest';
import { axe } from 'vitest-axe';
import { resetStore, useStore } from '@/store';
import { clearRings } from '@/store/ringBuffer';
import { clearSlots } from '@/shell/slots';
import { seedStore, stubViewport } from '@/shell/__tests__/testUtils';
import { AppRoutes } from '../routes';

beforeEach(() => {
  resetStore();
  clearRings();
  clearSlots();
  stubViewport(true);
});

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );

/**
 * §6.6 makes zero axe violations a merge gate, and §6.6 specifically warns that
 * components on `--c-surface-2` must re-verify their contrast — which is exactly
 * what the faint micro-labels failed. These run over the whole rendered chrome,
 * not a component in isolation, so the token pairs are checked in context.
 */
describe('shell accessibility', () => {
  it('has no violations on the plant floor', async () => {
    seedStore();
    const { container } = renderAt('/');
    await expect(axe(container)).resolves.toHaveNoViolations();
  });

  it('has no violations on machine detail', async () => {
    seedStore();
    const { container } = renderAt('/machines/ai4i-03');
    await expect(axe(container)).resolves.toHaveNoViolations();
  });

  it('has no violations on the not-found route, which carries the h1', async () => {
    seedStore();
    const { container } = renderAt('/zzz');
    expect(container.querySelector('h1')).not.toBeNull();
    await expect(axe(container)).resolves.toHaveNoViolations();
  });

  it('has no violations while the API is unreachable', async () => {
    useStore.getState().setConnectionError('Cannot reach the API. Failed to fetch');
    const { container } = renderAt('/');
    await expect(axe(container)).resolves.toHaveNoViolations();
  });
});
