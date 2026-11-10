import { AlertCircle, ArrowLeft, Check, CheckCircle2, CircleAlert, Download, Eye, FileText, Info, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, api, isAbort } from "../api/client";
import type { FileConfig, FileReport, ImportConfig, Issue, RecordType, RecordTypeInfo, ReviewGroup, StatusValue, UploadBatch, ValidationReport } from "../api/types";
import { Alert, Badge, Button, Card, PageTitle, Select, Spinner } from "../components/ui";
import { useRouter } from "../lib/router";
import { useSession } from "../state/session";

const DATE_FORMATS: [string, string][] = [
  ["YYYY-MM-DD", "Year-month-day (2025-04-03)"],
  ["DD/MM/YYYY", "Day/month/year (03/04/2025 = 3 April)"],
  ["MM/DD/YYYY", "Month/day/year (04/03/2025 = 3 April)"],
  ["DD-MM-YYYY", "Day-month-year (03-04-2025 = 3 April)"],
  ["MM-DD-YYYY", "Month-day-year (04-03-2025 = 3 April)"],
  ["DD.MM.YYYY", "Day.month.year (03.04.2025)"],
  ["YYYY/MM/DD", "Year/month/day (2025/04/03)"],
  ["D MMM YYYY", "Day, month name, year (3 Apr 2025)"],
  ["MMM D, YYYY", "Month name, day, year (Apr 3, 2025)"],
];
const STATUS_OPTIONS: [StatusValue, string][] = [
  ["completed", "Completed"],
  ["cancelled", "Cancelled"],
  ["no_show", "No-show"],
];
const SEVERITY: Record<Issue["severity"], { label: string; icon: ReactNode }> = {
  blocking: { label: "Must fix", icon: <AlertCircle aria-hidden className="size-4 text-danger" /> },
  review: { label: "Needs review", icon: <Eye aria-hidden className="size-4 text-amber" /> },
  warning: { label: "Check", icon: <CircleAlert aria-hidden className="size-4 text-amber" /> },
  info: { label: "Note", icon: <Info aria-hidden className="size-4 text-muted" /> },
};

function Stepper({ step }: { step: 2 | 3 }) {
  const steps = ["Upload", "Review", "Finish"];
  return (
    <ol aria-label="Import steps" className="mx-auto flex w-full max-w-md items-start">
      {steps.map((label, i) => {
        const n = i + 1;
        const done = n < step || (step === 3 && n === 3);
        const current = n === step && !done;
        return (
          <li key={label} aria-current={current ? "step" : undefined} className="relative flex flex-1 flex-col items-center">
            {i > 0 && <span aria-hidden className={`absolute right-1/2 top-[15px] h-0.5 w-full ${n <= step ? "bg-teal" : "bg-line"}`} />}
            <span
              className={`relative z-10 flex size-8 items-center justify-center rounded-full border-2 text-sm font-semibold ${
                done || current ? "border-teal bg-teal text-white" : "border-line-strong bg-surface text-muted"
              }`}
            >
              {done ? <Check aria-hidden className="size-4" strokeWidth={3} /> : n}
            </span>
            <span className={`mt-1.5 text-sm ${current ? "font-semibold text-navy" : "text-ink"}`}>
              {label}
              <span className="sr-only">{done ? " (done)" : current ? " (current step)" : ""}</span>
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function ReviewPage({ batchId }: { batchId: string }) {
  const { navigate } = useRouter();
  const { refresh, setNotice } = useSession();
  const [batch, setBatch] = useState<UploadBatch | null>(null);
  const [config, setConfig] = useState<ImportConfig | null>(null);
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [types, setTypes] = useState<RecordTypeInfo[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [phase, setPhase] = useState<"review" | "importing" | "done">("review");
  const validation = useRef<{ seq: number; ctl: AbortController | null; timer: number | null }>({ seq: 0, ctl: null, timer: null });

  useEffect(() => {
    const ctl = new AbortController();
    Promise.all([api.getUpload(batchId, ctl.signal), api.recordTypes(ctl.signal)])
      .then(([b, t]) => {
        setBatch(b);
        setConfig(b.config);
        setReport(b.report);
        setTypes(t);
        setSelected(b.files[0]?.file_id ?? null);
      })
      .catch((err) => {
        if (!isAbort(err)) setLoadError(err instanceof Error ? err.message : "This upload couldn't be opened.");
      });
    return () => ctl.abort();
  }, [batchId]);

  useEffect(() => () => {
    validation.current.ctl?.abort();
    if (validation.current.timer) window.clearTimeout(validation.current.timer);
  }, []);

  /** Apply a change and re-check it on the server (debounced; stale replies are ignored). */
  const update = useCallback(
    (next: ImportConfig) => {
      setConfig(next);
      const v = validation.current;
      if (v.timer) window.clearTimeout(v.timer);
      v.ctl?.abort();
      setChecking(true);
      v.timer = window.setTimeout(async () => {
        const seq = ++v.seq;
        const ctl = new AbortController();
        v.ctl = ctl;
        try {
          const r = await api.validate(batchId, next, ctl.signal);
          if (seq === v.seq) setReport(r);
        } catch (err) {
          if (!isAbort(err) && seq === v.seq) setActionError(err instanceof Error ? err.message : "Couldn't check the files.");
        } finally {
          if (seq === v.seq) setChecking(false);
        }
      }, 300);
    },
    [batchId],
  );

  const fileReports = useMemo(() => new Map(report?.files.map((f) => [f.file_id, f]) ?? []), [report]);

  if (loadError) {
    return (
      <div className="space-y-6">
        <PageTitle>Review your data.</PageTitle>
        <Alert tone="error" action={<Button variant="secondary" size="sm" onClick={() => navigate("/data")}>Upload files</Button>}>
          {loadError}
        </Alert>
      </div>
    );
  }
  if (!batch || !config || !report) return <Spinner label="Opening your files…" />;

  const fileConfig = (id: string) => config.files.find((f) => f.file_id === id) ?? { file_id: id, record_type: null, mapping: {}, date_formats: {}, money_unit: null, status_map: {} };
  const setFile = (id: string, patch: Partial<FileConfig>) => {
    const files = batch.files.map((f) => (f.file_id === id ? { ...fileConfig(id), ...patch } : fileConfig(f.file_id)));
    update({ ...config, files });
  };
  const current = batch.files.find((f) => f.file_id === selected) ?? batch.files[0];
  const currentConfig = fileConfig(current.file_id);
  const currentReport = fileReports.get(current.file_id);
  const typeInfo = types.find((t) => t.key === currentConfig.record_type);
  const pendingGroups = report.review_groups.filter((g) => !g.decision).length;

  async function removeFile(fileId: string) {
    setActionError(null);
    try {
      if (batch!.files.length === 1) {
        await api.cancelUpload(batchId);
        navigate("/data");
        return;
      }
      const next = await api.removeFile(batchId, fileId);
      setBatch(next);
      setConfig(next.config);
      setReport(next.report);
      if (selected === fileId) setSelected(next.files[0]?.file_id ?? null);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "The file couldn't be removed.");
    }
  }

  async function goBack() {
    try {
      await api.cancelUpload(batchId);
    } catch {
      // Unused uploads also expire on their own; going back should never be blocked.
    }
    navigate("/data");
  }

  async function runImport() {
    setActionError(null);
    setPhase("importing");
    try {
      const meta = await api.importUpload(batchId, config!);
      setPhase("done");
      await refresh();
      setNotice(`${meta.name} is ready: ${meta.coverage.label}.`);
      navigate("/overview");
    } catch (err) {
      setPhase("review");
      if (err instanceof ApiError && err.code === "not_ready" && err.details.report) setReport(err.details.report as ValidationReport);
      setActionError(err instanceof Error ? err.message : "The import didn't finish. Your current data is unchanged.");
    }
  }

  return (
    <div className="space-y-7 pb-4">
      <Stepper step={phase === "done" ? 3 : 2} />
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageTitle sub="Confirm how your file columns map to clinic data before importing.">Review your data.</PageTitle>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="group" aria-label="Uploaded files" className="flex flex-wrap gap-2">
          {batch.files.map((f) => {
            const r = fileReports.get(f.file_id);
            const isCurrent = f.file_id === current.file_id;
            return (
              <div key={f.file_id} className={`flex items-center rounded-lg border bg-surface ${isCurrent ? "border-teal ring-1 ring-teal" : "border-line-strong"}`}>
                <button type="button" aria-pressed={isCurrent} onClick={() => setSelected(f.file_id)} className="flex items-center gap-2 rounded-l-lg py-2 pl-3 pr-2 text-sm text-ink">
                  <FileText aria-hidden className="size-4 text-muted" />
                  <span className="max-w-[220px] truncate">{f.filename}</span>
                  {r && r.blocking > 0 ? (
                    <span className="inline-flex items-center gap-0.5 text-xs text-danger">
                      <AlertCircle aria-hidden className="size-3.5" />
                      {r.blocking}
                      <span className="sr-only"> to fix</span>
                    </span>
                  ) : (
                    <CheckCircle2 aria-label="No problems" className="size-3.5 text-teal" />
                  )}
                </button>
                <button type="button" onClick={() => removeFile(f.file_id)} aria-label={`Remove ${f.filename} from this upload`} className="rounded-r-lg px-2 py-2 text-muted hover:text-danger">
                  <X aria-hidden className="size-4" />
                </button>
              </div>
            );
          })}
        </div>
        <div aria-live="polite" className="flex items-center gap-2">
          {checking ? (
            <Spinner label="Checking…" />
          ) : report.ready ? (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-teal-line bg-teal-soft px-3 py-1 text-sm font-medium text-[#06564f]">
              <CheckCircle2 aria-hidden className="size-4" />
              Ready to import
            </span>
          ) : (
            <span className="text-sm text-muted">{report.summary}</span>
          )}
        </div>
      </div>

      <Card className="p-5 sm:p-6">
        <div className="grid gap-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Select
            label="This file contains"
            value={currentConfig.record_type ?? ""}
            onChange={(event) => {
              const type = (event.target.value || null) as RecordType | null;
              const suggestion = type ? batch.suggestions[current.file_id]?.[type] : undefined;
              setFile(current.file_id, { record_type: type, mapping: suggestion?.mapping ?? {}, status_map: suggestion?.status_map ?? {}, date_formats: {} });
            }}
          >
            <option value="">Choose a record type…</option>
            {types.map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}
              </option>
            ))}
          </Select>
          <div className="text-sm">
            <p className="font-medium text-ink">{current.rows.toLocaleString("en-IN")} rows</p>
            <p className="mt-1 text-muted">{typeInfo ? `One row = ${typeInfo.one_row.charAt(0).toLowerCase()}${typeInfo.one_row.slice(1)}` : "Choose what kind of records this file holds."}</p>
          </div>
        </div>

        {typeInfo && currentReport && (
          <>
            <RequiredChecklist info={typeInfo} mapping={currentReport.mapping} />
            <MappingTable
              columns={current.columns}
              preview={current.preview}
              info={typeInfo}
              mapping={currentConfig.mapping}
              onChange={(mapping) => setFile(current.file_id, { mapping })}
            />
            <DateFormats
              report={currentReport}
              config={currentConfig}
              onChoose={(field, format) => {
                // Apply the same choice to other undecided ambiguous date columns that can use it.
                const files = batch.files.map((f) => {
                  const cfg = fileConfig(f.file_id);
                  if (f.file_id === current.file_id) return { ...cfg, date_formats: { ...cfg.date_formats, [field]: format } };
                  const rep = fileReports.get(f.file_id);
                  const extra = Object.fromEntries(
                    (rep?.date_fields ?? []).filter((d) => d.ambiguous && !cfg.date_formats[d.field] && d.candidates.includes(format)).map((d) => [d.field, format]),
                  );
                  return Object.keys(extra).length ? { ...cfg, date_formats: { ...cfg.date_formats, ...extra } } : cfg;
                });
                update({ ...config, files });
              }}
            />
            {currentReport.money_fields.length > 0 && (
              <MoneyUnit report={currentReport} unit={currentConfig.money_unit} onChange={(money_unit) => setFile(current.file_id, { money_unit })} />
            )}
            {currentReport.status_labels.length > 0 && (
              <StatusMapping report={currentReport} statusMap={currentConfig.status_map} onChange={(status_map) => setFile(current.file_id, { status_map })} />
            )}
          </>
        )}

        <PreviewTable filename={current.filename} columns={current.columns} rows={current.preview} />
      </Card>

      <Card className="p-5 sm:p-6">
        <label htmlFor="dataset-name" className="block text-sm font-medium text-ink">
          Dataset name
        </label>
        <p id="dataset-name-hint" className="mt-0.5 text-sm text-muted">
          Shown in the dataset selector, for example the clinic's name.
        </p>
        <input
          id="dataset-name"
          aria-describedby="dataset-name-hint"
          maxLength={80}
          value={config.name}
          onChange={(event) => update({ ...config, name: event.target.value })}
          className="mt-2 h-10 w-full max-w-md rounded-lg border border-line-strong bg-surface px-3 text-sm text-ink"
        />
      </Card>

      {report.review_groups.length > 0 && (
        <section aria-labelledby="review-title" className="space-y-3">
          <div>
            <h2 id="review-title" className="text-lg font-semibold text-navy">
              Needs your review
            </h2>
            <p className="text-sm text-muted">
              These records are unusual. Choose whether to include them as recorded or leave them out. Your choice is shown with the results.
            </p>
          </div>
          {report.review_groups.map((group) => (
            <ReviewGroupCard
              key={group.code}
              group={group}
              decision={config.review_decisions[group.code]}
              onChange={(decision) => update({ ...config, review_decisions: { ...config.review_decisions, [group.code]: decision } })}
            />
          ))}
        </section>
      )}

      <IssuesPanel report={report} batchId={batchId} />

      {actionError && <Alert tone="error">{actionError}</Alert>}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-5">
        <Button variant="ghost" onClick={goBack} disabled={phase !== "review"}>
          <ArrowLeft aria-hidden className="size-4" />
          Back
        </Button>
        <div className="flex flex-wrap items-center gap-3">
          {!report.ready && !checking && (
            <span className="text-sm text-muted">{pendingGroups && !report.blocking ? `Review ${pendingGroups === 1 ? "the group" : "each group"} above to continue.` : "Fix the problems above to continue."}</span>
          )}
          <Button onClick={runImport} disabled={!report.ready || checking || phase !== "review"}>
            {phase === "importing" ? "Importing…" : phase === "done" ? "Imported" : "Import data"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function RequiredChecklist({ info, mapping }: { info: RecordTypeInfo; mapping: Record<string, string> }) {
  const required = info.fields.filter((f) => f.required);
  const items = required.map((f) => ({ label: f.label, ok: Boolean(mapping[f.key]) }));
  if (info.key === "treatments") items.push({ label: "Net fee or listed fee", ok: Boolean(mapping.net_fee || mapping.listed_fee) });
  return (
    <div className="mt-5">
      <h3 className="text-sm font-semibold text-navy">Required fields</h3>
      <ul className="mt-2 flex flex-wrap gap-2">
        {items.map((item) => (
          <li key={item.label} className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${item.ok ? "border-teal-line bg-teal-soft text-[#06564f]" : "border-[#f5c2bd] bg-danger-soft text-[#7a1a12]"}`}>
            {item.ok ? <Check aria-hidden className="size-3.5" /> : <X aria-hidden className="size-3.5" />}
            {item.label}
            <span className="sr-only">{item.ok ? " mapped" : " not mapped yet"}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function MappingTable({ columns, preview, info, mapping, onChange }: { columns: string[]; preview: string[][]; info: RecordTypeInfo; mapping: Record<string, string>; onChange: (m: Record<string, string>) => void }) {
  const fieldFor = (column: string) => Object.entries(mapping).find(([, c]) => c === column)?.[0] ?? "";
  const sample = (i: number) => preview.map((row) => row[i]).find((v) => v && v.trim()) ?? "";
  return (
    <div className="mt-6">
      <h3 className="text-sm font-semibold text-navy">Columns</h3>
      <div className="mt-2 overflow-hidden rounded-lg border border-line">
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="bg-page text-left">
              <th scope="col" className="w-1/2 px-4 py-2.5 font-semibold text-ink">File column</th>
              <th scope="col" className="w-1/2 px-4 py-2.5 font-semibold text-ink">Map to</th>
            </tr>
          </thead>
          <tbody>
            {columns.map((column, i) => {
              const id = `map-${i}`;
              return (
                <tr key={column} className="border-t border-line">
                  <td className="px-4 py-2.5 align-middle">
                    <label htmlFor={id} className="block break-words text-ink">
                      {column}
                    </label>
                    {sample(i) && <span className="block truncate text-xs text-muted">e.g. {sample(i)}</span>}
                  </td>
                  <td className="px-4 py-2">
                    <div className="relative">
                      <select
                        id={id}
                        value={fieldFor(column)}
                        onChange={(event) => {
                          const field = event.target.value;
                          const next = Object.fromEntries(Object.entries(mapping).filter(([f, c]) => c !== column && f !== field));
                          if (field) next[field] = column;
                          onChange(next);
                        }}
                        className="h-9 w-full appearance-none rounded-md border border-line-strong bg-surface pl-3 pr-8 text-sm text-ink"
                      >
                        <option value="">Don't import</option>
                        {info.fields.map((f) => (
                          <option key={f.key} value={f.key}>
                            {f.label}
                            {f.required || (info.key === "treatments" && (f.key === "net_fee" || f.key === "listed_fee")) ? (f.required ? " (required)" : " (this or the other fee)") : " (optional)"}
                          </option>
                        ))}
                      </select>
                      <svg aria-hidden viewBox="0 0 24 24" className="pointer-events-none absolute right-2.5 top-1/2 size-4 -translate-y-1/2 text-ink" fill="none" stroke="currentColor" strokeWidth={2}>
                        <path d="m6 9 6 6 6-6" />
                      </svg>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-muted">Columns set to “Don't import” are not stored.</p>
    </div>
  );
}

function DateFormats({ report, config, onChoose }: { report: FileReport; config: FileConfig; onChoose: (field: string, format: string) => void }) {
  if (report.date_fields.length === 0) return null;
  return (
    <div className="mt-6 space-y-4">
      {report.date_fields.map((d) => {
        const value = config.date_formats[d.field] ?? d.chosen ?? d.detected ?? "";
        const needsChoice = d.ambiguous && !config.date_formats[d.field];
        const options = d.ambiguous ? DATE_FORMATS.filter(([key]) => d.candidates.includes(key)) : DATE_FORMATS;
        return (
          <div key={d.field} className={`rounded-lg border p-4 ${needsChoice ? "border-[#f0d9a8] bg-amber-soft" : "border-line"}`}>
            <Select
              label={`Date format: ${d.label} (column “${d.column}”)`}
              value={value}
              onChange={(event) => onChoose(d.field, event.target.value)}
              className="max-w-md"
            >
              {!value && <option value="">Choose the date format…</option>}
              {options.map(([key, label]) => (
                <option key={key} value={key}>
                  {label}
                </option>
              ))}
            </Select>
            <p className="mt-2 text-sm text-muted">
              {needsChoice
                ? `Dates like “${d.examples[0] ?? ""}” could be day first or month first. Choose the format your clinic uses.`
                : `Examples from the file: ${d.examples.join(", ")}`}
            </p>
          </div>
        );
      })}
    </div>
  );
}

function MoneyUnit({ report, unit, onChange }: { report: FileReport; unit: FileConfig["money_unit"]; onChange: (u: "rupees" | "paise") => void }) {
  const suggestion = report.money_unit_suggestion;
  return (
    <fieldset className={`mt-6 rounded-lg border p-4 ${unit ? "border-line" : "border-[#f0d9a8] bg-amber-soft"}`}>
      <legend className="px-1 text-sm font-semibold text-navy">Amounts in this file are in</legend>
      <div className="mt-1 flex flex-wrap gap-x-6 gap-y-2">
        {(
          [
            ["rupees", "Rupees", "1500.50 means ₹1,500.50"],
            ["paise", "Paise", "150050 means ₹1,500.50"],
          ] as const
        ).map(([value, label, hint]) => (
          <label key={value} className="flex cursor-pointer items-start gap-2 text-sm">
            <input type="radio" name={`unit-${report.file_id}`} value={value} checked={unit === value} onChange={() => onChange(value)} className="mt-0.5 size-4 accent-[#0b7f75]" />
            <span>
              <span className="font-medium text-ink">{label}</span>
              {suggestion === value && <span className="ml-1.5 text-xs text-muted">(suggested from the file)</span>}
              <span className="block text-xs text-muted">{hint}</span>
            </span>
          </label>
        ))}
      </div>
      {unit && (
        <ul className="mt-3 space-y-1 text-sm">
          {report.money_fields.map((f) => (
            <li key={f.field} className="text-ink">
              <span className="text-muted">{f.label}:</span>{" "}
              {f.examples.map((e) => `${e.raw} → ${e.interpreted ?? "can't be read"}`).join(" · ")}
            </li>
          ))}
        </ul>
      )}
    </fieldset>
  );
}

function StatusMapping({ report, statusMap, onChange }: { report: FileReport; statusMap: Record<string, StatusValue>; onChange: (m: Record<string, StatusValue>) => void }) {
  return (
    <div className="mt-6">
      <h3 className="text-sm font-semibold text-navy">Appointment statuses</h3>
      <p className="text-sm text-muted">Match each status in the file to completed, cancelled or no-show.</p>
      <ul className="mt-2 divide-y divide-line rounded-lg border border-line">
        {report.status_labels.map((s) => {
          const id = `status-${s.key}`;
          const chosen = statusMap[s.key] ?? "";
          return (
            <li key={s.key} className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
              <label htmlFor={id} className="text-sm text-ink">
                “{s.label}” <span className="text-muted">({s.count.toLocaleString("en-IN")} {s.count === 1 ? "row" : "rows"})</span>
              </label>
              <select
                id={id}
                value={chosen}
                onChange={(event) => {
                  const next = { ...statusMap };
                  if (event.target.value) next[s.key] = event.target.value as StatusValue;
                  else delete next[s.key];
                  onChange(next);
                }}
                className={`h-9 w-44 appearance-none rounded-md border bg-surface bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%231b2f4b%22 stroke-width=%222%22><path d=%22m6 9 6 6 6-6%22/></svg>')] bg-[length:16px] bg-[right_10px_center] bg-no-repeat pl-3 pr-8 text-sm text-ink ${chosen ? "border-line-strong" : "border-danger"}`}
              >
                <option value="">Choose…</option>
                {STATUS_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function PreviewTable({ filename, columns, rows }: { filename: string; columns: string[]; rows: string[][] }) {
  if (rows.length === 0) return null;
  return (
    <div className="mt-6">
      <h3 className="text-sm font-semibold text-navy">Preview</h3>
      <div className="mt-2 overflow-x-auto rounded-lg border border-line" tabIndex={0} role="region" aria-label={`First rows of ${filename}`}>
        <table className="w-full min-w-max border-collapse text-sm">
          <caption className="sr-only">First {rows.length} rows of {filename}</caption>
          <thead>
            <tr className="bg-page">
              {columns.map((c) => (
                <th key={c} scope="col" className="whitespace-nowrap px-3 py-2 text-left font-semibold text-ink">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="border-t border-line">
                {row.map((cell, j) => (
                  <td key={j} className="max-w-[240px] truncate whitespace-nowrap px-3 py-2 text-ink">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ReviewGroupCard({ group, decision, onChange }: { group: ReviewGroup; decision: "include" | "exclude" | undefined; onChange: (d: "include" | "exclude") => void }) {
  return (
    <Card className={`p-5 ${decision ? "" : "border-[#f0d9a8]"}`}>
      <fieldset>
        <legend className="flex flex-wrap items-center gap-2 text-base font-semibold text-navy">
          {group.title}
          <Badge>{group.count.toLocaleString("en-IN")} {group.count === 1 ? "record" : "records"}</Badge>
        </legend>
        <p className="mt-1 text-sm text-ink">{group.description}</p>
        <ul className="mt-2 space-y-0.5 text-sm text-muted">
          {group.examples.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {(
            [
              ["include", "Include as recorded", group.include_effect],
              ["exclude", "Leave out", group.exclude_effect],
            ] as const
          ).map(([value, label, effect]) => (
            <label key={value} className={`flex cursor-pointer items-start gap-2 rounded-lg border p-3 text-sm ${decision === value ? "border-teal bg-teal-soft" : "border-line"}`}>
              <input type="radio" name={`review-${group.code}`} value={value} checked={decision === value} onChange={() => onChange(value)} className="mt-0.5 size-4 accent-[#0b7f75]" />
              <span>
                <span className="block font-medium text-ink">{label}</span>
                <span className="block text-muted">{effect}</span>
              </span>
            </label>
          ))}
        </div>
      </fieldset>
    </Card>
  );
}

function IssuesPanel({ report, batchId }: { report: ValidationReport; batchId: string }) {
  const visible = report.issues.filter((i) => i.severity !== "review");
  return (
    <section aria-labelledby="issues-title" className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="issues-title" className="text-lg font-semibold text-navy">
            Checks
          </h2>
          <p className="text-sm text-muted">
            {report.blocking} to fix · {report.needs_review} to review · {report.warnings} to check. Row numbers match your spreadsheet (the header is row 1).
          </p>
        </div>
        <a href={`/api/uploads/${batchId}/issues.csv`} download className="inline-flex items-center gap-1.5 text-sm font-medium text-teal hover:underline">
          <Download aria-hidden className="size-4" />
          Download issues report
        </a>
      </div>
      {visible.length === 0 ? (
        <Alert tone="success">No problems found.</Alert>
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {visible.map((issue, i) => (
            <li key={i} className="flex gap-3 px-4 py-3">
              <span className="mt-0.5">{SEVERITY[issue.severity].icon}</span>
              <div className="min-w-0 text-sm">
                <p className="text-ink">
                  <span className="sr-only">{SEVERITY[issue.severity].label}: </span>
                  {issue.file && <span className="font-medium">{issue.file}: </span>}
                  {issue.message}
                </p>
                {issue.suggestion && <p className="text-muted">{issue.suggestion}</p>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
