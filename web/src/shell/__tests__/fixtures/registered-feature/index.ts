/**
 * Stands in for a Phase-4 feature module in the registry test: a thin
 * registration module with a side effect, exactly the shape `features/registry.ts`
 * expects. It lives under `__tests__/` so the production glob never sees it.
 */
import { registerSlot } from '@/shell/slots';

registerSlot('detail.charts', () => null);

export const registeredBy = 'registered-feature';
