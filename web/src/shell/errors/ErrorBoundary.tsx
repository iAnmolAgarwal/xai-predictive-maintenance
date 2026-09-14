import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button } from '@/components/ui/Button';
import { ErrorState } from '@/components/ui/ErrorState';

type Props = { children: ReactNode; area?: string };
type State = { error: Error | null };

/**
 * The global error boundary. A render crash degrades to a designed, recoverable
 * state instead of a white screen; the socket and the store survive it.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('[xpm] render error', error, info.componentStack);
  }

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <ErrorState
        area={this.props.area ?? 'app'}
        title="This view stopped responding"
        detail={error.message}
        action={
          <Button onClick={() => this.setState({ error: null })}>Try rendering again</Button>
        }
      />
    );
  }
}
