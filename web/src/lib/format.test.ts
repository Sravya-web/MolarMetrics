import { describe, expect, it } from "vitest";
import { formatBytes, formatDate, formatInr, formatInrAxis, indianGrouping, niceTicks } from "./format";

describe("money formatting", () => {
  it("formats exact rupees from integer paise with Indian grouping", () => {
    expect(formatInr(4_700_000)).toBe("₹47,000.00");
    expect(formatInr(12_345_678)).toBe("₹1,23,456.78");
    expect(formatInr(543_210_050)).toBe("₹54,32,100.50");
    expect(formatInr(7)).toBe("₹0.07");
    expect(formatInr(-250_000)).toBe("-₹2,500.00");
    expect(formatInr(0)).toBe("₹0.00");
  });

  it("refuses non-integer paise rather than rounding silently", () => {
    expect(() => formatInr(10.5)).toThrow();
  });

  it("groups digits the Indian way", () => {
    expect(indianGrouping(999)).toBe("999");
    expect(indianGrouping(1000)).toBe("1,000");
    expect(indianGrouping(100000)).toBe("1,00,000");
    expect(indianGrouping(12345678)).toBe("1,23,45,678");
  });

  it("uses compact labels only for axes", () => {
    expect(formatInrAxis(0)).toBe("₹0");
    expect(formatInrAxis(50_000)).toBe("₹500");
    expect(formatInrAxis(250_000)).toBe("₹2.5K");
    expect(formatInrAxis(15_000_000)).toBe("₹1.5L");
    expect(formatInrAxis(2_500_000_000)).toBe("₹2.5Cr");
  });
});

describe("other formatting", () => {
  it("formats dates and sizes", () => {
    expect(formatDate("2025-03-12")).toBe("12 Mar 2025");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1536)).toBe("1.5 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });

  it("chooses round axis ticks that cover the maximum", () => {
    const ticks = niceTicks(1_900_000);
    expect(ticks[0]).toBe(0);
    expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(1_900_000);
    expect(ticks).toEqual([0, 500_000, 1_000_000, 1_500_000, 2_000_000]);
  });
});
