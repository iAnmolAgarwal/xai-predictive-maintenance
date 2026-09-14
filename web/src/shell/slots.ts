/**
 * The slot registry (frontend.md §2, "Cross-task integration points").
 *
 * The shell ships seven named, empty slots. A Phase-4 feature fills one by
 * calling `registerSlot` from its own `index.ts`; nothing in `shell/` is edited
 * to make that happen, so no two tasks ever touch the same file. A slot with no
 * registration renders its designed production empty state — not a stub.
 */
import { createElement, type ComponentType, type ReactElement } from 'react';
import { SlotFallback } from './layout/SlotFallback';

export const SLOT_NAMES = [
  'topbar.playback',
  'rail.feed',
  'detail.shap',
  'detail.whatif',
  'detail.compare',
  'floor.grid',
  'detail.charts',
] as const;

export type SlotName = (typeof SLOT_NAMES)[number];

/** Props a slot passes through to whatever component fills it. */
export type SlotProps = Record<string, unknown>;

const registry = new Map<SlotName, ComponentType<SlotProps>>();

/** Register the component that fills `name`. Last registration wins. */
export function registerSlot(name: SlotName, component: ComponentType<SlotProps>): void {
  registry.set(name, component);
}

/** The component currently filling `name`, if any. */
export function getSlotComponent(name: SlotName): ComponentType<SlotProps> | undefined {
  return registry.get(name);
}

/** Test-only: drop every registration so slots fall back to their empty states. */
export function clearSlots(): void {
  registry.clear();
}

export type SlotElementProps = { name: SlotName } & SlotProps;

/**
 * Render a slot. Written with `createElement` rather than JSX so this file stays
 * a `.ts` module, as the file map requires.
 */
export function Slot({ name, ...props }: SlotElementProps): ReactElement {
  const Filled = registry.get(name);
  if (Filled) return createElement(Filled, props);
  return createElement(SlotFallback, { name });
}
