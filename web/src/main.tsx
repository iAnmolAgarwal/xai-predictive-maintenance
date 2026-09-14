import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/inter/latin-400.css';
import '@fontsource/inter/latin-500.css';
import '@fontsource/inter/latin-600.css';
import '@fontsource/jetbrains-mono/latin-400.css';
import '@fontsource/jetbrains-mono/latin-500.css';
import './styles/tokens.css';
import './styles/base.css';
import './styles/utilities.css';
import { App } from './App';
import './features/registry';

const container = document.getElementById('root');
if (!container) throw new Error('#root is missing from index.html');

async function start(): Promise<void> {
  // The only reference to mock code in the application graph, behind a build-time
  // flag that is never set in the Docker build or in `pnpm dev` (frontend.md §1.1).
  if (import.meta.env.VITE_USE_MOCKS === 'true') {
    const { startMockServer } = await import('./mock/browser');
    await startMockServer();
  }
  createRoot(container as HTMLElement).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void start();
