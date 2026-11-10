import type {
  AskResponse,
  DatasetMeta,
  ImportConfig,
  OverviewPayload,
  RecordTypeInfo,
  SessionState,
  UploadBatch,
  ValidationReport,
} from "./types";

// Every state-changing request carries this header; the server refuses
// requests without it (a cross-site page cannot add custom headers).
const APP_HEADER = { "X-MolarMetrics": "1" };
const GENERIC = "Something went wrong. Please try again.";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as { error?: { code?: string; message?: string } & Record<string, unknown> };
    if (body.error?.message) {
      const { code, message, ...details } = body.error;
      return new ApiError(response.status, code ?? "error", message, details);
    }
  } catch {
    // Not JSON (e.g. the server is not running): fall through to a plain message.
  }
  if (response.status === 502 || response.status === 504) {
    return new ApiError(response.status, "unreachable", "MolarMetrics isn't responding. Check that it is running, then try again.");
  }
  return new ApiError(response.status, "error", GENERIC);
}

async function request<T>(method: string, path: string, options: { body?: unknown; signal?: AbortSignal } = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers: options.body !== undefined ? { ...APP_HEADER, "Content-Type": "application/json" } : APP_HEADER,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
      credentials: "same-origin",
    });
  } catch (error) {
    if (isAbort(error)) throw error;
    throw new ApiError(0, "network", "MolarMetrics isn't responding. Check that it is running, then try again.");
  }
  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

const q = (params: Record<string, string | undefined>) => {
  const entries = Object.entries(params).filter((e): e is [string, string] => Boolean(e[1]));
  return entries.length ? `?${new URLSearchParams(entries).toString()}` : "";
};

export const api = {
  session: (signal?: AbortSignal) => request<SessionState>("GET", "/api/session", { signal }),
  activate: (datasetId: string) => request<SessionState>("PUT", "/api/session/active", { body: { dataset_id: datasetId } }),
  activateSample: () => request<DatasetMeta>("POST", "/api/datasets/sample"),
  removeDataset: (datasetId: string) => request<SessionState>("DELETE", `/api/datasets/${datasetId}`),
  overview: (datasetId: string, period: { start?: string; end?: string }, signal?: AbortSignal) =>
    request<OverviewPayload>("GET", `/api/datasets/${datasetId}/overview${q(period)}`, { signal }),
  suggestions: (datasetId: string, signal?: AbortSignal) =>
    request<{ questions: string[] }>("GET", `/api/datasets/${datasetId}/suggestions`, { signal }),
  ask: (datasetId: string, question: string, signal?: AbortSignal) =>
    request<AskResponse>("POST", `/api/datasets/${datasetId}/ask`, { body: { question }, signal }),
  recordTypes: (signal?: AbortSignal) => request<RecordTypeInfo[]>("GET", "/api/record-types", { signal }),
  getUpload: (batchId: string, signal?: AbortSignal) => request<UploadBatch>("GET", `/api/uploads/${batchId}`, { signal }),
  validate: (batchId: string, config: ImportConfig, signal?: AbortSignal) =>
    request<ValidationReport>("POST", `/api/uploads/${batchId}/validate`, { body: config, signal }),
  removeFile: (batchId: string, fileId: string) => request<UploadBatch>("DELETE", `/api/uploads/${batchId}/files/${fileId}`),
  cancelUpload: (batchId: string) => request<void>("DELETE", `/api/uploads/${batchId}`),
  importUpload: (batchId: string, config: ImportConfig) =>
    request<DatasetMeta>("POST", `/api/uploads/${batchId}/import`, { body: config }),
};

/** Upload files with progress (fetch cannot report upload progress). */
export function uploadFiles(files: File[], onProgress: (fraction: number) => void): Promise<UploadBatch> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const file of files) form.append("files", file, file.name);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/uploads");
    xhr.setRequestHeader("X-MolarMetrics", "1");
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as UploadBatch);
        return;
      }
      const body = xhr.response as { error?: { code?: string; message?: string } & Record<string, unknown> } | null;
      if (body?.error?.message) {
        const { code, message, ...details } = body.error;
        reject(new ApiError(xhr.status, code ?? "error", message, details));
      } else {
        reject(new ApiError(xhr.status, "error", GENERIC));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "MolarMetrics isn't responding. Check that it is running, then try again."));
    xhr.send(form);
  });
}
