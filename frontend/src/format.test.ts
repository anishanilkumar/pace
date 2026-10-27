import { describe, expect, it } from "vitest";
import { clock, rupees, shiftMonth, span } from "./format";

describe("format", () => {
  it("reads hours as a clock", () => {
    expect(clock(2.4166)).toBe("2:25");
    expect(clock(0)).toBe("0:00");
    expect(clock(10.999)).toBe("11:00");
  });
  it("says spans like the nudges do", () => {
    expect(span(2.4166)).toBe("2 h 25 min");
    expect(span(0.75)).toBe("45 min");
    expect(span(3)).toBe("3 h");
    expect(span(-1.5)).toBe("1 h 30 min");
  });
  it("groups rupees the Indian way", () => {
    expect(rupees(150000)).toBe("₹1,50,000");
  });
  it("steps months across a year", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  });
});
