import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { refine, type V2Draft } from "@/lib/api";

import { RefineEditor } from "./refine-editor";

function makeDraft(): V2Draft {
  return {
    session_id: "s1",
    status: "draft",
    approved_at: null,
    insights_stale: false,
    segments: [
      { segment_id: 0, speaker_label: "speaker_1", speaker_name: "Alice", tokens: ["we", "use", "the", "DStack", "protocol"] },
      { segment_id: 1, speaker_label: "speaker_2", speaker_name: null, tokens: ["sounds", "good"] },
    ],
    annotations: [
      { span: { segment_id: 0, token_start: 0, token_end: 1 }, surface: "we", state: "known", type: "person", source: "user", confidence: null },
      { span: { segment_id: 0, token_start: 3, token_end: 4 }, surface: "DStack", state: "oov", type: null, source: "nlp", confidence: null },
      { span: { segment_id: 0, token_start: 4, token_end: 5 }, surface: "protocol", state: "candidate", type: null, source: "nlp", confidence: null },
    ],
  };
}

function renderEditor() {
  const onChange = vi.fn();
  const utils = render(<RefineEditor draft={makeDraft()} sessionId="s1" onDraftChange={onChange} />);
  return { onChange, ...utils };
}

describe("RefineEditor", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(refine, "speakerSuggestions").mockResolvedValue({ speakers: ["Carol", "Dave"] });
  });

  it("renders segments with the confirmed speaker name, falling back to the label (F1b)", () => {
    renderEditor();
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("speaker_2")).toBeInTheDocument();
    expect(screen.getByText("DStack")).toBeInTheDocument();
  });

  it("applies the right token-state tints (F1c)", () => {
    const { container } = renderEditor();
    expect(container.querySelector('[data-token="0"][data-segment="0"]')!.className).toContain("tok-known");
    expect(container.querySelector('[data-token="3"][data-segment="0"]')!.className).toContain("tok-oov");
    expect(container.querySelector('[data-token="4"][data-segment="0"]')!.className).toContain("tok-candidate");
    expect(container.querySelector('[data-token="1"][data-segment="0"]')!.getAttribute("data-state")).toBe("");
  });

  it("edits a token optimistically without awaiting the network (F2a/FE-2)", () => {
    const editSpy = vi.spyOn(refine, "editToken").mockReturnValue(new Promise(() => {})); // never resolves
    const { onChange } = renderEditor();
    fireEvent.click(screen.getByText("DStack"));
    const input = document.querySelector('[data-token-input="3"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Dstack" } });
    fireEvent.keyDown(input, { key: "Enter" });
    // UI updated BEFORE the network resolved (the promise never does)
    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as V2Draft;
    expect(next.segments[0].tokens[3]).toBe("Dstack");
    expect(next.insights_stale).toBe(true);
    expect(editSpy).toHaveBeenCalledWith("s1", 0, 3, "Dstack");
  });

  it("shows no tag control until a word is selected, then tags ANY word (FE-5)", async () => {
    const tagSpy = vi.spyOn(refine, "tagEntity").mockResolvedValue({ v2: makeDraft() });
    renderEditor();
    expect(document.querySelector("[data-tag]")).toBeNull(); // nothing persistent in the text
    fireEvent.click(screen.getByText("good")); // a plain word — NO annotation
    const sel = document.querySelector('[data-tag="1-1"]') as HTMLSelectElement;
    expect(sel).toBeTruthy(); // the tag option appears only on selection
    fireEvent.change(sel, { target: { value: "project" } });
    await waitFor(() =>
      expect(tagSpy).toHaveBeenCalledWith("s1", {
        segment_id: 1,
        token_start: 1,
        token_end: 2,
        surface: "good",
        type: "project",
      }),
    );
  });

  it("lets you tag a word you just edited (not only pre-highlighted ones)", async () => {
    const editSpy = vi
      .spyOn(refine, "editToken")
      .mockResolvedValue({ decision: "promote", v2: makeDraft() });
    const tagSpy = vi.spyOn(refine, "tagEntity").mockResolvedValue({ v2: makeDraft() });
    renderEditor();
    fireEvent.click(screen.getByText("good")); // select a plain, unhighlighted word
    const input = document.querySelector('[data-token-input="1"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Goodall" } });
    const sel = document.querySelector('[data-tag="1-1"]') as HTMLSelectElement;
    fireEvent.change(sel, { target: { value: "person" } });
    // edit is committed AND the tag applied — both with the edited surface
    await waitFor(() => expect(editSpy).toHaveBeenCalledWith("s1", 1, 1, "Goodall"));
    await waitFor(() =>
      expect(tagSpy).toHaveBeenCalledWith("s1", {
        segment_id: 1,
        token_start: 1,
        token_end: 2,
        surface: "Goodall",
        type: "person",
      }),
    );
  });

  it("shows speaker suggestions and assigns on chip click (F2c/FE-4)", async () => {
    const assignSpy = vi.spyOn(refine, "assignSpeaker").mockResolvedValue({ v2: makeDraft() });
    const { onChange } = renderEditor();
    fireEvent.click(screen.getByText("speaker_2")); // open assign for segment 1
    await waitFor(() => expect(document.querySelector('[data-speaker-chip="Carol"]')).toBeTruthy());
    fireEvent.click(document.querySelector('[data-speaker-chip="Carol"]')!);
    expect(assignSpy).toHaveBeenCalledWith("s1", 1, "Carol");
    expect(onChange).toHaveBeenCalled();
  });

  it("surfaces a save error and re-syncs from the server when a write fails (A)", async () => {
    vi.spyOn(refine, "editToken").mockRejectedValue(new Error("500"));
    const getSpy = vi.spyOn(refine, "getDraft").mockResolvedValue(makeDraft());
    renderEditor();
    fireEvent.click(screen.getByText("DStack"));
    const input = document.querySelector('[data-token-input="3"]') as HTMLInputElement;
    fireEvent.change(input, { target: { value: "Dstack" } });
    fireEvent.keyDown(input, { key: "Enter" });
    // the failure is shown (not swallowed) AND the view is re-synced from the server
    await waitFor(() => expect(screen.getByTestId("save-error")).toBeInTheDocument());
    expect(getSpy).toHaveBeenCalledWith("s1");
  });
});
