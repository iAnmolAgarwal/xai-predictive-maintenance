/**
 * vitest-axe ships no `vitest` module augmentation of its own, so the
 * `toHaveNoViolations` matcher registered in `vitest.setup.ts` is declared here.
 * The shape mirrors `@testing-library/jest-dom`'s augmentation exactly, so the
 * two merge into one `Assertion` interface instead of shadowing each other.
 */
/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-empty-object-type, @typescript-eslint/no-unused-vars */
import 'vitest';
import type { AxeMatchers } from 'vitest-axe/matchers';

declare module 'vitest' {
  interface Assertion<T = any> extends AxeMatchers {}
  interface AsymmetricMatchersContaining extends AxeMatchers {}
}
