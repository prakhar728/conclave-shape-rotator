import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { meetings, refine, type V2Draft } from "@/lib/api";

import { RefineEditor } from "./refine-editor";

function makeDraft(): V2Draft {
  return {
    session_id: "s1",
    status: "draft",
    approved_at: null,
    insights_stale: false,
    segments: [
      { segment_id: 0, speaker_label: "speaker_1", speaker_name: null, tokens: ["hello", "there"] },
      { segment_id: 1, speaker_label: "speaker_2", speaker_name: null, tokens: ["hi"] },
    ],
    annotations: [],
  };
}

function renderEditor(over?: { canTag?: boolean; resolvedSpeakers?: Record<string, unknown> }) {
  const onChange = vi.fn();
  return {
    onChange,
    ...render(
      <RefineEditor
        draft={makeDraft()}
        sessionId="s1"
        workspaceId="ws_1"
        canTag={over?.canTag ?? true}
        resolvedSpeakers={over?.resolvedSpeakers}
        onDraftChange={onChange}
      />,
    ),
  };
}

describe("RefineEditor — VFTE speaker tagging", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // suggestions stay empty here — tagging is the surface under test
    vi.spyOn(refine, "speakerSuggestions").mockResolvedValue({ speakers: [] });
  });

  it("owners get the name+email tag form when a speaker is opened", () => {
    renderEditor();
    fireEvent.click(screen.getByText("speaker_1"));
    expect(screen.getByTestId("speaker-tag-form")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Full name")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("email@company.com")).toBeInTheDocument();
  });

  it("non-owners get no tag form", () => {
    renderEditor({ canTag: false });
    fireEvent.click(screen.getByText("speaker_1"));
    expect(screen.queryByTestId("speaker-tag-form")).not.toBeInTheDocument();
  });

  it("a confirmed tag binds by label and flips the name in place", async () => {
    const spy = vi.spyOn(meetings, "tagSpeaker").mockResolvedValue({
      label: "speaker_1",
      voiceprint_id: "vp1",
      status: "confirmed",
      name: "Alice",
      proposal_id: null,
    });
    renderEditor();
    fireEvent.click(screen.getByText("speaker_1"));
    fireEvent.change(screen.getByPlaceholderText("Full name"), { target: { value: "Alice" } });
    fireEvent.change(screen.getByPlaceholderText("email@company.com"), {
      target: { value: "alice@x.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tag" }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("ws_1", "s1", {
        label: "speaker_1",
        name: "Alice",
        email: "alice@x.com",
      }),
    );
    expect(await screen.findByText("Alice")).toBeInTheDocument();
  });

  it("tagging someone else shows a pending badge", async () => {
    vi.spyOn(meetings, "tagSpeaker").mockResolvedValue({
      label: "speaker_1",
      voiceprint_id: "vp1",
      status: "pending",
      name: null,
      proposal_id: "p1",
    });
    renderEditor();
    fireEvent.click(screen.getByText("speaker_1"));
    fireEvent.change(screen.getByPlaceholderText("Full name"), { target: { value: "Bob" } });
    fireEvent.change(screen.getByPlaceholderText("email@company.com"), {
      target: { value: "bob@x.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tag" }));
    expect(await screen.findByText("pending: Bob")).toBeInTheDocument();
  });

  it("the email-transcript toggle threads email_transcript through tagSpeaker (Task #15)", async () => {
    const spy = vi.spyOn(meetings, "tagSpeaker").mockResolvedValue({
      label: "speaker_1",
      voiceprint_id: "vp1",
      status: "pending",
      name: null,
      proposal_id: "p1",
    });
    renderEditor();
    fireEvent.click(screen.getByText("speaker_1"));
    fireEvent.change(screen.getByPlaceholderText("Full name"), { target: { value: "Bob" } });
    fireEvent.change(screen.getByPlaceholderText("email@company.com"), {
      target: { value: "bob@x.com" },
    });
    // Opt in to also emailing the transcript link.
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Tag" }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("ws_1", "s1", {
        label: "speaker_1",
        name: "Bob",
        email: "bob@x.com",
        email_transcript: true,
      }),
    );
  });

  it("without checking the toggle, tagSpeaker omits email_transcript", async () => {
    const spy = vi.spyOn(meetings, "tagSpeaker").mockResolvedValue({
      label: "speaker_1",
      voiceprint_id: "vp1",
      status: "pending",
      name: null,
      proposal_id: "p1",
    });
    renderEditor();
    fireEvent.click(screen.getByText("speaker_1"));
    fireEvent.change(screen.getByPlaceholderText("Full name"), { target: { value: "Bob" } });
    fireEvent.change(screen.getByPlaceholderText("email@company.com"), {
      target: { value: "bob@x.com" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Tag" }));

    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith("ws_1", "s1", {
        label: "speaker_1",
        name: "Bob",
        email: "bob@x.com",
      }),
    );
  });

  it("renders an already-resolved identity from resolvedSpeakers", () => {
    renderEditor({ resolvedSpeakers: { speaker_2: { name: "Carol" } } });
    expect(screen.getByText("Carol")).toBeInTheDocument();
  });
});
