import { expect, test, type Page } from "@playwright/test";
import { csvRows, downloadText, expectCleanCopy, importLakeview, importSunrise } from "./helpers";

async function askQuestion(page: Page, question: string) {
  await page.getByLabel("Ask about your clinic").fill(question);
  await page.getByRole("button", { name: "Send question" }).click();
}

test("a late answer for a previous dataset is never shown", async ({ page }) => {
  await importSunrise(page);
  await importLakeview(page, ["appointments"]);
  await page.goto("/ask");
  const lakeviewId = await page.getByLabel("Dataset").inputValue();
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route("**/api/datasets/*/ask", async (route) => {
    await held;
    await route.fulfill({
      json: {
        id: "late", question: "x", status: "answered", answer: "LATE ANSWER FOR THE OLD DATASET", results: [],
        dataset: { id: lakeviewId, name: "Lakeview appointments", kind: "uploaded" },
      },
    });
  });
  await askQuestion(page, "How many completed visits were there in 2024?");
  await expect(page.getByText("Working on your answer…").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Send question" })).toBeDisabled();
  await page.getByLabel("Dataset").selectOption({ label: "Sunrise Dental" });
  await expect(page.getByText("Try asking about Sunrise Dental")).toBeVisible();
  release();
  await page.waitForTimeout(800);
  await expect(page.getByText("LATE ANSWER FOR THE OLD DATASET")).toHaveCount(0);
  await expect(page.getByText("How many completed visits were there in 2024?")).toHaveCount(0);
});

test("a failed answer can be retried", async ({ page }) => {
  await importLakeview(page, ["appointments"]);
  await page.goto("/ask");
  const id = await page.getByLabel("Dataset").inputValue();
  let calls = 0;
  await page.route("**/api/datasets/*/ask", async (route) => {
    calls += 1;
    if (calls === 1) {
      await route.fulfill({ status: 502, json: { error: { code: "answer_failed", message: "Something went wrong while answering. Please try again." } } });
      return;
    }
    await route.fulfill({
      json: { id: "ok", question: "q", status: "no_match", answer: "Retried answer.", results: [], dataset: { id, name: "Lakeview appointments", kind: "uploaded" } },
    });
  });
  await askQuestion(page, "What was the no-show rate by month in 2024?");
  await expect(page.getByText("Something went wrong while answering. Please try again.")).toBeVisible();
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByText("Retried answer.")).toBeVisible();
  await expectCleanCopy(page);
});

test("when questions are unavailable the page says so plainly", async ({ page }) => {
  await page.route("**/api/session", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, questions_available: false } });
  });
  await importLakeview(page, ["appointments"]);
  await page.goto("/ask");
  await expect(page.getByText("Questions are temporarily unavailable. You can still explore your overview.")).toBeVisible();
  await expect(page.getByLabel("Ask about your clinic")).toBeDisabled();
  await expectCleanCopy(page);
  await page.getByRole("link", { name: "Go to the overview" }).click();
  await expect(page.getByRole("heading", { name: "Appointments by status" })).toBeVisible();
});

async function ollamaReady(): Promise<boolean> {
  try {
    const res = await fetch("http://127.0.0.1:11434/api/tags", { signal: AbortSignal.timeout(2000) });
    const body = (await res.json()) as { models?: { name: string }[] };
    return Boolean(body.models?.some((m) => m.name === "llama3.2:3b"));
  } catch {
    return false;
  }
}

test("live: the local model answers from the selected uploaded dataset", async ({ page }) => {
  test.skip(!(await ollamaReady()), "NOT RUN: the local question service (Ollama with llama3.2:3b) is not reachable");
  test.setTimeout(420_000);
  await importSunrise(page);
  await page.goto("/ask");
  await askQuestion(page, "Which procedures generated the most billed revenue in 2025?");
  const first = page.locator("main article").first();
  await expect(first).toBeVisible({ timeout: 240_000 });
  await expect(first).toContainText("Crown");
  await first.getByRole("button", { name: "View supporting data" }).click();
  await expect(first.getByRole("region")).toContainText("₹23,000.00");
  const csv = csvRows(await downloadText(page, () => first.getByRole("link", { name: "Download results" }).click()));
  expect(csv.find((r) => r.procedure === "Crown")?.billed_inr).toBe("23000.00");
  expect(new Set(csv.map((r) => r.dataset))).toEqual(new Set(["Sunrise Dental"]));
  await expectCleanCopy(page);

  await importLakeview(page);
  await page.goto("/ask");
  await askQuestion(page, "What was billed revenue in 2024?");
  const answer = page.locator("main article").first();
  await expect(answer).toBeVisible({ timeout: 240_000 });
  await expect(answer).toContainText("₹41,000.00");
  await expect(answer).not.toContainText("₹47,000");
  await expectCleanCopy(page);
});
