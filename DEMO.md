# MolarMetrics: portfolio demo walkthrough

> This script describes the **earlier Streamlit app** (`streamlit run app.py`) on the bundled sample
> data. The current web app (`./scripts/start.sh`) is described in the [README](README.md).

A local portfolio prototype using **synthetic data**. Present it that way: it is not production
software, it has no clinical validation, and it makes no claims about business impact.

## Demo checklist (5 minutes before)

1. `ollama list` shows `llama3.2:3b`. If it can't connect, open the Ollama app.
2. `cd ~/Desktop/MolarMetrics && source .venv/bin/activate && python -m pytest -q` passes in about 5 s.
3. Warm up the model, because the first answer is slow:
   `python scripts/ask.py "What was billed revenue in 2025?"`
4. `streamlit run app.py`. The sidebar should say **Chat ready**. Set browser zoom to about 90%.
5. Close memory-heavy apps (this Mac has 8 GB RAM). Keep `reports/integration_report.md` open as backup
   evidence.
6. In the demo, point at three things: the **Calculated by MolarMetrics tools** box, the
   **Model commentary** label, and the **Number check** line.

---

## The two-minute script

### 0:00–0:20 · The problem

> "Dental clinics record appointments, procedures and payments every day, but few have an analyst
> to turn that into answers. **MolarMetrics** is a local prototype: you ask a question in plain
> English, a small AI model on this laptop picks the right analysis, and Python and SQL calculate
> the numbers. Everything here is **synthetic demo data** for a fictional clinic."

*Point at the orange SYNTHETIC DEMO DATA badge.*

### 0:20–0:50 · Dashboard

*Click the **2025** period button.*

> "This dashboard works without any AI at all. In 2025 the clinic **billed ₹68.09 lakh** but
> **collected ₹64.19 lakh**. Those are different measures: billed revenue counts fees by treatment
> date, collections count payments by payment date. The no-show rate is **7.6%**, and the denominator
> is always shown: **225 of 2,954** scheduled appointments, cancellations included."

*Scroll to the billed-vs-collections chart and open one **Table view**.*

### 0:50–1:20 · Ask one question

*Open **Ask MolarMetrics** → **Example questions** → click **"How much was outstanding as of 31 December 2025?"***

> "The model is llama3.2, 3 billion parameters, running locally through Ollama, so no data leaves
> this machine."

*When the answer appears (a few seconds):*

> "Notice the two parts. The top paragraph is labelled **Model commentary**: that's the AI's
> wording. The box below is **Calculated by MolarMetrics tools**: deterministic sentences written by
> Python. The figure is **₹9,05,720.00**, and the **number check** confirms that every number the model
> wrote came from the tool results."

### 1:20–1:45 · The real tool call and the calculation

*Expand **Tool activity**.*

> "The model didn't calculate this. It **chose** `analyze_finances` with
> `metric = outstanding_balance` and `as_of_date = 2025-12-31`. Those arguments were validated, then
> SQL computed **₹1,37,99,880 of net fees minus ₹1,28,94,160 received = ₹9,05,720**, with payments
> summed per treatment first so a split payment can't be double counted. Each number in the result
> carries its unit and aggregation, and every figure is checked against an independent pandas
> calculation in the tests."

### 1:45–2:00 · Limitations and next steps

> "It's honest about its limits. There's no clinical outcome data, so if you ask *'Which treatment
> works best?'*, it declines. A 3B model can still phrase things loosely, which is why the calculated
> summary and tables are shown separately from its commentary. Next steps would be a larger test set
> of rephrased questions and testing larger local models."

*(Optional: click "Which treatment works best?" to show the refusal.)*

---

## How it works (for questions afterwards)

**How the agent selects a tool.**
LangChain's `create_agent` sends the system prompt and four tool schemas to llama3.2:3b through
Ollama's tool-calling API. The schemas are generated from Pydantic models, with enums and defaults.
At temperature 0, the model returns a structured call (a tool name plus JSON arguments), and
LangChain executes it. There is no keyword router, except that the rule-based clinical guard
withholds tools for outcome questions. Tool choice is the model's decision, so it can be wrong; the
live checks measure it on every run. Limits: at most 4 model calls and 3 tool calls per question.

**How tool arguments are validated.**
Each tool has a Pydantic argument model (`molarmetrics/analytics/params.py`). It:
- normalises harmless input: `"2025"` becomes the full year, `"No-show rate"` becomes
  `no_show_rate`, `"RCT"` becomes the catalogue name, and null becomes the default;
- enforces enums, `top_n` between 1 and 20, and start ≤ end;
- drops unknown keys.

A failure goes back to the model as an error message it can correct, with no crash or stack trace.
`run_analysis` validates again and turns database errors into friendly messages. The UI shows both
the model's raw arguments and the validated ones.

**How SQL avoids double counting.**
Each table is aggregated at its own grain before anything is combined:
- billed revenue sums treatments, joined many-to-one to appointments only to get the date;
- collections sum payments by payment date, with no join;
- the outstanding balance pre-aggregates payments per treatment in a CTE before the join;
- monthly billed vs collected runs two separate `GROUP BY` queries merged by month;
- patient counts use `DISTINCT`.

A hand-calculated fixture with a visit that has 2 treatments and a treatment paid in 3 instalments
proves the totals are not inflated.

**How results reach the charts.**
Each tool returns `(content, artifact)`. The model reads only the compact JSON content: facts,
metrics with unit, aggregation and date basis, and a few rows. The app reads `ToolMessage.artifact`:
the full `AnalysisResult` with raw paise, counts and a declarative `ChartSpec`. Fixed code in
`molarmetrics/ui/charts.py` turns that spec into a Plotly figure; tables and CSV downloads come from
the same rows. The model's prose is never parsed for numbers, and no model-written code runs.

**What the rule-based clinical-question guard cannot guarantee.**
It is regular-expression matching on phrasing, so:
- it misses paraphrases ("Which procedure gives the fewest complications?", "Is Dr. Kavya good?"),
  typos, other languages, and follow-ups that depend on earlier messages ("and which of those is
  safest?");
- it can block a legitimate question that happens to match;
- it does not inspect the reply itself; the number check only verifies numbers, not meaning.

It is a narrow first line of defence, backed by the first rule of the system prompt. It is not a
safety guarantee, and nothing in MolarMetrics is clinically validated.

## Talking points

| If asked… | Point to |
|---|---|
| "How do you know the numbers are right?" | `tests/fixtures/mini_clinic.py` (hand-calculated answers), `tests/test_real_dataset.py` (independent pandas cross-check), `reports/integration_report.md` (live model checks). |
| "What stops the model misphrasing?" | Tool results carry explicit units and Python-written facts; `tests/integration/wording_checks.py` catches a total called an average, an unsupported "majority", records called patients, and billed/collections swaps. |
| "Why not let the LLM write SQL?" | Small models make arithmetic and SQL mistakes. Four typed tools with enum arguments are safer, testable and explainable. |
| "How is money handled?" | Integer paise end to end (`molarmetrics/money.py`); INR is only for display and CSV. |
| "What about privacy?" | Local model, no cloud APIs, remote tracing forced off, app bound to localhost, and no names, phones or addresses in the data. |
| "What would production need?" | Real data governance, authentication, audit logs, clinical and regulatory review, and a much larger evaluation. None of these are claimed here. |

## Questions verified live

See the About tab or `reports/integration_report.md` for the last recorded run, with tool facts and
model commentary shown separately.

1. What was billed revenue in 2025?
2. Compare monthly billed revenue and collections in 2025.
3. Which five procedures generated the most billed revenue in 2025?
4. What was the no-show rate by month in 2025?
5. How much was outstanding as of 31 December 2025?
6. Which dentist completed the most appointments in 2025?
7. How many returning patients were seen in 2025?
8. Compare root canal and extraction procedure counts in 2025.
9. Which treatment works best? *(declines: no outcome data)*
10. What was the average patient satisfaction score in 2025? *(declines: not in the data)*
11. How much money was collected in 2025? *(probe for billed/collections mix-ups)*

Untested phrasings may behave differently, and wording can vary slightly between runs. If an answer
looks off, show the calculated summary and the table: that separation is exactly the safety design
this prototype demonstrates.
