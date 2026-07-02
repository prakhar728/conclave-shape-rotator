import { describe, expect, it } from "vitest";

import { meetingTitle } from "./meetingTitle";

describe("meetingTitle", () => {
  it("prefers an explicit title", () => {
    expect(meetingTitle("Board sync", "a long summary paragraph here")).toBe("Board sync");
  });

  it("trims whitespace-only titles and falls back to the summary lead", () => {
    expect(meetingTitle("   ", "We shipped the matcher today")).toBe(
      "We shipped the matcher today",
    );
  });

  it("falls back to the summary's first line when there's no title (legacy)", () => {
    expect(meetingTitle(null, "First line.\nSecond line.")).toBe("First line.");
  });

  it("cuts a long single-line summary at a sentence boundary", () => {
    expect(meetingTitle(null, "We shipped it. Then we celebrated at length.")).toBe(
      "We shipped it",
    );
  });

  it("truncates a long summary lead with an ellipsis", () => {
    const long = "word ".repeat(40).trim();
    const out = meetingTitle(null, long);
    expect(out.endsWith("…")).toBe(true);
    expect(out.length).toBeLessThan(long.length);
  });

  it("returns a neutral placeholder when there is neither a title nor a summary", () => {
    expect(meetingTitle(null, null)).toBe("Untitled meeting");
    expect(meetingTitle(undefined, undefined)).toBe("Untitled meeting");
  });
});
