/** Derived reads over the store. Pure functions, so they are unit-testable. */
import type { Alert, Explanation, PlantSnapshot } from '@/contracts';
import type { AlertFilters } from './slices/alerts';
import type { Store } from './index';

/**
 * Per-machine historical explanation, derived from a `PlantSnapshot`
 * (frontend.md §3.1). There is no `active_explanation_ids` map on the wire and
 * none is needed: at most one alert per machine is open at a time, so a machine
 * absent from `active_alerts` correctly has no active explanation.
 */
export function historicalExplanations(
  snapshot: PlantSnapshot,
): Record<string, Explanation | null> {
  const byAlert = new Map(snapshot.active_explanations.map((e) => [e.alert_id, e]));
  const result: Record<string, Explanation | null> = {};
  for (const alert of snapshot.active_alerts) {
    result[alert.machine_id] = byAlert.get(alert.alert_id) ?? null;
  }
  return result;
}

/** Alerts in rail order with the three filters composed. */
export function visibleAlerts(state: Store): Alert[] {
  const { byId, order, filters } = state.alerts;
  const alerts: Alert[] = [];
  for (const id of order) {
    const alert = byId[id];
    if (alert && matchesFilters(alert, filters)) alerts.push(alert);
  }
  return alerts;
}

/** All three filters compose; an empty list for a facet means "no filter". */
export function matchesFilters(alert: Alert, filters: AlertFilters): boolean {
  if (filters.machineIds.length > 0 && !filters.machineIds.includes(alert.machine_id)) {
    return false;
  }
  if (filters.severities.length > 0 && !filters.severities.includes(alert.severity)) {
    return false;
  }
  if (filters.feature !== null && alert.top_feature !== filters.feature) return false;
  return true;
}

/** The `top_feature` values actually present in the rail, for its filter. */
export function availableTopFeatures(state: Store): string[] {
  const features = new Set<string>();
  for (const id of state.alerts.order) {
    const alert = state.alerts.byId[id];
    if (alert) features.add(alert.top_feature);
  }
  return [...features].sort();
}

/** The currently selected plant descriptor, if one has been chosen. */
export function selectedPlant(state: Store) {
  const id = state.plants.selected;
  return id === null ? null : (state.plants.byId[id] ?? null);
}

/** Machine count for the selected plant; the grid is driven by this, never 12. */
export function selectedMachineCount(state: Store): number {
  return selectedPlant(state)?.machine_count ?? 0;
}
