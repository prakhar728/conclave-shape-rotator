/**
 * Task #30 — audio player + URL helper.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { meetings } from "@/lib/api";

import { MeetingAudioPlayer } from "./meeting-audio-player";

describe("meetings.audioUrl", () => {
  it("builds the full-recording path", () => {
    expect(meetings.audioUrl("s1")).toBe("/api/transcripts/sessions/s1/audio");
  });

  it("appends start/end for a segment clip", () => {
    expect(meetings.audioUrl("s1", { start: 0.25, end: 0.5 })).toBe(
      "/api/transcripts/sessions/s1/audio?start=0.25&end=0.5",
    );
  });

  it("url-encodes the session id", () => {
    expect(meetings.audioUrl("a/b")).toContain("sessions/a%2Fb/audio");
  });
});

describe("MeetingAudioPlayer", () => {
  it("renders an <audio> pointed at the decrypt-on-read endpoint", () => {
    const { container } = render(
      <MeetingAudioPlayer sessionId="s9" storeAudio={true} />,
    );
    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();
    expect(audio?.getAttribute("src")).toBe("/api/transcripts/sessions/s9/audio");
  });

  it("renders nothing when the meeting opted out of storing audio", () => {
    const { container } = render(
      <MeetingAudioPlayer sessionId="s9" storeAudio={false} />,
    );
    expect(container.querySelector("audio")).toBeNull();
  });

  it("shows a Delete control only for the owner", () => {
    const { rerender } = render(
      <MeetingAudioPlayer sessionId="s9" storeAudio={true} isOwner={true} />,
    );
    expect(screen.getByLabelText("Delete audio")).toBeTruthy();
    rerender(<MeetingAudioPlayer sessionId="s9" storeAudio={true} isOwner={false} />);
    expect(screen.queryByLabelText("Delete audio")).toBeNull();
  });
});
