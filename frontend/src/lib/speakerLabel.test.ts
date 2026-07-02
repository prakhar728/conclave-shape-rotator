import { describe, expect, it } from "vitest";

import { speakerLabel } from "./speakerLabel";

describe("speakerLabel", () => {
  it("normalizes engine-specific indices to 'Speaker N'", () => {
    expect(speakerLabel("2")).toBe("Speaker 2");        // DiariZen bare index
    expect(speakerLabel("speaker0")).toBe("Speaker 0"); // diart
    expect(speakerLabel("Speaker 1")).toBe("Speaker 1"); // already normalized
    expect(speakerLabel("spk_3")).toBe("Speaker 3");
  });

  it("leaves real names untouched", () => {
    expect(speakerLabel("Ada Lovelace")).toBe("Ada Lovelace");
    expect(speakerLabel("Grace")).toBe("Grace");
  });

  it("handles blank / missing labels", () => {
    expect(speakerLabel("")).toBe("Speaker");
    expect(speakerLabel(null)).toBe("Speaker");
    expect(speakerLabel(undefined)).toBe("Speaker");
  });

  it("does not turn a name that merely ends in a number into 'Speaker N'", () => {
    expect(speakerLabel("Room 4")).toBe("Room 4"); // not a speaker-index pattern
  });
});
