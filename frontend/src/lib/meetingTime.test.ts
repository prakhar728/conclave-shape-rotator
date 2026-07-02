import { describe, expect, it } from "vitest";

import { meetingWhen } from "./meetingTime";

const NOW = new Date("2026-07-02T15:00:00Z");

describe("meetingWhen", () => {
  it("renders recent times as relative", () => {
    expect(meetingWhen("2026-07-02T14:59:30Z", "2026-07-02", NOW).label).toBe("just now");
    expect(meetingWhen("2026-07-02T14:30:00Z", "2026-07-02", NOW).label).toBe("30m ago");
    expect(meetingWhen("2026-07-02T13:00:00Z", "2026-07-02", NOW).label).toBe("2h ago");
  });

  it("renders older-than-a-day times as an absolute date+time (has a clock time)", () => {
    const w = meetingWhen("2026-06-28T09:00:00Z", "2026-06-28", NOW);
    expect(w.hasTime).toBe(true);
    // Absolute form includes a year and a minute — locale-dependent, so assert structure.
    expect(w.label).toMatch(/2026/);
    expect(w.label).toMatch(/\d:\d\d/);
    expect(w.label).not.toMatch(/ago/);
  });

  it("always exposes an absolute title for hover, even when the label is relative", () => {
    const w = meetingWhen("2026-07-02T14:30:00Z", "2026-07-02", NOW);
    expect(w.label).toBe("30m ago");
    expect(w.title).toMatch(/2026/);
    expect(w.title).toMatch(/\d:\d\d/);
  });

  it("degrades to the plain date when there is no timestamp (legacy), no bogus time", () => {
    const w = meetingWhen(null, "2026-05-20", NOW);
    expect(w.hasTime).toBe(false);
    expect(w.label).toBe("2026-05-20");
    expect(w.label).not.toMatch(/\d:\d\d/);
  });

  it("treats an unparseable timestamp as date-only (never NaN/Invalid Date)", () => {
    const w = meetingWhen("not-a-date", "2026-05-20", NOW);
    expect(w.hasTime).toBe(false);
    expect(w.label).toBe("2026-05-20");
  });

  it("treats a future timestamp (clock skew) as absolute, not a negative relative", () => {
    const w = meetingWhen("2026-07-02T16:00:00Z", "2026-07-02", NOW);
    expect(w.label).not.toMatch(/ago/);
    expect(w.label).toMatch(/2026/);
  });
});
