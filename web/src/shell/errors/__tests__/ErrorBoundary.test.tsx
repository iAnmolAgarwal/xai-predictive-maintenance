import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ErrorBoundary } from '../ErrorBoundary';

function Boom({ explode }: { explode: boolean }) {
  if (explode) throw new Error('uPlot went sideways');
  return <p>chart</p>;
}

describe('ErrorBoundary', () => {
  it('degrades to a designed, recoverable state instead of a white screen', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const user = userEvent.setup();

    const { rerender } = render(
      <ErrorBoundary area="machine-detail">
        <Boom explode />
      </ErrorBoundary>,
    );

    expect(screen.getByTestId('error-machine-detail')).toHaveTextContent(
      'uPlot went sideways',
    );

    rerender(
      <ErrorBoundary area="machine-detail">
        <Boom explode={false} />
      </ErrorBoundary>,
    );
    await user.click(screen.getByRole('button', { name: 'Try rendering again' }));
    expect(screen.getByText('chart')).toBeInTheDocument();
  });

  it('renders its children when nothing throws', () => {
    render(
      <ErrorBoundary>
        <Boom explode={false} />
      </ErrorBoundary>,
    );
    expect(screen.getByText('chart')).toBeInTheDocument();
  });
});
