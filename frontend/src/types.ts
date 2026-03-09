export type Severity = "danger" | "warning" | "info";

export interface DashboardSummary {
  total_mesas: number;
  total_puestos: number;
  total_municipios: number;
  e14_downloaded: number;
  e14_processed: number;
  e14_errors: number;
  alerts_total: number;
  alerts_danger: number;
  alerts_warning: number;
  alerts_resolved: number;
  novedades_count: number;
}

export interface NovedadItem {
  id: number;
  municipio_cod: string;
  zona_cod: string;
  puesto_cod: string;
  mesa: number;
  corporacion: string;
  validated_by: string;
  action: string;
  corrected_ph_votes: number | null;
  novelty_note: string;
  validated_at: string;
  ai_ph_votes: number | null;
  votos_urna: number | null;
  ocr_confidence: number | null;
  municipio: string | null;
  puesto_nombre: string | null;
  departamento: string | null;
}

export interface ValidationItem extends NovedadItem {
  // Same structure, reused for admin corrections list
}

export interface MesaData {
  mesa: number;
  sen_votes: number | null;
  cam_votes: number | null;
  sen_status: string | null;
  cam_status: string | null;
  sen_conf: number | null;
  cam_conf: number | null;
  alert_type: string | null;
  severity: Severity | null;
  discrepancy_pct: number | null;
  has_novelty: 0 | 1;
}

export interface PuestoNode {
  puesto_cod: string;
  nombre: string;
  mesas: number;
  lat: number | null;
  lon: number | null;
  alert_count: number;
  mesas_data: MesaData[];
}

export interface ZonaNode {
  zona_cod: string;
  total_mesas: number;
  alert_count: number;
  puestos: PuestoNode[];
}

export interface MunicipioNode {
  municipio_cod: string;
  municipio: string;
  total_mesas: number;
  alerts_danger: number;
  alerts_warning: number;
  zonas: ZonaNode[];
}

export interface AlertItem {
  id: number;
  municipio_cod: string;
  zona_cod: string;
  puesto_cod: string;
  mesa: number;
  municipio: string;
  puesto_nombre: string;
  alert_type: string;
  severity: Severity;
  description: string;
  discrepancy_pct: number | null;
  is_resolved: 0 | 1;
  created_at: string;
}

export interface MapItem {
  id: string;
  municipio: string;
  municipio_cod: string;
  zona_cod: string;
  puesto_cod: string;
  nombre: string;
  mesas: number;
  lat: number;
  lon: number;
  danger_count: number;
  warning_count: number;
  novelty_count: number;
}

export interface ValidationResult {
  id: number;
  download_id: number;
  corporacion: string;
  ph_votos_lista: number | null;
  ph_total_votos: number | null;
  votantes_e11: number | null;
  votos_urna: number | null;
  status: string;
  ocr_confidence: number | null;
  filename: string;
  filepath: string;
}

export interface ValidationResponse {
  result: ValidationResult | null;
  puesto: {
    municipio: string;
    nombre: string;
    zona_cod: string;
    puesto_cod: string;
  } | null;
  alerts: AlertItem[];
}

export interface UserSettings {
  user_name: string;
  user_cc: string;
}

export interface ReclamationRequest {
  level: "municipio" | "zona" | "puesto" | "mesa";
  municipio_cod: string;
  zona_cod?: string;
  puesto_cod?: string;
  mesa?: number;
  user_name?: string;
  user_cc?: string;
}

export interface CamaraPartyRow {
  party_name: string;
  votes: number;
  vote_share_pct: number;
  curules_current: number;
  projected_votes: number;
  curules_projected: number;
  color: string;
  logo_file?: string | null;
  is_pacto_historico: boolean;
}

export interface CamaraTimelinePoint {
  mesas_reportadas: number;
  coverage_pct: number;
  timestamp: string | null;
  party_votes: Record<string, number>;
  party_curules: Record<string, number>;
}

export interface CamaraLiveResponse {
  curules_total: number;
  mesas_total: number;
  mesas_reportadas: number;
  coverage_pct: number;
  projection_scale: number;
  total_votes_current: number;
  cociente_electoral_current: number;
  threshold_votes_current: number;
  parties: CamaraPartyRow[];
  tracked_parties: string[];
  seat_order_current: string[];
  seat_order_visual_current?: string[];
  seat_order_projected: string[];
  seat_order_visual_projected?: string[];
  timeline: CamaraTimelinePoint[];
  updated_at: string;
}
