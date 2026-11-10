import { expect, test } from "@playwright/test";
import { expectCleanCopy, importSunrise } from "./helpers";

test("keyboard: skip link, navigation and visible focus", async ({ page }) => {
  await importSunrise(page);
  await page.goto("/overview");
  await expect(page.getByRole("heading", { name: "Billed revenue and collections" })).toBeVisible();
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "Skip to content" });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  await expect(focused).toHaveText(/Overview/);
  const outline = await focused.evaluate((el) => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe("none");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "Ask MolarMetrics." })).toBeVisible();
});

test("mobile: usable menu, no sideways scrolling, readable screens", async ({ page }, info) => {
  await importSunrise(page);
  await page.setViewportSize({ width: 390, height: 844 });
  for (const route of ["/overview", "/ask", "/data"]) {
    await page.goto(route);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `horizontal overflow on ${route}`).toBeLessThanOrEqual(0);
    await page.screenshot({ path: info.outputPath(`mobile${route.replace("/", "-")}.png`), fullPage: true });
    await expectCleanCopy(page);
  }
  const menu = page.getByRole("button", { name: "Open menu" });
  await menu.click();
  await expect(page.getByRole("button", { name: "Close menu" })).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Open menu" })).toBeFocused();
  await menu.click();
  await page.locator("#mobile-nav").getByRole("link", { name: "Overview" }).click();
  await expect(page.getByRole("heading", { name: "Clinic overview." })).toBeVisible();
  await expect(page.locator("#mobile-nav")).toBeHidden();
});

test("desktop screenshots of every screen", async ({ page }, info) => {
  await page.goto("/data");
  await page.screenshot({ path: info.outputPath("desktop-upload.png") });
  await importSunrise(page);
  await page.screenshot({ path: info.outputPath("desktop-overview.png"), fullPage: true });
  await page.goto("/ask");
  await page.screenshot({ path: info.outputPath("desktop-ask.png") });
  await page.goto("/data");
  await page.screenshot({ path: info.outputPath("desktop-data.png"), fullPage: true });
});
