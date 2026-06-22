import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { V2Draft } from "@/lib/api";

import { RefineEditor } from "./refine-editor";

const draft: V2Draft = {
  session_id: "s1",
  status: "draft",
  approved_at: null,
  insights_stale: false,
  segments: [
    {
      segment_id: 0,
      speaker_label: "speaker_1",
      speaker_name: "Alice",
      tokens: ["we", "use", "the", "DStack", "protocol"],
    },
    {
      segment_id: 1,
      speaker_label: "speaker_2",
      speaker_name: null,
      tokens: ["sounds", "good"],
    },
  ],
  annotations: [
    { span: { segment_id: 0, token_start: 0, token_end: 1 }, surface: "we", state: "known", type: "person", source: "user", confidence: null },
    { span: { segment_id: 0, token_start: 3, token_end: 4 }, surface: "DStack", state: "oov", type: null, source: "nlp", confidence: null },
    { span: { segment_id: 0, token_start: 4, token_end: 5 }, surface: "protocol", state: "candidate", type: null, source: "nlp", confidence: null },
  ],
};

describe("RefineEditor", () => {
  it("renders segments with the confirmed speaker name, falling back to the label (F1b)", () => {
    render(<RefineEditor draft={draft} />);
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("speaker_2")).toBeInTheDocument(); // fallback when no name
    expect(screen.getByText("DStack")).toBeInTheDocument();
  });

  it("applies the right token-state tints (F1c)", () => {
    const { container } = render(<RefineEditor draft={draft} />);
    expect(container.querySelector('[data-token="0"][data-segment="0"]')!.className).toContain("tok-known");
    expect(container.querySelector('[data-token="3"][data-segment="0"]')!.className).toContain("tok-oov");
    expect(container.querySelector('[data-token="4"][data-segment="0"]')!.className).toContain("tok-candidate");
    // an un-annotated token has no state
    expect(container.querySelector('[data-token="1"][data-segment="0"]')!.getAttribute("data-state")).toBe("");
  });
});
