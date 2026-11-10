import type { ReactNode } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from "recharts";
import type { AnalysisPayload, AppointmentRow, FinanceRow, ValueKind } from "../api/types";
import { formatCount, formatInrAxis, niceTicks } from "../lib/format";

// Data colours (validated: see index.css). Identity never rests on colour
// alone: every multi-series chart has a legend, and every chart a table view.
export const SERIES_COLORS: Record<string, string> = {
  billed: "#008a7a",
  billed_paise: "#008a7a",
  collected: "#3cc4ab",
  collected_paise: "#3cc4ab",
  completed: "#008a7a",
  cancelled: "#6250d6",
  no_show: "#eb6834",
};
const SINGLE = "#008a7a";
const GRID = "#e6eaee";
const AXIS = "#c5ccd3";
const TICK = { fontSize: 12, fill: "#536373" };

interface TooltipRow {
  key: string;
  label: string;
  value: string;
  color: string;
  mark: "line" | "rect";
}

function TooltipBox({ title, rows, footer }: { title: string; rows: TooltipRow[]; footer?: string }) {
  return (
    <div className="min-w-[180px] rounded-lg border border-line bg-surface px-3 py-2.5 text-sm shadow-md">
      <div className="mb-1.5 text-xs font-medium text-muted">{title}</div>
      <ul className="space-y-1">
        {rows.map((r) => (
          <li key={r.key} className="flex items-center gap-2">
            <span
              aria-hidden
              className={r.mark === "line" ? "h-0.5 w-3.5 rounded-full" : "size-2.5 rounded-[3px]"}
              style={{ background: r.color }}
            />
            <span className="tabular font-semibold text-navy">{r.value}</span>
            <span className="text-muted">{r.label}</span>
          </li>
        ))}
      </ul>
      {footer && <div className="mt-1.5 border-t border-line pt-1.5 text-xs text-muted">{footer}</div>}
    </div>
  );
}

export function Legend({ items }: { items: { key: string; label: string; color: string; mark: "line" | "rect" }[] }) {
  if (items.length < 2) return null;
  return (
    <ul className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm text-ink" aria-label="Legend">
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-2">
          <span
            aria-hidden
            className={item.mark === "line" ? "h-[3px] w-5 rounded-full" : "size-3 rounded-[3px]"}
            style={{ background: item.color }}
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

function Figure({ label, summary, children, height }: { label: string; summary: string; children: ReactNode; height: number }) {
  return (
    <figure className="m-0" aria-label={label}>
      <div style={{ height }} className="w-full">
        {children}
      </div>
      <figcaption className="sr-only">{summary}</figcaption>
    </figure>
  );
}

// --- overview: billed revenue and collections -------------------------------------------
export type MoneyMode = "monthly" | "cumulative";

export function FinanceChart({ rows, hasCollections, mode }: { rows: FinanceRow[]; hasCollections: boolean; mode: MoneyMode }) {
  const cumulative = mode === "cumulative";
  const data = rows.map((r) => ({
    label: r.month_label,
    billed: cumulative ? r.cumulative_billed_paise : r.billed_paise,
    collected: hasCollections ? (cumulative ? r.cumulative_collected_paise : r.collected_paise) : null,
    billedText: cumulative ? r.cumulative_billed : r.billed,
    collectedText: cumulative ? r.cumulative_collected : r.collected,
  }));
  const max = Math.max(1, ...data.map((d) => Math.max(d.billed, d.collected ?? 0)));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1];
  const last = data[data.length - 1];
  // Direct end labels only when they cannot collide (else the legend carries identity).
  const endLabels = hasCollections && last && last.collected !== null && Math.abs(last.billed - last.collected) / top > 0.09;
  const single = data.length === 1;
  const series = [
    { key: "billed", label: cumulative ? "Billed revenue (cumulative)" : "Billed revenue", color: SERIES_COLORS.billed },
    ...(hasCollections
      ? [{ key: "collected", label: cumulative ? "Collections (cumulative)" : "Collections", color: SERIES_COLORS.collected }]
      : []),
  ];
  const endLabel = (name: string) =>
    function EndLabel(props: { x?: number | string; y?: number | string; index?: number }) {
      if (!endLabels || props.index !== data.length - 1) return null;
      return (
        <text x={Number(props.x) + 8} y={Number(props.y)} dy={4} fontSize={12} fill="#1b2f4b">
          {name}
        </text>
      );
    };
  const summary = `${cumulative ? "Cumulative" : "Monthly"} billed revenue${hasCollections ? " and collections" : ""} from ${data[0]?.label} to ${last?.label}. The table view lists every value.`;

  return (
    <div className="space-y-3">
      <Legend items={series.map((s) => ({ ...s, mark: "line" as const }))} />
      <Figure label={summary} summary={summary} height={290}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: endLabels ? 76 : 16, bottom: 4, left: 4 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="label" tick={TICK} tickLine={false} axisLine={{ stroke: AXIS }} interval="preserveStartEnd" minTickGap={16} />
            <YAxis
              ticks={ticks}
              domain={[0, top]}
              tickFormatter={(v: number) => formatInrAxis(v)}
              tick={TICK}
              tickLine={false}
              axisLine={false}
              width={62}
            />
            <Tooltip
              cursor={{ stroke: AXIS, strokeWidth: 1 }}
              isAnimationActive={false}
              content={(props: TooltipContentProps) => {
                if (!props.active || props.activeIndex === undefined) return null;
                const row = data[Number(props.activeIndex)];
                if (!row) return null;
                return (
                  <TooltipBox
                    title={`${row.label}${cumulative ? " · cumulative" : ""}`}
                    rows={[
                      { key: "b", label: "Billed", value: row.billedText, color: SERIES_COLORS.billed, mark: "line" },
                      ...(hasCollections && row.collectedText
                        ? [{ key: "c", label: "Collected", value: row.collectedText, color: SERIES_COLORS.collected, mark: "line" as const }]
                        : []),
                    ]}
                  />
                );
              }}
            />
            <Line
              type="linear"
              dataKey="billed"
              name="Billed revenue"
              stroke={SERIES_COLORS.billed}
              strokeWidth={2}
              dot={single ? { r: 4, strokeWidth: 2, stroke: "#fff", fill: SERIES_COLORS.billed } : false}
              activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }}
              isAnimationActive={false}
            >
              <LabelList dataKey="billed" content={endLabel("Billed")} />
            </Line>
            {hasCollections && (
              <Line
                type="linear"
                dataKey="collected"
                name="Collections"
                stroke={SERIES_COLORS.collected}
                strokeWidth={2}
                dot={single ? { r: 4, strokeWidth: 2, stroke: "#fff", fill: SERIES_COLORS.collected } : false}
                activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }}
                isAnimationActive={false}
              >
                <LabelList dataKey="collected" content={endLabel("Collected")} />
              </Line>
            )}
          </LineChart>
        </ResponsiveContainer>
      </Figure>
    </div>
  );
}

// --- overview: appointments by status (appointment-only data) ------------------------------
const STATUS_SERIES = [
  { key: "completed", label: "Completed", color: SERIES_COLORS.completed },
  { key: "cancelled", label: "Cancelled", color: SERIES_COLORS.cancelled },
  { key: "no_show", label: "No-show", color: SERIES_COLORS.no_show },
] as const;

export function AppointmentsChart({ rows }: { rows: AppointmentRow[] }) {
  const data = rows.map((r) => ({ ...r, label: r.month_label }));
  const max = Math.max(1, ...rows.map((r) => r.scheduled));
  const ticks = niceTicks(max).map((t) => Math.round(t));
  const summary = `Appointments by status each month, from ${data[0]?.label} to ${data[data.length - 1]?.label}. The table view lists every value.`;
  return (
    <div className="space-y-3">
      <Legend items={STATUS_SERIES.map((s) => ({ ...s, mark: "rect" as const }))} />
      <Figure label={summary} summary={summary} height={280}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey="label" tick={TICK} tickLine={false} axisLine={{ stroke: AXIS }} interval="preserveStartEnd" minTickGap={12} />
            <YAxis ticks={ticks} domain={[0, ticks[ticks.length - 1]]} allowDecimals={false} tick={TICK} tickLine={false} axisLine={false} width={40} />
            <Tooltip
              cursor={{ fill: "#eef2f4" }}
              isAnimationActive={false}
              content={(props: TooltipContentProps) => {
                if (!props.active || props.activeIndex === undefined) return null;
                const row = data[Number(props.activeIndex)];
                if (!row) return null;
                return (
                  <TooltipBox
                    title={row.label}
                    rows={STATUS_SERIES.map((s) => ({ key: s.key, label: s.label, value: formatCount(row[s.key]), color: s.color, mark: "rect" }))}
                    footer={`${formatCount(row.scheduled)} scheduled · no-show rate ${row.no_show_rate_pct === null ? "n/a" : `${row.no_show_rate_pct.toFixed(1)}%`}`}
                  />
                );
              }}
            />
            {STATUS_SERIES.map((s, i) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.label}
                stackId="status"
                fill={s.color}
                stroke="#ffffff"
                strokeWidth={2}
                maxBarSize={24}
                radius={i === STATUS_SERIES.length - 1 ? [4, 4, 0, 0] : 0}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </Figure>
    </div>
  );
}

// --- Ask: a chart drawn from a result's structured rows ----------------------------------------
function axisFormatter(kind: ValueKind) {
  if (kind === "inr") return (v: number) => formatInrAxis(v);
  if (kind === "percent") return (v: number) => `${v}%`;
  return (v: number) => formatCount(v);
}

export function ResultChart({ result }: { result: AnalysisPayload }) {
  const chart = result.chart;
  const table = result.table;
  if (!chart || !table || table.rows.length === 0) return null;
  const kind = chart.series[0]?.kind ?? "count";
  const data: Record<string, string | number | null>[] = table.rows.map((row, i) => ({ ...row, __i: i }));
  const display = table.display;
  const colorFor = (key: string, count: number) => (count === 1 ? SINGLE : SERIES_COLORS[key] ?? SINGLE);
  const colors = chart.series.map((s) => colorFor(s.key, chart.series.length));
  const values = data.flatMap((row) => chart.series.map((s) => Number(row[s.key] ?? 0)));
  const stacked = chart.type === "stacked_bar";
  const max = Math.max(1, ...(stacked ? data.map((row) => chart.series.reduce((sum, s) => sum + Number(row[s.key] ?? 0), 0)) : values));
  const ticks = kind === "percent" ? niceTicks(Math.min(100, Math.ceil(max))) : niceTicks(max);
  const domain: [number, number] = [0, ticks[ticks.length - 1]];
  const fmt = axisFormatter(kind);
  const xKey = chart.x;
  const labelOf = (row: Record<string, unknown>) => String(row[xKey] ?? "");
  const legend = chart.series.map((s, i) => ({ key: s.key, label: s.label, color: colors[i], mark: (chart.type === "line" ? "line" : "rect") as "line" | "rect" }));
  const summary = `${chart.title}, ${result.period_label}. The supporting data lists every value.`;

  const tooltip = (props: TooltipContentProps) => {
    if (!props.active || props.activeIndex === undefined) return null;
    const i = Number(props.activeIndex);
    const row = data[i];
    if (!row) return null;
    return (
      <TooltipBox
        title={labelOf(row)}
        rows={chart.series.map((s, j) => ({
          key: s.key,
          label: s.label,
          value: display[i]?.[s.key] ?? String(row[s.key] ?? ""),
          color: colors[j],
          mark: chart.type === "line" ? "line" : "rect",
        }))}
      />
    );
  };

  if (chart.orientation === "h") {
    const height = Math.max(150, data.length * 34 + 36);
    return (
      <div className="space-y-3">
        <Legend items={legend} />
        <Figure label={summary} summary={summary} height={height}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 64, bottom: 4, left: 4 }}>
              <CartesianGrid stroke={GRID} horizontal={false} />
              <XAxis type="number" ticks={ticks} domain={domain} tickFormatter={fmt} tick={TICK} tickLine={false} axisLine={false} />
              <YAxis
                type="category"
                dataKey={xKey}
                width={150}
                tick={{ ...TICK, fill: "#1b2f4b" }}
                tickLine={false}
                axisLine={{ stroke: AXIS }}
                tickFormatter={(v: string) => (v.length > 22 ? `${v.slice(0, 21)}…` : v)}
              />
              <Tooltip cursor={{ fill: "#eef2f4" }} isAnimationActive={false} content={tooltip} />
              {chart.series.map((s, j) => (
                <Bar key={s.key} dataKey={s.key} name={s.label} fill={colors[j]} maxBarSize={22} radius={[0, 4, 4, 0]} isAnimationActive={false}>
                  {chart.series.length === 1 && (
                    <LabelList dataKey={s.key} position="right" formatter={(v: unknown) => fmt(Number(v))} style={{ fontSize: 12, fill: "#536373" }} />
                  )}
                </Bar>
              ))}
            </BarChart>
          </ResponsiveContainer>
        </Figure>
      </div>
    );
  }

  if (chart.type === "line") {
    return (
      <div className="space-y-3">
        <Legend items={legend} />
        <Figure label={summary} summary={summary} height={260}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey={xKey} tick={TICK} tickLine={false} axisLine={{ stroke: AXIS }} interval="preserveStartEnd" minTickGap={12} />
              <YAxis ticks={ticks} domain={domain} tickFormatter={fmt} tick={TICK} tickLine={false} axisLine={false} width={kind === "inr" ? 62 : 44} />
              <Tooltip cursor={{ stroke: AXIS, strokeWidth: 1 }} isAnimationActive={false} content={tooltip} />
              {chart.series.map((s, j) => (
                <Line
                  key={s.key}
                  type="linear"
                  dataKey={s.key}
                  name={s.label}
                  stroke={colors[j]}
                  strokeWidth={2}
                  connectNulls={false}
                  dot={data.length === 1 ? { r: 4, strokeWidth: 2, stroke: "#fff", fill: colors[j] } : false}
                  activeDot={{ r: 5, strokeWidth: 2, stroke: "#fff" }}
                  isAnimationActive={false}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </Figure>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Legend items={legend} />
      <Figure label={summary} summary={summary} height={270}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 4, left: 0 }} barGap={2}>
            <CartesianGrid stroke={GRID} vertical={false} />
            <XAxis dataKey={xKey} tick={TICK} tickLine={false} axisLine={{ stroke: AXIS }} interval="preserveStartEnd" minTickGap={8} />
            <YAxis ticks={ticks} domain={domain} tickFormatter={fmt} tick={TICK} tickLine={false} axisLine={false} width={kind === "inr" ? 62 : 44} />
            <Tooltip cursor={{ fill: "#eef2f4" }} isAnimationActive={false} content={tooltip} />
            {chart.series.map((s, j) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.label}
                fill={colors[j]}
                stackId={stacked ? "stack" : undefined}
                stroke={stacked ? "#ffffff" : undefined}
                strokeWidth={stacked ? 2 : 0}
                maxBarSize={24}
                radius={!stacked || j === chart.series.length - 1 ? [4, 4, 0, 0] : 0}
                isAnimationActive={false}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </Figure>
    </div>
  );
}
