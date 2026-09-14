/**
 * One function per REST endpoint the frontend calls (frontend.md §3.1). Return
 * types come from the generated contract; none is written by hand.
 */
import type {
  Alert,
  AlertPage,
  AlertSeverity,
  ConfigPatch,
  ConfigResponse,
  Explanation,
  GlobalImportance,
  HealthResponse,
  MachineDetail,
  MachineSummary,
  ModelComparison,
  ModelInfo,
  Plant,
  PlantId,
  PlantSnapshot,
  ReplayCommand,
  ReplayState,
  RiskSeries,
  TelemetrySeries,
  WhatIfRequest,
  WhatIfResponse,
} from '@/contracts';
import { apiGet, apiPost, apiPut, type RequestOptions } from './client';

export const getHealth = (options?: RequestOptions): Promise<HealthResponse> =>
  apiGet<HealthResponse>('/api/health', options);

export const getPlants = (options?: RequestOptions): Promise<Plant[]> =>
  apiGet<Plant[]>('/api/plants', options);

export const getMachines = (
  plantId: PlantId,
  options?: RequestOptions,
): Promise<MachineSummary[]> =>
  apiGet<MachineSummary[]>('/api/machines', { ...options, params: { plant_id: plantId } });

export const getMachine = (
  machineId: string,
  options?: RequestOptions,
): Promise<MachineDetail> =>
  apiGet<MachineDetail>(`/api/machines/${encodeURIComponent(machineId)}`, options);

export const getTelemetry = (
  params: {
    machine_id: string;
    since?: string;
    until?: string;
    channels?: readonly string[];
    max_points?: number;
  },
  options?: RequestOptions,
): Promise<TelemetrySeries> =>
  apiGet<TelemetrySeries>('/api/telemetry', { ...options, params });

export const getRisk = (
  params: { machine_id: string; since?: string; until?: string; max_points?: number },
  options?: RequestOptions,
): Promise<RiskSeries> => apiGet<RiskSeries>('/api/risk', { ...options, params });

export const getAlerts = (
  params: {
    plant_id?: PlantId;
    machine_id?: string;
    since?: string;
    until?: string;
    severity?: AlertSeverity;
    feature?: string;
    limit?: number;
    cursor?: string | null;
  },
  options?: RequestOptions,
): Promise<AlertPage> => apiGet<AlertPage>('/api/alerts', { ...options, params });

export const getAlert = (alertId: string, options?: RequestOptions): Promise<Alert> =>
  apiGet<Alert>(`/api/alerts/${encodeURIComponent(alertId)}`, options);

export const getExplanation = (
  alertId: string,
  model?: Explanation['model_kind'],
  options?: RequestOptions,
): Promise<Explanation> =>
  apiGet<Explanation>(`/api/alerts/${encodeURIComponent(alertId)}/explanation`, {
    ...options,
    params: model ? { model } : {},
  });

export const getComparison = (
  alertId: string,
  options?: RequestOptions,
): Promise<ModelComparison> =>
  apiGet<ModelComparison>(`/api/alerts/${encodeURIComponent(alertId)}/compare`, options);

export const getImportance = (
  machineId: string,
  params?: { since?: string; until?: string; limit?: number },
  options?: RequestOptions,
): Promise<GlobalImportance> =>
  apiGet<GlobalImportance>(
    `/api/machines/${encodeURIComponent(machineId)}/importance`,
    { ...options, params: params ?? {} },
  );

export const getStateAt = (
  plantId: PlantId,
  datasetTs: string,
  options?: RequestOptions,
): Promise<PlantSnapshot> =>
  apiGet<PlantSnapshot>('/api/state_at', {
    ...options,
    params: { plant_id: plantId, dataset_ts: datasetTs },
  });

export const postWhatIf = (
  body: WhatIfRequest,
  options?: RequestOptions,
): Promise<WhatIfResponse> => apiPost<WhatIfResponse>('/api/whatif', body, options);

export const getConfig = (options?: RequestOptions): Promise<ConfigResponse> =>
  apiGet<ConfigResponse>('/api/config', options);

export const putConfig = (
  patch: ConfigPatch,
  options?: RequestOptions,
): Promise<ConfigResponse> => apiPut<ConfigResponse>('/api/config', patch, options);

export const getReplay = (options?: RequestOptions): Promise<ReplayState> =>
  apiGet<ReplayState>('/api/replay', options);

/** All transport control goes through here; the socket is receive-only (R11). */
export const postReplayCommand = (
  command: ReplayCommand,
  options?: RequestOptions,
): Promise<ReplayState> =>
  apiPost<ReplayState>('/api/replay/command', command, options);

export const getModels = (options?: RequestOptions): Promise<ModelInfo[]> =>
  apiGet<ModelInfo[]>('/api/models', options);

/** `req_` + 4 lowercase hex, the form `ReplayCommand.request_id` pins. */
export function newRequestId(): string {
  const bytes = new Uint8Array(2);
  crypto.getRandomValues(bytes);
  return `req_${[...bytes].map((b) => b.toString(16).padStart(2, '0')).join('')}`;
}
