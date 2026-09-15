import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';
import { describe, expect, it } from 'vitest';
import { MOCK_MARKER } from '../fixtures';

const ROOT = process.cwd();
const DIST = join(ROOT, 'dist');

/** Anything that would let a production page register or import the mock stack. */
const MOCK_PATTERN = /mockServiceWorker|msw/i;

/** Text-ish assets whose contents are worth grepping; fonts and images are not. */
const TEXT_EXTENSIONS = new Set([
  '.js',
  '.mjs',
  '.cjs',
  '.css',
  '.html',
  '.json',
  '.map',
  '.svg',
  '.txt',
  '.webmanifest',
]);

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

/**
 * The production bundle is the artefact under test, so the test builds it when it
 * is not already there rather than skipping — a guard that passes because it had
 * nothing to inspect is worse than no guard at all.
 */
function ensureDist(): void {
  if (existsSync(DIST)) return;
  execFileSync('pnpm', ['build'], { cwd: ROOT, stdio: 'ignore' });
}

describe('no-mock-in-prod', () => {
  it('ships no mock code, and no service worker, in the production bundle', () => {
    ensureDist();
    expect(existsSync(DIST), 'pnpm build produced no dist/').toBe(true);

    const offenders = walk(DIST).filter((file) => {
      const path = relative(DIST, file);
      if (MOCK_PATTERN.test(path)) return true;
      if (!TEXT_EXTENSIONS.has(extname(file))) return false;
      const contents = readFileSync(file, 'utf8');
      return MOCK_PATTERN.test(contents) || contents.includes(MOCK_MARKER);
    });

    expect(offenders.map((file) => relative(DIST, file))).toEqual([]);
  }, 180_000); // A cold build has to fit inside the case's budget.

  it('keeps the marker the guard greps for in mock code only', () => {
    expect(MOCK_MARKER).toBe('__MSW_MOCK_MARKER__');
    const handlers = readFileSync(join(ROOT, 'src/mock/handlers.ts'), 'utf8');
    expect(handlers).toContain('MOCK_MARKER');
  });
});
