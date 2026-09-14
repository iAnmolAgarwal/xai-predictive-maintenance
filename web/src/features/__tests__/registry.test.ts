import { describe, expect, it } from 'vitest';
import { registeredFeatureModules } from '../registry';
import { SLOT_NAMES } from '@/shell/slots';

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
});
