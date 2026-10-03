import { describe, expect, it } from "vitest";
import { firstName, fmt, fmtDuration, initialsOf, pct, relativeTime, ukPhone } from "./format";

describe("fmt (pence, as the prototype's fmt)", () => {
  it("drops pence for whole pounds and keeps two places otherwise", () => {
    expect(fmt(3000)).toBe("£30");
    expect(fmt(2550)).toBe("£25.50");
    expect(fmt(174200)).toBe("£1,742");
    expect(fmt(26130)).toBe("£261.30");
    expect(fmt(5)).toBe("£0.05");
  });
});

describe("fmtDuration (as the prototype)", () => {
  it("uses minutes under 90 and half hours above", () => {
    expect(fmtDuration(38)).toBe("38 minutes");
    expect(fmtDuration(89)).toBe("89 minutes");
    expect(fmtDuration(90)).toBe("1½ hours");
    expect(fmtDuration(120)).toBe("2 hours");
    expect(fmtDuration(510)).toBe("8½ hours");
    expect(fmtDuration(135)).toBe("2½ hours"); // Math.round(4.5) rounds up
  });
});

describe("small helpers", () => {
  it("formats percentages, initials, first names and phones", () => {
    expect(pct(0.15)).toBe("15%");
    expect(initialsOf("Dave Hughes")).toBe("DH");
    expect(firstName("Sarah Whitfield")).toBe("Sarah");
    expect(ukPhone("+447700900123")).toBe("07700 900123");
  });
  it("describes times relative to now", () => {
    const now = new Date("2026-10-02T12:00:00Z");
    expect(relativeTime("2026-10-02T11:59:40Z", now)).toBe("just now");
    expect(relativeTime("2026-10-02T11:56:00Z", now)).toBe("4 min ago");
    expect(relativeTime("2026-10-02T11:00:00Z", now)).toBe("1 hr ago");
    expect(relativeTime("2026-09-30T12:00:00Z", now)).toBe("2 days ago");
  });
});
