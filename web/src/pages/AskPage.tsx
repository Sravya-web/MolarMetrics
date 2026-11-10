import { ChevronRight, Download, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ApiError, api, isAbort } from "../api/client";
import type { AnalysisPayload, AskResponse, DatasetMeta } from "../api/types";
import { ResultChart } from "../components/charts";
import { DataTable } from "../components/DataTable";
import { DatasetSelect } from "../components/DatasetSelect";
import { Alert, Button, Card, Disclosure, PageTitle, Spinner } from "../components/ui";
import { Link } from "../lib/router";
import { useSession } from "../state/session";
import { NoDataset } from "./NoDataset";

const UNAVAILABLE = "Questions are temporarily unavailable. You can still explore your overview.";

interface Turn {
  id: string;
  question: string;
  status: "pending" | "done" | "error";
  response?: AskResponse;
  error?: string;
}

export function AskPage() {
  const { active } = useSession();
  if (!active) {
    return (
      <div className="space-y-6">
        <PageTitle>Ask MolarMetrics.</PageTitle>
        <NoDataset />
      </div>
    );
  }
  // Keyed by dataset: switching clears the conversation, results and downloads.
  return <AskContent key={active.id} dataset={active} />;
}

function AskContent({ dataset }: { dataset: DatasetMeta }) {
  const { state, refresh } = useSession();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [checking, setChecking] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const datasetRef = useRef(dataset.id);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const pending = turns.some((t) => t.status === "pending");
  const available = state?.questions_available ?? true;

  useEffect(() => {
    datasetRef.current = dataset.id;
    const ctl = new AbortController();
    api.suggestions(dataset.id, ctl.signal).then((s) => setSuggestions(s.questions)).catch(() => setSuggestions([]));
    return () => {
      ctl.abort();
      controller.current?.abort(); // leaving or switching: drop any in-flight answer
    };
  }, [dataset.id]);

  useEffect(() => {
    if (turns.length) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  async function send(question: string) {
    const text = question.trim();
    if (!text || pending) return;
    const id = crypto.randomUUID();
    const askedFor = dataset.id;
    setTurns((t) => [...t, { id, question: text, status: "pending" }]);
    setDraft("");
    const ctl = new AbortController();
    controller.current = ctl;
    try {
      const response = await api.ask(askedFor, text, ctl.signal);
      // Never show an answer for a dataset that is no longer selected.
      if (response.dataset.id !== datasetRef.current || ctl.signal.aborted) return;
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, status: "done", response } : x)));
    } catch (err) {
      if (isAbort(err) || datasetRef.current !== askedFor) return;
      if (err instanceof ApiError && err.code === "questions_unavailable") void refresh();
      const message = err instanceof ApiError && err.code === "busy" ? "MolarMetrics is still finishing your previous question. Try again in a moment." : err instanceof Error ? err.message : "Something went wrong while answering. Please try again.";
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, status: "error", error: message } : x)));
    }
  }

  function retry(turn: Turn) {
    setTurns((t) => t.filter((x) => x.id !== turn.id));
    void send(turn.question);
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void send(draft);
  };

  return (
    <div className="flex min-h-[calc(100dvh-8rem)] flex-col gap-5">
      <div className="space-y-4">
        <PageTitle>Ask MolarMetrics.</PageTitle>
        <DatasetSelect />
      </div>

      {!available && (
        <Alert
          tone="warning"
          action={
            <Button
              variant="secondary"
              size="sm"
              disabled={checking}
              onClick={async () => {
                setChecking(true);
                await refresh();
                setChecking(false);
              }}
            >
              {checking ? "Checking…" : "Check again"}
            </Button>
          }
        >
          {UNAVAILABLE}{" "}
          <Link to="/overview" className="font-medium underline">
            Go to the overview
          </Link>
        </Alert>
      )}

      <div className="flex-1 space-y-5" aria-live="polite" aria-busy={pending}>
        {turns.length === 0 && suggestions.length > 0 && (
          <section aria-labelledby="suggestions-title">
            <h2 id="suggestions-title" className="text-sm font-medium text-muted">
              Try asking about {dataset.name} ({dataset.coverage.label})
            </h2>
            <ul className="mt-3 flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <li key={s}>
                  <button
                    type="button"
                    disabled={!available || pending}
                    onClick={() => void send(s)}
                    className="rounded-full border border-line-strong bg-surface px-3.5 py-2 text-left text-sm text-ink hover:border-teal hover:bg-teal-soft disabled:cursor-not-allowed disabled:text-muted"
                  >
                    {s}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )}

        {turns.map((turn) => (
          <div key={turn.id} className="space-y-3">
            <div className="rounded-lg border border-teal-line bg-teal-soft px-4 py-3 text-sm text-navy">
              <span className="sr-only">You asked: </span>
              {turn.question}
            </div>
            {turn.status === "pending" && (
              <Card className="px-5 py-4">
                <Spinner label="Working on your answer…" />
              </Card>
            )}
            {turn.status === "error" && (
              <Alert
                tone="error"
                action={
                  <Button variant="secondary" size="sm" onClick={() => retry(turn)} disabled={pending}>
                    <RotateCcw aria-hidden className="size-4" />
                    Try again
                  </Button>
                }
              >
                {turn.error}
              </Alert>
            )}
            {turn.status === "done" && turn.response && <AnswerCard response={turn.response} />}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form onSubmit={onSubmit} className="sticky bottom-0 -mx-1 bg-surface px-1 pb-3 pt-2">
        <label htmlFor="question" className="sr-only">
          Ask about your clinic
        </label>
        <div className="flex items-center gap-2 rounded-xl border border-line-strong bg-surface p-1.5 pl-4 focus-within:border-teal">
          <input
            id="question"
            ref={inputRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            maxLength={500}
            placeholder="Ask about your clinic…"
            disabled={!available}
            autoComplete="off"
            className="h-10 min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-[#7a8794] disabled:cursor-not-allowed"
          />
          <button
            type="submit"
            disabled={!available || pending || !draft.trim()}
            className="inline-flex size-10 shrink-0 items-center justify-center rounded-lg bg-teal text-white hover:bg-teal-hover disabled:cursor-not-allowed disabled:bg-[#9cbfbb]"
          >
            <ChevronRight aria-hidden className="size-5" />
            <span className="sr-only">Send question</span>
          </button>
        </div>
        {pending && <p className="mt-1.5 text-xs text-muted">Working on your answer… You can ask the next question when it arrives.</p>}
      </form>
    </div>
  );
}

function AnswerCard({ response }: { response: AskResponse }) {
  const usable = response.results.filter((r) => r.status === "ok" || r.status === "empty");
  const unavailable = response.results.filter((r) => r.status === "unavailable");
  const primary = usable[0];
  const title =
    response.status === "out_of_scope"
      ? "Outside what your data can show"
      : response.status === "not_available"
        ? "Not available for this dataset"
        : response.status === "no_match"
          ? "Answer"
          : primary?.title ?? "Answer";
  const definitions = [...new Map(usable.flatMap((r) => r.definitions).map((d) => [d.key, d])).values()];
  return (
    <Card as="article" className="px-5 py-5 sm:px-6">
      <h2 className="text-lg font-semibold text-navy">{title}</h2>
      {primary && <p className="mt-0.5 text-xs text-muted">{primary.period_label}</p>}
      <p className="mt-2 text-[0.95rem] leading-relaxed text-ink">{response.answer}</p>

      {primary?.chart && (
        <div className="mt-5">
          <ResultChart result={primary} />
        </div>
      )}

      {unavailable.length > 0 && usable.length > 0 && (
        <Alert tone="info" className="mt-4">
          {[...new Set(unavailable.map((r) => r.unavailable_reason))].map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
        </Alert>
      )}

      {usable.length > 0 && (
        <div className="mt-5 flex flex-wrap items-start justify-between gap-3 border-t border-line pt-3">
          <div className="min-w-0 flex-1 space-y-1">
            <Disclosure label="View supporting data">
              <div className="space-y-6">
                {usable.map((r) => (
                  <SupportingData key={r.id} result={r} />
                ))}
              </div>
            </Disclosure>
            {definitions.length > 0 && (
              <Disclosure label="How this is calculated">
                <dl className="space-y-2 text-sm">
                  {definitions.map((d) => (
                    <div key={d.key}>
                      <dt className="font-medium text-ink">{d.label}</dt>
                      <dd className="text-muted">{d.text}</dd>
                    </div>
                  ))}
                </dl>
              </Disclosure>
            )}
          </div>
          {primary?.export_url && (
            <a href={primary.export_url} download className="inline-flex items-center gap-1.5 py-1 text-sm font-medium text-teal hover:underline">
              <Download aria-hidden className="size-4" />
              Download results
            </a>
          )}
        </div>
      )}
    </Card>
  );
}

function SupportingData({ result }: { result: AnalysisPayload }) {
  const metricsTable = {
    columns: [
      { key: "label", label: "Measure", kind: "text" as const, unit: "text", aggregation: "label" },
      { key: "value", label: "Value", kind: "text" as const, unit: "text", aggregation: "label" },
      { key: "note", label: "Basis", kind: "text" as const, unit: "text", aggregation: "label" },
    ],
    rows: [],
    display: result.metrics.map((m) => ({
      label: m.label,
      value: m.formatted,
      note: [m.date_basis ? `by ${m.date_basis}` : "", m.note ?? ""].filter(Boolean).join("; "),
    })),
  };
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-navy">
          {result.title} <span className="font-normal text-muted">· {result.period_label}</span>
        </h3>
        {result.export_url && (
          <a href={result.export_url} download className="inline-flex items-center gap-1 text-sm font-medium text-teal hover:underline">
            <Download aria-hidden className="size-3.5" />
            CSV
          </a>
        )}
      </div>
      {result.table ? <DataTable table={result.table} caption={result.title} /> : result.metrics.length > 0 && <DataTable table={metricsTable} caption={result.title} />}
      {result.facts.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold uppercase tracking-wide text-muted">Calculated from your records</h4>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink">
            {result.facts.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </div>
      )}
      {[...result.warnings, ...result.notes].length > 0 && (
        <ul className="space-y-1 text-xs text-muted">
          {[...result.warnings, ...result.notes].map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
