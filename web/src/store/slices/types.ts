import type { StateCreator } from 'zustand';
import type { Store } from '../index';

/** Every slice is created against the whole store, with selector subscriptions. */
export type SliceCreator<T> = StateCreator<
  Store,
  [['zustand/subscribeWithSelector', never]],
  [],
  T
>;
