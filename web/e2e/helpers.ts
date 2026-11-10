import { expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const EXAMPLES = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../examples");

// Hand-calculated totals: examples/README.md
export const SUNRISE = { billed: "₹47,000", billedExact: "₹47,000.00", collected: "₹37,200.00", outstanding: "₹9,800" };
export const LAKEVIEW = { billed: "₹41,000", billedExact: "₹41,000.00", collected: "₹31,000.00", outstanding: "₹10,000" };

/** Words the clinic-facing app must never show. */
const FORBIDDEN = /\b(artificial intelligence|machine learning|language model|LLM|llama|ollama|langchain|langgraph|python|sql|sqlite|json|tool|tools|model|prompt|traceback|stack trace|database)\b/i;
const AI = /\bA\.?I\b/;

export async function expectCleanCopy(page: Page) {
  const text = await page.locator("body").innerText();
  expect(text.match(FORBIDDEN)?.[0] ?? null, "implementation detail in visible text").toBeNull();
  expect(text.match(AI)?.[0] ?? null, "'AI' in visible text").toBeNull();
}

async function chooseFiles(page: Page, files: string[]) {
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose files" }).click();
  await (await chooser).setFiles(files);
  await page.getByRole("button", { name: "Upload and review" }).click();
  await expect(page.getByRole("heading", { name: "Review your data." })).toBeVisible();
}

export async function importSunrise(page: Page) {
  await page.goto("/data");
  await chooseFiles(page, ["appointments", "treatments", "payments", "patients", "dentists"].map((n) => path.join(EXAMPLES, "sunrise-dental", `${n}.csv`)));
  await expect(page.getByText("Ready to import")).toHaveCount(0);
  // One explicit choice; it also applies to the other ambiguous date columns.
  await page.getByLabel(/Date format: Appointment date/).selectOption("DD/MM/YYYY");
  for (const name of [/treatments\.csv/, /payments\.csv/]) {
    await page.getByRole("button", { name }).first().click();
    await page.getByRole("radio", { name: /Rupees/ }).check();
  }
  await page.getByLabel("Dataset name").fill("Sunrise Dental");
  await expect(page.getByText("Ready to import")).toBeVisible();
  await page.getByRole("button", { name: "Import data" }).click();
  await expect(page.getByRole("heading", { name: "Billed revenue and collections" })).toBeVisible();
}

export async function importLakeview(page: Page, only?: string[]) {
  const names = only ?? ["appointments", "treatments", "payments"];
  await page.goto("/data");
  await chooseFiles(page, names.map((n) => path.join(EXAMPLES, "lakeview-dental", `${n}.csv`)));
  for (const n of names.filter((x) => x === "treatments" || x === "payments")) {
    await page.getByRole("button", { name: new RegExp(`${n}\\.csv`) }).first().click();
    await page.getByRole("radio", { name: /Paise/ }).check();
  }
  if (names.includes("treatments")) {
    await page.locator("fieldset", { hasText: "Treatments on cancelled or no-show appointments" }).getByRole("radio", { name: /Leave out/ }).check();
  }
  if (names.includes("payments")) {
    await page.locator("fieldset", { hasText: "Payments dated before their treatment" }).getByRole("radio", { name: /Include as recorded/ }).check();
  }
  await page.getByLabel("Dataset name").fill(only ? "Lakeview appointments" : "Lakeview Dental");
  await expect(page.getByText("Ready to import")).toBeVisible();
  await page.getByRole("button", { name: "Import data" }).click();
  await expect(page.getByRole("heading", { name: "Clinic overview." })).toBeVisible();
}

export function kpi(page: Page, label: string) {
  return page.locator("main article").filter({ has: page.getByRole("heading", { name: label, exact: true }) });
}

export async function downloadText(page: Page, trigger: () => Promise<void>): Promise<string> {
  const download = page.waitForEvent("download");
  await trigger();
  const file = await (await download).path();
  return fs.readFileSync(file, "utf-8").replace(/^﻿/, "");
}

export function csvRows(text: string): Record<string, string>[] {
  const [header, ...lines] = text.trim().split("\n");
  const cols = header.split(",");
  return lines.map((line) => Object.fromEntries(line.split(",").map((v, i) => [cols[i], v])));
}
