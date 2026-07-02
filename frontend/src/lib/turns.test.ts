import { describe, expect, it } from "vitest";

import { groupConsecutive, groupIntoTurns, PARAGRAPH_GAP_SEC, speakerKey } from "./turns";

const s = (speaker: string, text: string, start: number, end: number, extra = {}) => ({
  speaker,
  text,
  start,
  end,
  ...extra,
});

describe("speakerKey", () => {
  it("prefers resolved identity, falls back to the local label", () => {
    expect(speakerKey({ voiceprint_id: "vp1", speaker: "0" })).toBe("vp:vp1");
    expect(speakerKey({ speaker_name: "Ada", speaker: "0" })).toBe("name:Ada");
    expect(speakerKey({ speaker: "2" })).toBe("local:2");
  });
  it("does NOT use proposed_name as a key", () => {
    expect(speakerKey({ proposed_name: "Ada", speaker: "0" })).toBe("local:0");
  });
});

describe("groupConsecutive (editor grouping)", () => {
  it("groups consecutive same-speaker items", () => {
    const items = [
      { speaker_label: "s1" },
      { speaker_label: "s1" },
      { speaker_label: "s2" },
      { speaker_label: "s1" },
    ];
    const groups = groupConsecutive(items, (i) => speakerKey(i));
    expect(groups.map((g) => g.length)).toEqual([2, 1, 1]);
  });
});

describe("groupIntoTurns (live page)", () => {
  it("coalesces consecutive same-speaker spans into one turn", () => {
    const turns = groupIntoTurns([s("0", "hi", 0, 1), s("0", "there", 1, 2)]);
    expect(turns).toHaveLength(1);
    expect(turns[0].text).toBe("hi there");
    expect(turns[0].start).toBe(0);
    expect(turns[0].end).toBe(2);
    expect(turns[0].spans).toHaveLength(2);
  });

  it("starts a new turn on a speaker change", () => {
    const turns = groupIntoTurns([s("0", "a", 0, 1), s("1", "b", 1, 2), s("0", "c", 2, 3)]);
    expect(turns.map((t) => t.text)).toEqual(["a", "b", "c"]);
  });

  it("never merges two distinct unknown speakers", () => {
    expect(groupIntoTurns([s("0", "a", 0, 1), s("1", "b", 1, 2)])).toHaveLength(2);
  });

  it("merges the same voiceprint across different local labels", () => {
    const turns = groupIntoTurns([
      s("0", "one", 0, 1, { voiceprint_id: "vp" }),
      s("3", "two", 1, 2, { voiceprint_id: "vp" }),
    ]);
    expect(turns).toHaveLength(1);
    expect(turns[0].text).toBe("one two");
  });

  it("absorbs empty/whitespace spans without opening or flipping a turn", () => {
    const turns = groupIntoTurns([s("0", "hello", 0, 1), s("1", "  ", 1, 1.2), s("0", "world", 1.2, 2)]);
    expect(turns).toHaveLength(1);
    expect(turns[0].text).toBe("hello world");
    expect(turns[0].spans).toHaveLength(3);
  });

  it("inserts a paragraph break on a big same-speaker gap (still one turn)", () => {
    const turns = groupIntoTurns([
      s("0", "before", 0, 2),
      s("0", "after", 2 + PARAGRAPH_GAP_SEC + 1, 2 + PARAGRAPH_GAP_SEC + 3),
    ]);
    expect(turns).toHaveLength(1);
    expect(turns[0].text).toContain("\n\n");
  });

  it("handles empty input", () => {
    expect(groupIntoTurns([])).toEqual([]);
  });
});
