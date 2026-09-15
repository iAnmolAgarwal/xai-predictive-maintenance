import { describe, expect, it } from 'vitest';
import { clearSlots, getSlotComponent, SLOT_NAMES } from '@/shell/slots';
import { registeredFeatureModules } from '../registry';

describe('feature registry', () => {
  it('imports every feature module for its side effects, with no edit per feature', () => {
    // The glob resolves to whatever feature directories exist, so a Phase-4 task
    // integrates by adding its own directory and never by editing this file.
    expect(Array.isArray(registeredFeatureModules)).toBe(true);
    for (const path of registeredFeatureModules) {
      expect(path).toMatch(/^\.\/[a-z-]+\/index\.ts$/);
    }
    // Registration is by slot name, and the seven names are fixed in Phase 3.
    expect(registeredFeatureModules.length).toBeLessThanOrEqual(SLOT_NAMES.length);
  });

  it('runs the registration side effect of a feature-shaped module', async () => {
    // The same glob pattern the registry uses, pointed at a fixture directory:
    // this proves the mechanism itself, which has no other coverage until the
    // first Phase-4 feature lands.
    clearSlots();
    expect(getSlotComponent('detail.charts')).toBeUndefined();

    const modules = import.meta.glob<{ registeredBy: string }>(
      '../../shell/__tests__/fixtures/*/index.ts',
    );
    const paths = Object.keys(modules);
    expect(paths).toHaveLength(1);

    const load = modules[paths[0] ?? ''];
    expect(load).toBeDefined();
    const loaded = await load?.();

    expect(loaded?.registeredBy).toBe('registered-feature');
    expect(getSlotComponent('detail.charts')).toBeDefined();
    clearSlots();
  });
});
