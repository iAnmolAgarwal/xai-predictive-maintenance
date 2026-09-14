import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { MOCK_MARKER } from '../fixtures';

const DIST = join(process.cwd(), 'dist');

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

describe('no-mock-in-prod', () => {
  it('ships no mock code in the production bundle', () => {
    // The bundle is produced by `pnpm build`; CI runs this test after it, and
    // the assertion is skipped locally only when no build has been made yet.
    if (!existsSync(DIST)) {
      expect(MOCK_MARKER).toBe('__MSW_MOCK_MARKER__');
      return;
    }

    const offenders = walk(DIST).filter((file) => {
      if (!/\.(js|css|html)$/.test(file)) return false;
      const contents = readFileSync(file, 'utf8');
      return contents.includes(MOCK_MARKER) || contents.includes('msw/browser');
    });

    expect(offenders).toEqual([]);
  });
});
