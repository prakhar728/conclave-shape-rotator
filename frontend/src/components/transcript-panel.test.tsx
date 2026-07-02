/**
 * Task #3 — host-facing "Proposed: <name>" confirm affordance in the transcript
 * panel. A recognized-but-not-yet-consented speaker gets a chip with Confirm/Edit
 * that opens the (email-collecting) tag form pre-filled with the suggested name;
 * a consented recognition renders plainly, and an unrecognized speaker stays the
 * anonymous "Speaker N" label.
 */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { meetings, type TranscriptSegment } from "@/lib/api";

import { TranscriptPanel } from "./transcript-panel";

function seg(over: Partial<TranscriptSegment>): TranscriptSegment {
  return {
    speaker: "Speaker 0",
    speaker_name: null,
    proposed_name: null,
    voiceprint_id: null,
    consented: null,
    text: "hello there",
    start: null,
    end: null,
    ...over,
  };
}

function mount(segments: TranscriptSegment[]) {
  vi.spyOn(meetings, "transcript").mockResolvedValue({
    session_id: "s1",
    segment_count: segments.length,
    segments,
  });
  return render(
    <TranscriptPanel
      sessionId="s1"
      canView={true}
      canTag={true}
      workspaceId="ws1"
    />,
  );
}

describe("TranscriptPanel — proposed name", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a 'Proposed:' chip with Confirm/Edit for a recognized-but-unconsented speaker", async () => {
    mount([seg({ proposed_name: "Ada Lovelace", consented: false })]);
    const chip = await screen.findByTestId("proposed-chip");
    expect(chip).toHaveTextContent("Proposed: Ada Lovelace");
    expect(screen.getByText("Confirm")).toBeInTheDocument();
    expect(screen.getByText("Edit")).toBeInTheDocument();
  });

  it("renders a consented name plainly with no proposed chip", async () => {
    mount([seg({ speaker_name: "Grace Hopper", consented: true })]);
    await screen.findByText("Grace Hopper");
    expect(screen.queryByTestId("proposed-chip")).toBeNull();
  });

  it("renders the anonymous label when there is no name or proposal", async () => {
    mount([seg({})]);
    await screen.findByText("Speaker 0");
    expect(screen.queryByTestId("proposed-chip")).toBeNull();
  });

  it("Confirm opens the tag form pre-filled with the proposed name (email still required)", async () => {
    mount([seg({ proposed_name: "Ada Lovelace", consented: false })]);
    await screen.findByTestId("proposed-chip");
    fireEvent.click(screen.getByText("Confirm"));
    await waitFor(() =>
      expect(screen.getByTestId("speaker-tag-form")).toBeInTheDocument(),
    );
    const nameInput = screen.getByPlaceholderText("Full name") as HTMLInputElement;
    expect(nameInput.value).toBe("Ada Lovelace");
  });
});

describe("TranscriptPanel — click-to-seek (Task #41)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  function mountWithSeek(
    segments: TranscriptSegment[],
    onSeek?: (s: number) => void,
  ) {
    vi.spyOn(meetings, "transcript").mockResolvedValue({
      session_id: "s1",
      segment_count: segments.length,
      segments,
    });
    return render(
      <TranscriptPanel
        sessionId="s1"
        canView={true}
        canTag={false}
        workspaceId="ws1"
        onSeek={onSeek}
      />,
    );
  }

  it("clicking a segment seeks to its start when audio is available", async () => {
    const onSeek = vi.fn();
    mountWithSeek([seg({ text: "first line", start: 12.5, end: 15 })], onSeek);
    const row = await screen.findByTestId("seek-segment");
    fireEvent.click(row);
    expect(onSeek).toHaveBeenCalledWith(12.5);
  });

  it("does NOT seek while the user has a text selection (drag-select preserved)", async () => {
    const onSeek = vi.fn();
    mountWithSeek([seg({ text: "selectable text", start: 3, end: 5 })], onSeek);
    const row = await screen.findByTestId("seek-segment");
    const orig = window.getSelection;
    // Simulate an active selection.
    window.getSelection = (() =>
      ({ toString: () => "selectable" }) as unknown as Selection);
    fireEvent.click(row);
    window.getSelection = orig;
    expect(onSeek).not.toHaveBeenCalled();
  });

  it("renders no seek affordance when there is no audio (onSeek undefined)", async () => {
    mountWithSeek([seg({ text: "no audio", start: 1, end: 2 })], undefined);
    await screen.findByText("no audio");
    expect(screen.queryByTestId("seek-segment")).toBeNull();
  });

  it("renders no seek affordance for a segment without a start time", async () => {
    const onSeek = vi.fn();
    mountWithSeek([seg({ text: "no timestamp", start: null, end: null })], onSeek);
    await screen.findByText("no timestamp");
    expect(screen.queryByTestId("seek-segment")).toBeNull();
  });
});
