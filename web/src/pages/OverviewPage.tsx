import { CalendarDays, Download, Info, Upload } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, isAbort } from "../api/client";
import type { DatasetMeta, KpiOut, OverviewPayload, TableOut } from "../api/types";
import { AppointmentsChart, FinanceChart, type MoneyMode } from "../components/charts";
import { DataTable } from "../components/DataTable";
import { DatasetSelect } from "../components/DatasetSelect";
import { Alert, Button, Card, Disclosure, PageTitle, Select, Skeleton } from "../components/ui";
import { formatCount, formatDate, formatPercent } from "../lib/format";
import { useRouter } from "../lib/router";
import { useSession } from "../state/session";
import { NoDataset } from "./NoDataset";

export function OverviewPage() {
  const { active, notice, setNotice } = useSession();
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 8000);
    return () => window.clearTimeout(timer);
  }, [notice, setNotice]);
  if (!active) {
    return (
      <div className="space-y-6">
        <PageTitle>Clinic overview.</PageTitle>
        <NoDataset />
      </div>
    );
  }
  // Keyed by dataset: switching resets the period, the chart mode and every result.
  return <OverviewContent key={active.id} dataset={active} notice={notice} />;
}

type Period = { key: string; start?: string; end?: string };

function OverviewContent({ dataset, notice }: { dataset: DatasetMeta; notice: string | null }) {
  const { navigate } = useRouter();
  const [period, setPeriod] = useState<Period>({ key: "all" });
  const [custom, setCustom] = useState({ start: dataset.coverage.start, end: dataset.coverage.end });
  const [data, setData] = useState<OverviewPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [mode, setMode] = useState<MoneyMode>("monthly");

  useEffect(() => {
    const ctl = new AbortController();
    setLoading(true);
    api
      .overview(dataset.id, { start: period.start, end: period.end }, ctl.signal)
      .then((payload) => {
        if (payload.dataset.id !== dataset.id) return; // a late reply for another dataset
        setData(payload);
        setError(null);
      })
      .catch((err) => {
        if (!isAbort(err)) setError(err instanceof Error ? err.message : "The overview couldn't be loaded.");
      })
      .finally(() => {
        if (!ctl.signal.aborted) setLoading(false);
      });
    return () => ctl.abort();
  }, [dataset.id, period, reload]);

  const presets = data?.presets ?? [{ key: "all", label: "All data", start: dataset.coverage.start, end: dataset.coverage.end }];

  return (
    <div className="space-y-6">
      <PageTitle>Clinic overview.</PageTitle>
      {notice && <Alert tone="success">{notice}</Alert>}

      <div className="flex flex-wrap items-end gap-3">
        <DatasetSelect />
        <Select
          label="Reporting period"
          hideLabel
          icon={<CalendarDays aria-hidden className="size-4" strokeWidth={1.8} />}
          value={period.key}
          onChange={(event) => {
            const key = event.target.value;
            if (key === "custom") {
              setPeriod({ key: "custom", start: custom.start, end: custom.end });
              return;
            }
            const preset = presets.find((p) => p.key === key);
            setPeriod(key === "all" || !preset ? { key: "all" } : { key, start: preset.start, end: preset.end });
          }}
          className="w-[190px]"
        >
          {presets.map((p) => (
            <option key={p.key} value={p.key}>
              {p.label}
            </option>
          ))}
          <option value="custom">Custom range…</option>
        </Select>
        <div className="ml-auto">
          <Button onClick={() => navigate("/data")}>
            <Upload aria-hidden className="size-4" />
            Upload data
          </Button>
        </div>
      </div>

      {period.key === "custom" && (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            setPeriod({ key: "custom", start: custom.start, end: custom.end });
          }}
        >
          <label className="text-sm text-ink">
            <span className="mb-1 block font-medium">From</span>
            <input type="date" required min={dataset.coverage.start} max={dataset.coverage.end} value={custom.start} onChange={(e) => setCustom({ ...custom, start: e.target.value })} className="h-10 rounded-lg border border-line-strong bg-surface px-3 text-sm" />
          </label>
          <label className="text-sm text-ink">
            <span className="mb-1 block font-medium">To</span>
            <input type="date" required min={dataset.coverage.start} max={dataset.coverage.end} value={custom.end} onChange={(e) => setCustom({ ...custom, end: e.target.value })} className="h-10 rounded-lg border border-line-strong bg-surface px-3 text-sm" />
          </label>
          <Button type="submit" variant="secondary">
            Apply
          </Button>
        </form>
      )}

      {error && (
        <Alert tone="error" action={<Button variant="secondary" size="sm" onClick={() => setReload((n) => n + 1)}>Try again</Button>}>
          {error}
        </Alert>
      )}

      {!data && loading && <OverviewSkeleton />}

      {data && (
        <div aria-busy={loading} className={`space-y-6 transition-opacity ${loading ? "opacity-60" : ""}`}>
          <p className="text-sm text-muted">
            Showing <span className="font-medium text-ink">{data.period.label}</span>
          </p>
          {data.warnings.map((w) => (
            <Alert key={w} tone="warning">{w}</Alert>
          ))}
          <KpiGrid kpis={data.kpis} />
          {data.unavailable.length > 0 && (
            <Alert tone="info">
              {data.unavailable.map((u) => (
                <p key={u}>{u}</p>
              ))}
            </Alert>
          )}
          {data.finance ? <FinanceCard data={data} mode={mode} setMode={setMode} /> : data.appointments && data.appointments.rows.length > 0 && <AppointmentsCard data={data} />}
          {data.top_procedures && data.top_procedures.rows.length > 0 && <TopProcedures data={data} />}
          <Definitions kpis={data.kpis} />
          {data.notes.length > 0 && (
            <div className="space-y-1 text-sm text-muted">
              {data.notes.map((n) => (
                <p key={n} className="flex items-start gap-2">
                  <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
                  {n}
                </p>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function OverviewSkeleton() {
  return (
    <div className="space-y-6" aria-hidden>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-[106px]" />
        ))}
      </div>
      <Skeleton className="h-[360px]" />
    </div>
  );
}

function KpiGrid({ kpis }: { kpis: KpiOut[] }) {
  const shown = kpis.filter((k) => k.status === "available");
  const cols = shown.length >= 5 ? "lg:grid-cols-5" : shown.length === 4 ? "lg:grid-cols-4" : "lg:grid-cols-3";
  return (
    <ul className={`grid grid-cols-1 gap-3 min-[360px]:grid-cols-2 sm:gap-4 ${cols}`}>
      {shown.map((k) => (
        <li key={k.key}>
          <Card as="article" className="h-full px-4 py-4 sm:px-5">
            <h2 className="text-sm text-ink">{k.label}</h2>
            <p className="mt-1.5 text-2xl font-bold leading-tight tracking-[-0.01em] text-navy sm:text-[1.75rem]">{k.display}</p>
            {k.exact && <p className="mt-1 text-xs text-muted">{k.exact}</p>}
            {k.detail && <p className="mt-0.5 text-xs text-muted">{k.detail}</p>}
          </Card>
        </li>
      ))}
    </ul>
  );
}

function FinanceCard({ data, mode, setMode }: { data: OverviewPayload; mode: MoneyMode; setMode: (m: MoneyMode) => void }) {
  const finance = data.finance!;
  const cumulative = mode === "cumulative";
  const table: TableOut = useMemo(
    () => ({
      columns: [
        { key: "month", label: "Month", kind: "month", unit: "month", aggregation: "group" },
        { key: "billed", label: cumulative ? "Billed revenue, cumulative" : "Billed revenue", kind: "inr", unit: "INR", aggregation: "sum" },
        ...(finance.has_collections
          ? [{ key: "collected", label: cumulative ? "Collections, cumulative" : "Collections", kind: "inr" as const, unit: "INR", aggregation: "sum" }]
          : []),
      ],
      rows: [],
      display: finance.rows.map((r) => ({
        month: r.month_label,
        billed: cumulative ? r.cumulative_billed : r.billed,
        collected: (cumulative ? r.cumulative_collected : r.collected) ?? "",
      })),
    }),
    [finance, cumulative, finance.has_collections],
  );
  const title = finance.has_collections ? "Billed revenue and collections" : "Billed revenue";
  return (
    <Card className="p-5 sm:p-6" aria-labelledby="finance-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="finance-title" className="text-lg font-semibold text-navy">
            {title}
          </h2>
          <p className="mt-0.5 text-sm text-muted">
            {cumulative
              ? `Running totals from ${formatDate(data.period.start)}.`
              : "Each point is one month's total."}{" "}
            Billed revenue counts fees by treatment date{finance.has_collections ? "; collections count payments by payment date." : "."}
          </p>
        </div>
        <div role="group" aria-label="Show" className="inline-flex rounded-lg border border-line-strong p-0.5">
          {(["monthly", "cumulative"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => setMode(m)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium ${mode === m ? "bg-teal-soft text-[#06564f]" : "text-ink hover:bg-page"}`}
            >
              {m === "monthly" ? "Monthly" : "Cumulative"}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-4">
        <FinanceChart rows={finance.rows} hasCollections={finance.has_collections} mode={mode} />
      </div>
      <div className="mt-4 flex flex-wrap items-start justify-between gap-3 border-t border-line pt-3">
        <Disclosure label="View data">
          <DataTable table={table} caption={`${title}, ${cumulative ? "cumulative" : "by month"}`} />
        </Disclosure>
        <a href={finance.export_url} download className="inline-flex items-center gap-1.5 py-1 text-sm font-medium text-teal hover:underline">
          <Download aria-hidden className="size-4" />
          Download CSV
        </a>
      </div>
    </Card>
  );
}

function AppointmentsCard({ data }: { data: OverviewPayload }) {
  const appts = data.appointments!;
  const table: TableOut = {
    columns: [
      { key: "month", label: "Month", kind: "month", unit: "month", aggregation: "group" },
      { key: "scheduled", label: "Scheduled", kind: "count", unit: "appointments", aggregation: "count" },
      { key: "completed", label: "Completed", kind: "count", unit: "appointments", aggregation: "count" },
      { key: "cancelled", label: "Cancelled", kind: "count", unit: "appointments", aggregation: "count" },
      { key: "no_show", label: "No-shows", kind: "count", unit: "appointments", aggregation: "count" },
      { key: "rate", label: "No-show rate", kind: "percent", unit: "percent", aggregation: "ratio" },
    ],
    rows: [],
    display: appts.rows.map((r) => ({
      month: r.month_label,
      scheduled: formatCount(r.scheduled),
      completed: formatCount(r.completed),
      cancelled: formatCount(r.cancelled),
      no_show: formatCount(r.no_show),
      rate: formatPercent(r.no_show_rate_pct),
    })),
  };
  return (
    <Card className="p-5 sm:p-6" aria-labelledby="appointments-title">
      <h2 id="appointments-title" className="text-lg font-semibold text-navy">
        Appointments by status
      </h2>
      <p className="mt-0.5 text-sm text-muted">Each bar is one month's appointments, by appointment date.</p>
      <div className="mt-4">
        <AppointmentsChart rows={appts.rows} />
      </div>
      <div className="mt-4 flex flex-wrap items-start justify-between gap-3 border-t border-line pt-3">
        <Disclosure label="View data">
          <DataTable table={table} caption="Appointments by status and month" />
        </Disclosure>
        <a href={appts.export_url} download className="inline-flex items-center gap-1.5 py-1 text-sm font-medium text-teal hover:underline">
          <Download aria-hidden className="size-4" />
          Download CSV
        </a>
      </div>
    </Card>
  );
}

function TopProcedures({ data }: { data: OverviewPayload }) {
  const procs = data.top_procedures!;
  return (
    <Card className="p-5 sm:p-6" aria-labelledby="procedures-title">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="procedures-title" className="text-lg font-semibold text-navy">
          Top procedures
        </h2>
        <span className="text-sm text-muted">By billed revenue · {procs.total_procedures} procedures in this period</span>
      </div>
      <table className="mt-3 w-full border-collapse text-sm">
        <caption className="sr-only">Top procedures by billed revenue</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Procedure</th>
            <th scope="col">Treatment records</th>
            <th scope="col">Billed revenue</th>
          </tr>
        </thead>
        <tbody>
          {procs.rows.map((p) => (
            <tr key={p.procedure} className="border-t border-line first:border-t-0">
              <th scope="row" className="py-2.5 pr-3 text-left font-normal text-ink">
                {p.procedure}
              </th>
              <td className="tabular whitespace-nowrap py-2.5 pr-4 text-right text-muted">
                {formatCount(p.treatment_count)} {p.treatment_count === 1 ? "record" : "records"}
                {p.share_pct !== null ? ` · ${p.share_pct.toFixed(1)}%` : ""}
              </td>
              <td className="tabular whitespace-nowrap py-2.5 text-right font-medium text-ink">{p.billed}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 border-t border-line pt-3 text-right">
        <a href={procs.export_url} download className="inline-flex items-center gap-1.5 text-sm font-medium text-teal hover:underline">
          <Download aria-hidden className="size-4" />
          Download CSV
        </a>
      </div>
    </Card>
  );
}

function Definitions({ kpis }: { kpis: KpiOut[] }) {
  const shown = kpis.filter((k) => k.status === "available");
  return (
    <Disclosure label="How these figures are calculated">
      <dl className="space-y-2 text-sm">
        {shown.map((k) => (
          <div key={k.key}>
            <dt className="font-medium text-ink">{k.label}</dt>
            <dd className="text-muted">{k.definition}</dd>
          </div>
        ))}
        <div>
          <dt className="font-medium text-ink">What these figures are not</dt>
          <dd className="text-muted">These are operational figures. Revenue and appointment counts do not measure clinical quality or treatment outcomes.</dd>
        </div>
      </dl>
    </Disclosure>
  );
}
