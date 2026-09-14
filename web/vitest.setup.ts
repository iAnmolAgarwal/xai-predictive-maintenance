import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach, expect, vi } from 'vitest';
import * as axeMatchers from 'vitest-axe/matchers';

expect.extend(axeMatchers);

// jsdom implements neither matchMedia nor ResizeObserver, and the shell reads
// both (reduced motion, rail breakpoint, chart sizing).
if (!window.matchMedia) {
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    });
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  };
}


// jsdom supplies `AbortController`, but `fetch` is Node's, and Node rejects a
// signal that did not come from its own realm ("Expected signal to be an
// instance of AbortSignal"). In a browser both come from one realm, so this is a
// pure test-environment mismatch. The wrapper below preserves the caller's abort
// semantics while handing the underlying fetch a request it accepts, and is
// re-applied before every test because MSW installs its own `fetch` in
// `server.listen()`. Application code passes its signal straight through, as it
// must.
type FetchFn = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

const SHIMMED = Symbol.for('xpm.fetch.signal-shim');

const abortError = (): DOMException =>
  new DOMException('The operation was aborted.', 'AbortError');

function installFetchSignalShim(): void {
  const current = globalThis.fetch as FetchFn & { [SHIMMED]?: true };
  if (current[SHIMMED]) return;

  const shimmed: FetchFn & { [SHIMMED]?: true } = (input, init) => {
    const signal = init?.signal;
    if (!signal) return current(input, init);
    const { signal: _signal, ...rest } = init ?? {};
    if (signal.aborted) return Promise.reject(abortError());
    return new Promise<Response>((resolve, reject) => {
      signal.addEventListener('abort', () => reject(abortError()), { once: true });
      current(input, rest).then(resolve, reject);
    });
  };
  shimmed[SHIMMED] = true;
  globalThis.fetch = shimmed;
}

beforeEach(() => {
  installFetchSignalShim();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
