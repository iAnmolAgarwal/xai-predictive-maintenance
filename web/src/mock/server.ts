/** The Node-side MSW server, used by Vitest suites that need the REST surface. */
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const mockServer = setupServer(...handlers);
