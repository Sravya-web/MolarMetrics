import { CalendarRange, Download, FileText, HardDrive, Trash2, Upload, X } from "lucide-react";
import { useEffect, useRef, useState, type DragEvent } from "react";
import { ApiError, api, uploadFiles } from "../api/client";
import type { DatasetMeta, RecordTypeInfo } from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Alert, Badge, Button, Card, PageTitle, Spinner } from "../components/ui";
import { formatBytes, formatDateTime } from "../lib/format";
import { useRouter } from "../lib/router";
import { useSession } from "../state/session";

const COUNT_LABELS: [string, string, string][] = [
  ["appointments", "appointment", "appointments"],
  ["treatments", "treatment", "treatments"],
  ["payments", "payment", "payments"],
  ["patients", "patient", "patients"],
  ["dentists", "dentist", "dentists"],
];

function countsLine(counts: Record<string, number>): string {
  return COUNT_LABELS.filter(([key]) => counts[key])
    .map(([key, one, many]) => `${counts[key].toLocaleString("en-IN")} ${counts[key] === 1 ? one : many}`)
    .join(" · ");
}

function retentionText(hours: number): string {
  const span = hours === 24 ? "24 hours" : hours % 24 === 0 ? `${hours / 24} days` : `${hours} hours`;
  return `Files stay on this computer. Uploaded data is deleted automatically after ${span} without use, or as soon as you remove it.`;
}

export function DataPage() {
  const { state, active, activate, activateSample, remove } = useSession();
  const { navigate } = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejections, setRejections] = useState<{ filename: string; message: string }[]>([]);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [sampleBusy, setSampleBusy] = useState(false);
  const [removing, setRemoving] = useState<DatasetMeta | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);

  if (!state) return null;
  const limits = state.limits;
  const hasData = state.datasets.length > 0;
  const uploading = progress !== null;

  function addFiles(list: FileList | File[]) {
    setError(null);
    setRejections([]);
    const next = [...files];
    const problems: string[] = [];
    for (const file of Array.from(list)) {
      if (!file.name.toLowerCase().endsWith(".csv")) {
        problems.push(`${file.name} isn't a .csv file.`);
        continue;
      }
      if (file.size > limits.max_file_mb * 1024 * 1024) {
        problems.push(`${file.name} is larger than ${limits.max_file_mb} MB.`);
        continue;
      }
      if (next.some((f) => f.name === file.name && f.size === file.size)) continue;
      next.push(file);
    }
    if (next.length > limits.max_files) {
      problems.push(`You can upload up to ${limits.max_files} files at a time.`);
      next.length = limits.max_files;
    }
    setFiles(next);
    if (problems.length) setError(problems.join(" "));
  }

  async function startUpload() {
    setError(null);
    setRejections([]);
    setProgress(0);
    try {
      const batch = await uploadFiles(files, setProgress);
      navigate(`/data/review/${batch.batch_id}`);
    } catch (err) {
      setProgress(null);
      if (err instanceof ApiError && Array.isArray(err.details.files)) {
        setRejections(err.details.files as { filename: string; message: string }[]);
      }
      setError(err instanceof Error ? err.message : "The upload didn't finish. Please try again.");
    }
  }

  async function exploreSample() {
    setSampleBusy(true);
    setError(null);
    try {
      await activateSample();
      navigate("/overview");
    } catch (err) {
      setError(err instanceof Error ? err.message : "The sample data couldn't be opened.");
    } finally {
      setSampleBusy(false);
    }
  }

  async function confirmRemove() {
    if (!removing) return;
    setRemoveBusy(true);
    setRemoveError(null);
    try {
      await remove(removing.id);
      setRemoving(null);
    } catch (err) {
      setRemoveError(err instanceof Error ? err.message : "The dataset couldn't be removed.");
    } finally {
      setRemoveBusy(false);
    }
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    if (!uploading && event.dataTransfer.files.length) addFiles(event.dataTransfer.files);
  };

  return (
    <div className="max-w-3xl space-y-8">
      <PageTitle sub={hasData ? "Upload clinic records, or choose which dataset to explore." : "Turn clinic records into clear insights."}>
        {hasData ? "Data & uploads." : "Understand your dental practice."}
      </PageTitle>

      <div className="space-y-4">
        <div
          onDragOver={(event) => {
            event.preventDefault();
            if (!uploading) setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={`flex flex-col items-center justify-center rounded-xl border-[1.5px] border-dashed px-6 py-12 text-center transition-colors sm:py-14 ${
            dragging ? "border-teal bg-teal-soft" : "border-line-strong bg-surface"
          }`}
        >
          <Upload aria-hidden className="size-9 text-teal" strokeWidth={1.6} />
          <p className="mt-3 text-lg font-semibold text-navy">Drop your CSV files here</p>
          <p className="mt-1 text-sm text-muted">
            Appointments, treatments, payments, patients and dentists. Up to {limits.max_files} files, {limits.max_file_mb} MB each.
          </p>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".csv,text/csv"
            className="sr-only"
            aria-label="Choose CSV files"
            tabIndex={-1}
            onChange={(event) => {
              if (event.target.files) addFiles(event.target.files);
              event.target.value = "";
            }}
          />
          <Button className="mt-5 px-6" onClick={() => inputRef.current?.click()} disabled={uploading}>
            Choose files
          </Button>
        </div>

        <p className="flex items-start justify-center gap-2 text-center text-sm text-muted">
          <HardDrive aria-hidden className="mt-0.5 size-4 shrink-0" strokeWidth={1.8} />
          <span>{retentionText(state.retention_hours)}</span>
        </p>

        {files.length > 0 && (
          <Card className="p-4 sm:p-5">
            <h2 className="text-sm font-semibold text-navy">Selected files</h2>
            <ul className="mt-3 divide-y divide-line">
              {files.map((file) => {
                const rejected = rejections.find((r) => r.filename === file.name);
                return (
                  <li key={`${file.name}-${file.size}`} className="flex items-center gap-3 py-2.5">
                    <FileText aria-hidden className="size-4 shrink-0 text-muted" />
                    <div className="min-w-0 flex-1">
                      <div className="break-all text-sm text-ink">{file.name}</div>
                      <div className="text-xs text-muted">{formatBytes(file.size)}</div>
                      {rejected && <div className="mt-0.5 text-sm text-danger">{rejected.message}</div>}
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setFiles(files.filter((f) => f !== file))}
                      disabled={uploading}
                      aria-label={`Remove ${file.name}`}
                    >
                      <X aria-hidden className="size-4" />
                    </Button>
                  </li>
                );
              })}
            </ul>
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button onClick={startUpload} disabled={uploading || files.length === 0}>
                <Upload aria-hidden className="size-4" />
                Upload and review
              </Button>
              {uploading && (
                <div className="flex min-w-[220px] flex-1 items-center gap-3">
                  <div
                    role="progressbar"
                    aria-label="Upload progress"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round((progress ?? 0) * 100)}
                    className="h-2 flex-1 overflow-hidden rounded-full bg-line"
                  >
                    <div className="h-full rounded-full bg-teal transition-[width]" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
                  </div>
                  <span className="text-sm text-muted">{(progress ?? 0) < 1 ? `Uploading… ${Math.round((progress ?? 0) * 100)}%` : "Reading files…"}</span>
                </div>
              )}
            </div>
          </Card>
        )}

        {error && <Alert tone="error">{error}</Alert>}

        <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-sm">
          <button
            type="button"
            aria-expanded={templatesOpen}
            aria-controls="templates-panel"
            onClick={() => setTemplatesOpen((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-md font-medium text-teal hover:underline"
          >
            <Download aria-hidden className="size-4" />
            Download templates
          </button>
          <span aria-hidden className="h-4 w-px bg-line-strong" />
          <button
            type="button"
            onClick={exploreSample}
            disabled={sampleBusy}
            className="inline-flex items-center gap-1.5 rounded-md font-medium text-teal hover:underline disabled:text-muted"
          >
            {sampleBusy ? "Opening sample data…" : "Explore sample data"}
          </button>
        </div>
      </div>

      {templatesOpen && <TemplatesPanel onClose={() => setTemplatesOpen(false)} />}

      {hasData && (
        <section aria-labelledby="datasets-title" className="space-y-3">
          <h2 id="datasets-title" className="text-lg font-semibold text-navy">
            Your datasets
          </h2>
          <ul className="space-y-3">
            {state.datasets.map((d) => (
              <li key={d.id}>
                <Card as="article" className="p-4 sm:p-5">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0 space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="break-words text-base font-semibold text-navy">{d.name}</h3>
                        {d.kind === "sample" && <Badge>Sample data</Badge>}
                        {d.id === active?.id && <Badge tone="teal">In use</Badge>}
                      </div>
                      <p className="flex items-center gap-1.5 text-sm text-ink">
                        <CalendarRange aria-hidden className="size-4 text-muted" />
                        {d.coverage.label}
                      </p>
                      <p className="text-sm text-muted">{countsLine(d.counts)}</p>
                      {d.expires_at && (
                        <p className="text-xs text-muted">Deleted automatically if not used before {formatDateTime(d.expires_at)}.</p>
                      )}
                      {d.import_notes.map((note) => (
                        <p key={note} className="text-xs text-muted">
                          {note}
                        </p>
                      ))}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {d.id !== active?.id && (
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={async () => {
                            await activate(d.id);
                            navigate("/overview");
                          }}
                        >
                          Use this dataset
                        </Button>
                      )}
                      <Button variant="danger-ghost" size="sm" onClick={() => setRemoving(d)}>
                        <Trash2 aria-hidden className="size-4" />
                        {d.kind === "sample" ? "Remove from session" : "Remove dataset"}
                      </Button>
                    </div>
                  </div>
                </Card>
              </li>
            ))}
          </ul>
        </section>
      )}

      <ConfirmDialog
        open={removing !== null}
        title={removing?.kind === "sample" ? "Remove the sample data from this session?" : `Remove ${removing?.name ?? "this dataset"}?`}
        confirmLabel={removing?.kind === "sample" ? "Remove from session" : "Remove dataset"}
        busy={removeBusy}
        onCancel={() => {
          setRemoving(null);
          setRemoveError(null);
        }}
        onConfirm={confirmRemove}
      >
        {removing?.kind === "sample" ? (
          <p>The sample stays available: you can explore it again at any time.</p>
        ) : (
          <p>This permanently deletes the imported records from this computer. You can upload the files again later.</p>
        )}
        {removeError && <p className="mt-2 text-danger">{removeError}</p>}
      </ConfirmDialog>
    </div>
  );
}

function TemplatesPanel({ onClose }: { onClose: () => void }) {
  const [types, setTypes] = useState<RecordTypeInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const ctl = new AbortController();
    api.recordTypes(ctl.signal).then(setTypes).catch((err) => {
      if (!(err instanceof DOMException)) setError("The templates couldn't be loaded.");
    });
    return () => ctl.abort();
  }, []);
  return (
    <Card className="p-5 sm:p-6" aria-labelledby="templates-title">
      <div id="templates-panel" className="flex items-start justify-between gap-4">
        <div>
          <h2 id="templates-title" className="text-lg font-semibold text-navy">
            CSV templates
          </h2>
          <p className="mt-1 text-sm text-muted">
            Only appointments are required. Each extra file adds more to your overview. Use patient codes, not names or phone numbers.
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close templates">
          <X aria-hidden className="size-4" />
        </Button>
      </div>
      {error && <Alert tone="error" className="mt-4">{error}</Alert>}
      {!types && !error && <div className="mt-4"><Spinner label="Loading templates…" /></div>}
      {types && (
        <ul className="mt-4 divide-y divide-line">
          {types.map((t) => (
            <li key={t.key} className="flex flex-wrap items-start justify-between gap-3 py-3.5">
              <div className="min-w-0 max-w-2xl space-y-1">
                <h3 className="text-sm font-semibold text-navy">
                  {t.label} {t.key === "appointments" ? <span className="font-normal text-muted">(required)</span> : <span className="font-normal text-muted">(optional)</span>}
                </h3>
                <p className="text-sm text-ink">One row = {t.one_row.charAt(0).toLowerCase() + t.one_row.slice(1)}</p>
                <p className="text-sm text-muted">{t.purpose}</p>
                <p className="text-xs text-muted">
                  Required columns: {t.fields.filter((f) => f.required).map((f) => f.label).join(", ")}
                  {t.key === "treatments" ? ", and Net fee or Listed fee" : ""}
                </p>
              </div>
              <a href={t.template_url} download className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-md text-sm font-medium text-teal hover:underline">
                <Download aria-hidden className="size-4" />
                {t.key}.csv
              </a>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex flex-wrap gap-x-6 gap-y-2 border-t border-line pt-4 text-sm">
        <a href="/api/templates/all.zip" download className="inline-flex items-center gap-1.5 font-medium text-teal hover:underline">
          <Download aria-hidden className="size-4" />
          All templates (.zip)
        </a>
        <a href="/api/templates/example-bundle.zip" download className="inline-flex items-center gap-1.5 font-medium text-teal hover:underline">
          <Download aria-hidden className="size-4" />
          Example clinic files (.zip)
        </a>
      </div>
    </Card>
  );
}
