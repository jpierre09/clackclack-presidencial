import type {
  AlertItem,
  AlertReviewDecision,
  AlertReviewItem,
  AlertReviewSummary,
  PresLiveResponse,
  DashboardSummary,
  MapItem,
  MunicipioOption,
  MunicipioNode,
  NovedadItem,
  ProgressData,
  PublicExportMunicipioOption,
  PublicMunicipioPdfExportResponse,
  ReclamationRequest,
  UserSettings,
  ValidationResponse,
} from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ?? "";

function withBase(path: string): string {
  return `${API_BASE}${path}`;
}

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(withBase(path), {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function apiPath(path: string): string {
  return withBase(path);
}

export async function getSummary(): Promise<DashboardSummary> {
  return fetchJson<DashboardSummary>("/api/dashboard/summary");
}

export async function getHierarchy(municipio?: string): Promise<MunicipioNode[]> {
  const query = municipio ? `?municipio=${encodeURIComponent(municipio)}` : "";
  return fetchJson<MunicipioNode[]>(`/api/dashboard/hierarchy${query}`);
}

export async function getMunicipios(): Promise<MunicipioOption[]> {
  return fetchJson<MunicipioOption[]>("/api/dashboard/municipios");
}

export async function getMapData(): Promise<MapItem[]> {
  return fetchJson<MapItem[]>("/api/dashboard/map");
}

export async function getPresLive(): Promise<PresLiveResponse> {
  return fetchJson<PresLiveResponse>("/api/dashboard/pres-live");
}

export async function getAlerts(resolved = false): Promise<AlertItem[]> {
  return fetchJson<AlertItem[]>(`/api/alerts?resolved=${resolved}`);
}

export async function getAlertReviewItems(
  reviewed = false,
  municipio?: string,
  limit = 200,
  offset = 0,
): Promise<AlertReviewItem[]> {
  const params = new URLSearchParams({ reviewed: String(reviewed), limit: String(limit), offset: String(offset) });
  if (municipio) params.set("municipio", municipio);
  return fetchJson<AlertReviewItem[]>(`/api/alerts/review-items?${params}`);
}

export async function getAlertReviewSummary(municipio?: string): Promise<AlertReviewSummary> {
  const params = new URLSearchParams();
  if (municipio) params.set("municipio", municipio);
  const query = params.toString();
  return fetchJson<AlertReviewSummary>(`/api/alerts/review-summary${query ? `?${query}` : ""}`);
}

export async function reviewAlert(
  alertId: number,
  decision: AlertReviewDecision,
  reviewedBy = "dashboard"
): Promise<void> {
  await fetchJson(`/api/alerts/${alertId}/review`, {
    method: "PUT",
    body: JSON.stringify({ decision, reviewed_by: reviewedBy }),
  });
}

export async function correctAlertVotes(
  alertId: number,
  votes: number,
  reviewedBy = "dashboard"
): Promise<void> {
  await fetchJson(`/api/alerts/${alertId}/correct-votes`, {
    method: "PUT",
    body: JSON.stringify({ votes, reviewed_by: reviewedBy }),
  });
}

export async function undoReviewAlert(alertId: number): Promise<void> {
  await fetchJson(`/api/alerts/${alertId}/undo-review`, { method: "PUT" });
}

export async function resolveAlert(alertId: number): Promise<void> {
  await fetchJson(`/api/alerts/${alertId}/resolve`, { method: "PUT" });
}

export async function getValidation(
  mun: string,
  zona: string,
  puesto: string,
  mesa: number,
): Promise<ValidationResponse> {
  return fetchJson<ValidationResponse>(
    `/api/validation/mesa/${mun}/${zona}/${puesto}/${mesa}/PRES`
  );
}

export async function correctValidation(
  mun: string,
  zona: string,
  puesto: string,
  mesa: number,
  payload: {
    ph_votos_lista?: number;
    ph_total_votos?: number;
    votantes_e11?: number;
    votos_urna?: number;
  }
): Promise<void> {
  await fetchJson(`/api/validation/mesa/${mun}/${zona}/${puesto}/${mesa}/PRES`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

function parseFileName(headers: Headers, fallback: string): string {
  const contentDisposition = headers.get("content-disposition") || "";
  const match = contentDisposition.match(/filename=([^;]+)/i);
  if (!match) {
    return fallback;
  }
  return match[1].replace(/"/g, "").trim();
}

export async function generateReclamation(req: ReclamationRequest): Promise<void> {
  const response = await fetch(withBase("/api/reclamation/generate"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  const blob = await response.blob();
  const fileName = parseFileName(response.headers, "reclamacion.docx");
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export async function getPublicExportMunicipios(
  shareToken: string
): Promise<PublicExportMunicipioOption[]> {
  return fetchJson<PublicExportMunicipioOption[]>(
    `/api/validar/public-exports/share/${encodeURIComponent(shareToken)}/municipios`
  );
}

export async function generateMunicipioPdfExport(
  shareToken: string,
  municipioCod: string
): Promise<PublicMunicipioPdfExportResponse> {
  return fetchJson<PublicMunicipioPdfExportResponse>(
    `/api/validar/public-exports/share/${encodeURIComponent(shareToken)}/generate-municipio`,
    {
    method: "POST",
    body: JSON.stringify({ municipio_cod: municipioCod }),
    }
  );
}

export async function getUserSettings(): Promise<UserSettings> {
  return fetchJson<UserSettings>("/api/settings/user");
}

export async function saveUserSettings(payload: UserSettings): Promise<void> {
  await fetchJson("/api/settings/user", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function resolveNovedad(
  adminToken: string,
  noveltyId: number,
  unresolve = false,
  correctedVotes?: number,
): Promise<void> {
  const action = unresolve ? "unresolve" : "resolve";
  const body: Record<string, unknown> = { admin_token: adminToken };
  if (!unresolve && correctedVotes !== undefined) body.corrected_ph_votes = correctedVotes;
  const res = await fetch(withBase(`/api/validar/novedades/${noveltyId}/${action}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `${res.status}`);
  }
}

export async function purgeBadScanNovedades(adminToken: string): Promise<{ deleted: number; deleted_files: number; message: string }> {
  const res = await fetch(withBase("/api/validar/admin/novedades/purge-bad-scan"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ admin_token: adminToken }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${res.status}`);
  return data;
}

export async function getProgress(): Promise<ProgressData> {
  return fetchJson<ProgressData>("/api/validar/progress");
}

export async function getNovedades(): Promise<NovedadItem[]> {
  return fetchJson<NovedadItem[]>("/api/validar/novedades");
}

export async function getAdminValidations(adminToken: string, search = ""): Promise<NovedadItem[]> {
  const params = new URLSearchParams({ admin_token: adminToken });
  if (search) params.set("search", search);
  return fetchJson<NovedadItem[]>(`/api/validar/admin/validations?${params}`);
}

export async function adminCorrectValidation(
  adminToken: string, validationId: number, correctedVotes: number
): Promise<void> {
  const res = await fetch(withBase("/api/validar/admin/correct-validation"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ admin_token: adminToken, validation_id: validationId, corrected_ph_votes: correctedVotes }),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `${res.status}`);
  }
}

export async function downloadNovedadesExport(): Promise<void> {
  const response = await fetch(withBase("/api/validar/novedades/export"));
  if (!response.ok) throw new Error(`${response.status}`);
  const blob = await response.blob();
  const fileName = parseFileName(response.headers, "novedades.xlsx");
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

export async function triggerRescan(limit?: number): Promise<void> {
  const query = limit ? `?limit=${limit}` : "";
  await fetchJson(`/api/system/rescan${query}`, { method: "POST" });
}

export interface DemoSeedResponse {
  inserted_mesas: number;
  inserted_downloads: number;
  inserted_results: number;
  alerts_total: number;
  alerts_danger: number;
  alerts_warning: number;
}

export async function triggerDemoSeed(totalMesas = 180): Promise<DemoSeedResponse> {
  const query = `?total_mesas=${encodeURIComponent(totalMesas)}&clear_first=true`;
  const response = await fetchJson<{ status: string; demo: DemoSeedResponse }>(
    `/api/system/demo-seed${query}`,
    { method: "POST" }
  );
  return response.demo;
}

export async function clearDemoSeed(): Promise<number> {
  const response = await fetchJson<{ status: string; demo: { deleted_downloads: number } }>(
    "/api/system/demo-clear",
    { method: "DELETE" }
  );
  return response.demo.deleted_downloads ?? 0;
}
