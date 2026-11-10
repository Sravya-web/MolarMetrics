import { expect, test } from "@playwright/test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { LAKEVIEW, SUNRISE, csvRows, downloadText, expectCleanCopy, importLakeview, importSunrise, kpi } from "./helpers";

test("first visit: the upload screen, no sample data loaded", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Understand your dental practice." })).toBeVisible();
  await expect(page.getByText("Turn clinic records into clear insights.")).toBeVisible();
  await expect(page.getByText("Drop your CSV files here")).toBeVisible();
  await expect(page.getByRole("button", { name: "Download templates" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Explore sample data" })).toBeVisible();
  await expect(page.getByText(/deleted automatically after 24 hours without use/)).toBeVisible();
  await expect(page.getByText("Sample data", { exact: true })).toHaveCount(0);
  await page.getByRole("link", { name: "Overview" }).first().click();
  await expect(page.getByText("No clinic data yet")).toBeVisible();
  await expectCleanCopy(page);
});

test("Sunrise upload: overview, table view and download match the hand calculations", async ({ page }) => {
  await importSunrise(page);
  await expect(page.getByText(/Sunrise Dental is ready/)).toBeVisible();
  await expect(kpi(page, "Billed revenue")).toContainText(SUNRISE.billed);
  await expect(kpi(page, "Billed revenue")).toContainText(SUNRISE.billedExact);
  await expect(kpi(page, "Collections")).toContainText(SUNRISE.collected);
  await expect(kpi(page, "Completed visits")).toContainText("11");
  await expect(kpi(page, "No-show rate")).toContainText("18.8%");
  await expect(kpi(page, "Outstanding balance")).toContainText(SUNRISE.outstanding);
  await expect(page.getByText("Sample data", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "View data" }).first().click();
  const table = page.getByRole("region", { name: /Billed revenue and collections, by month/ });
  await expect(table).toContainText("₹10,000.00");
  await expect(table).toContainText("₹15,200.00");
  await page.getByRole("button", { name: "Cumulative" }).click();
  await expect(page.getByRole("region", { name: /cumulative/ })).toContainText("₹47,000.00");

  const csv = await downloadText(page, () => page.getByRole("link", { name: "Download CSV" }).first().click());
  const rows = csvRows(csv);
  expect(rows.map((r) => [r.month, r.billed_inr, r.collected_inr])).toEqual([
    ["2025-01", "10000.00", "8000.00"],
    ["2025-02", "18000.00", "14000.00"],
    ["2025-03", "19000.00", "15200.00"],
  ]);
  expect(new Set(rows.map((r) => r.dataset))).toEqual(new Set(["Sunrise Dental"]));
  await expectCleanCopy(page);
});

test("switching datasets updates every figure and sample data never leaks", async ({ page }) => {
  await importSunrise(page);
  await importLakeview(page);
  await page.goto("/overview");
  await expect(kpi(page, "Billed revenue")).toContainText(LAKEVIEW.billed);
  await expect(kpi(page, "Collections")).toContainText(LAKEVIEW.collected);
  await expect(kpi(page, "Outstanding balance")).toContainText(LAKEVIEW.outstanding);
  await expect(page.getByText(/1 treatment record on cancelled or no-show appointments was left out/)).toBeVisible();

  await page.getByLabel("Dataset").selectOption({ label: "Sunrise Dental" });
  await expect(kpi(page, "Billed revenue")).toContainText(SUNRISE.billed);
  await expect(page.getByLabel("Reporting period")).toHaveValue("all");

  await page.goto("/data");
  await page.getByRole("button", { name: "Explore sample data" }).click();
  await expect(page.getByText("Sample data", { exact: true })).toBeVisible();
  const sampleBilled = await kpi(page, "Billed revenue").innerText();
  expect(sampleBilled).not.toContain(SUNRISE.billed);
  expect(sampleBilled).not.toContain(LAKEVIEW.billed);

  await page.getByLabel("Dataset").selectOption({ label: "Lakeview Dental" });
  await expect(kpi(page, "Billed revenue")).toContainText(LAKEVIEW.billed);
  await expect(page.getByText("Sample data", { exact: true })).toHaveCount(0);
});

test("appointments-only data shows appointment charts and explains what's missing", async ({ page }) => {
  await importLakeview(page, ["appointments"]);
  await expect(page.getByRole("heading", { name: "Appointments by status" })).toBeVisible();
  await expect(page.getByText("Add treatment records to see billed revenue and top procedures.")).toBeVisible();
  await expect(page.getByText("Add payment records to see collections and outstanding balances.")).toBeVisible();
  await expect(kpi(page, "Completed visits")).toContainText("7");
  await expect(kpi(page, "No-show rate")).toContainText("20.0%");
  await expect(page.locator("main")).not.toContainText("₹");
  await expect(page.getByRole("heading", { name: "Billed revenue and collections" })).toHaveCount(0);
});

test("invalid files: row-numbered issues, no import, downloadable report", async ({ page }) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mm-bad-"));
  const file = path.join(dir, "appointments.csv");
  fs.writeFileSync(file, "appointment_id,patient_id,appointment_date,status\nA1,P1,2025-01-05,completed\nA1,P2,2025-01-06,completed\nA3,P3,2025-02-30,completed\nA4,,2025-02-03,completed\n");
  await page.goto("/data");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose files" }).click();
  await (await chooser).setFiles(file);
  await expect(page.getByText("appointments.csv")).toBeVisible();
  await expect(page.getByText(/\d+(\.\d)? (B|KB)/)).toBeVisible();
  await page.getByRole("button", { name: "Upload and review" }).click();
  await expect(page.getByText(/Row 3: Appointment ID 'A1' is already used in row 2/)).toBeVisible();
  await expect(page.getByText(/Row 4: '2025-02-30' isn't a valid date/)).toBeVisible();
  await expect(page.getByText("Row 5: Patient ID is blank.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Import data" })).toBeDisabled();
  await expect(page.getByText("Ready to import")).toHaveCount(0);
  const report = await downloadText(page, () => page.getByRole("link", { name: "Download issues report" }).click());
  expect(report).toContain("Must fix");
  expect(report).toContain("already used in row 2");
  await expectCleanCopy(page);
});

test("files can be removed before upload, and rejected files are explained", async ({ page }) => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "mm-files-"));
  fs.writeFileSync(path.join(dir, "notes.txt"), "hello");
  fs.writeFileSync(path.join(dir, "book.csv"), Buffer.from([0x50, 0x4b, 0x03, 0x04, 0, 1]));
  await page.goto("/data");
  const chooser = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose files" }).click();
  await (await chooser).setFiles([path.join(dir, "notes.txt"), path.join(dir, "book.csv")]);
  await expect(page.getByText("notes.txt isn't a .csv file.")).toBeVisible();
  await page.getByRole("button", { name: "Upload and review" }).click();
  await expect(page.getByText(/looks like an Excel workbook/)).toBeVisible();
  await page.getByRole("button", { name: "Remove book.csv" }).click();
  await expect(page.getByText("book.csv")).toHaveCount(0);
});

test("remove dataset asks for confirmation and deletes it", async ({ page }) => {
  await importLakeview(page, ["appointments"]);
  await page.goto("/data");
  await expect(page.getByRole("heading", { name: "Data & uploads." })).toBeVisible();
  await page.getByRole("button", { name: "Remove dataset" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("permanently deletes the imported records");
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(page.getByRole("heading", { name: "Lakeview appointments" })).toBeVisible();
  await page.getByRole("button", { name: "Remove dataset" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Remove dataset" }).click();
  await expect(page.getByRole("heading", { name: "Understand your dental practice." })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Lakeview appointments" })).toHaveCount(0);
});
