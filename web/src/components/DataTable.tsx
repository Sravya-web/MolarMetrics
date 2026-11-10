import type { ColumnOut, TableOut } from "../api/types";

const NUMERIC = new Set(["inr", "count", "percent"]);

/** The table twin of a chart: exact, formatted values (from the server). */
export function DataTable({ table, caption, maxRows }: { table: TableOut; caption: string; maxRows?: number }) {
  const rows = maxRows ? table.display.slice(0, maxRows) : table.display;
  const header = (c: ColumnOut) => (c.unit && !["text", "month"].includes(c.unit) && !c.label.toLowerCase().includes(c.unit.toLowerCase())
    ? `${c.label} (${c.unit === "percent" ? "%" : c.unit === "INR" ? "₹" : c.unit})`
    : c.label);
  return (
    <div className="overflow-x-auto rounded-lg border border-line" tabIndex={0} role="region" aria-label={caption}>
      <table className="w-full min-w-max border-collapse text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="bg-page">
            {table.columns.map((c) => (
              <th key={c.key} scope="col" className={`whitespace-nowrap px-3 py-2 font-semibold text-ink ${NUMERIC.has(c.kind) ? "text-right" : "text-left"}`}>
                {header(c)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-line">
              {table.columns.map((c, j) => {
                const Cell = j === 0 ? "th" : "td";
                return (
                  <Cell key={c.key} scope={j === 0 ? "row" : undefined} className={`whitespace-nowrap px-3 py-2 ${j === 0 ? "font-normal text-ink" : "text-ink"} ${NUMERIC.has(c.kind) ? "tabular text-right" : "text-left"}`}>
                    {row[c.key]}
                  </Cell>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
