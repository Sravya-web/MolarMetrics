// Mirrors molarmetrics/api/schemas.py and molarmetrics/ingest/validate.py.
// Money values are integer paise; display strings are formatted by the server.

export type DatasetKind = "sample" | "uploaded";

export interface DatasetRef {
  id: string;
  name: string;
  kind: DatasetKind;
}

export interface Coverage {
  start: string;
  end: string;
  label: string;
}

export interface DatasetMeta extends DatasetRef {
  coverage: Coverage;
  capabilities: string[];
  counts: Record<string, number>;
  import_notes: string[];
  created_at: string;
  last_used_at: string;
  expires_at: string | null;
  active: boolean;
}

export interface SessionState {
  datasets: DatasetMeta[];
  active_dataset_id: string | null;
  questions_available: boolean;
  retention_hours: number;
  limits: { max_file_mb: number; max_files: number };
}

export type ValueKind = "inr" | "count" | "percent" | "text" | "month";

export interface MetricOut {
  key: string;
  label: string;
  value: number | string | null;
  kind: ValueKind;
  unit: string;
  aggregation: string;
  date_basis: string | null;
  note: string | null;
  formatted: string;
}

export interface ColumnOut {
  key: string;
  label: string;
  kind: ValueKind;
  unit: string;
  aggregation: string;
}

export interface TableOut {
  columns: ColumnOut[];
  rows: Record<string, string | number | null>[];
  display: Record<string, string>[];
}

export interface ChartOut {
  type: "bar" | "grouped_bar" | "stacked_bar" | "line";
  x: string;
  series: { key: string; label: string; kind: ValueKind }[];
  title: string;
  y_title: string;
  orientation: "v" | "h";
}

export interface AnalysisPayload {
  id: string;
  kind: "kpis" | "appointments" | "procedures" | "finances" | "outstanding";
  dataset: DatasetRef;
  title: string;
  status: "ok" | "empty" | "unavailable" | "error";
  date_range: Record<string, string>;
  period_label: string;
  filters: Record<string, unknown>;
  metrics: MetricOut[];
  facts: string[];
  table: TableOut | null;
  chart: ChartOut | null;
  definitions: { key: string; label: string; text: string }[];
  notes: string[];
  warnings: string[];
  unavailable_reason: string | null;
  export_url: string | null;
}

export interface KpiOut {
  key: string;
  label: string;
  status: "available" | "unavailable";
  kind: "inr" | "count" | "percent";
  value: number | null;
  display: string | null;
  exact: string | null;
  detail: string | null;
  reason: string | null;
  definition: string;
}

export interface FinanceRow {
  month: string;
  month_label: string;
  billed_paise: number;
  collected_paise: number | null;
  cumulative_billed_paise: number;
  cumulative_collected_paise: number | null;
  billed: string;
  collected: string | null;
  cumulative_billed: string;
  cumulative_collected: string | null;
}

export interface AppointmentRow {
  month: string;
  month_label: string;
  scheduled: number;
  completed: number;
  cancelled: number;
  no_show: number;
  no_show_rate_pct: number | null;
}

export interface OverviewPayload {
  dataset: DatasetRef;
  period: { start: string; end: string; label: string; clamped: boolean };
  presets: { key: string; label: string; start: string; end: string }[];
  kpis: KpiOut[];
  finance: {
    has_collections: boolean;
    rows: FinanceRow[];
    total_billed: string;
    total_collected: string | null;
    export_url: string;
  } | null;
  appointments: { rows: AppointmentRow[]; export_url: string } | null;
  top_procedures: {
    rows: { procedure: string; billed_paise: number; billed: string; treatment_count: number; share_pct: number | null }[];
    total_procedures: number;
    export_url: string;
  } | null;
  unavailable: string[];
  notes: string[];
  warnings: string[];
}

export interface AskResponse {
  id: string;
  dataset: DatasetRef;
  question: string;
  answer: string;
  status: "answered" | "out_of_scope" | "not_available" | "no_match";
  results: AnalysisPayload[];
}

// --- uploads -------------------------------------------------------------------
export type RecordType = "appointments" | "treatments" | "payments" | "patients" | "dentists";
export type StatusValue = "completed" | "cancelled" | "no_show";
export type MoneyUnit = "rupees" | "paise";

export interface FileConfig {
  file_id: string;
  record_type: RecordType | null;
  mapping: Record<string, string>;
  date_formats: Record<string, string>;
  money_unit: MoneyUnit | null;
  status_map: Record<string, StatusValue>;
}

export interface ImportConfig {
  name: string;
  files: FileConfig[];
  review_decisions: Record<string, "include" | "exclude">;
}

export type Severity = "blocking" | "review" | "warning" | "info";

export interface Issue {
  severity: Severity;
  code: string;
  file_id: string | null;
  file: string | null;
  row: number | null;
  field: string | null;
  message: string;
  suggestion: string;
  value: string | null;
}

export interface FileReport {
  file_id: string;
  filename: string;
  record_type: RecordType | null;
  suggested_record_type: RecordType | null;
  rows: number;
  columns: string[];
  mapping: Record<string, string>;
  missing_required: string[];
  date_fields: {
    field: string;
    label: string;
    column: string;
    candidates: string[];
    detected: string | null;
    ambiguous: boolean;
    chosen: string | null;
    examples: string[];
  }[];
  money_unit: MoneyUnit | null;
  money_unit_suggestion: MoneyUnit | null;
  money_fields: { field: string; label: string; column: string; examples: { raw: string; interpreted: string | null }[] }[];
  status_labels: { key: string; label: string; count: number; suggested: StatusValue | null; chosen: StatusValue | null }[];
  ignored_columns: string[];
  blocking: number;
  warnings: number;
}

export interface ReviewGroup {
  code: string;
  title: string;
  description: string;
  count: number;
  examples: string[];
  include_effect: string;
  exclude_effect: string;
  decision: "include" | "exclude" | null;
}

export interface ValidationReport {
  ready: boolean;
  blocking: number;
  needs_review: number;
  warnings: number;
  issues: Issue[];
  issues_total: number;
  files: FileReport[];
  review_groups: ReviewGroup[];
  counts: Record<string, number>;
  coverage: { start: string; end: string } | null;
  capabilities: string[];
  summary: string;
}

export interface UploadBatch {
  batch_id: string;
  files: { file_id: string; filename: string; size: number; rows: number; columns: string[]; preview: string[][] }[];
  config: ImportConfig;
  report: ValidationReport;
  /** file id -> record type -> suggested mapping (applied when the user changes a file's type) */
  suggestions: Record<string, Record<string, { mapping: Record<string, string>; status_map: Record<string, StatusValue> }>>;
}

export interface RecordTypeInfo {
  key: RecordType;
  label: string;
  one_row: string;
  purpose: string;
  depends_on: RecordType | null;
  has_money: boolean;
  fields: { key: string; label: string; kind: string; required: boolean; description: string }[];
  template_url: string;
}
