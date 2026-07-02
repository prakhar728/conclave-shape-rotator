/**
 * Task #30 — audio player + URL helper.
 */
import { createRef } from "react";

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { meetings } from "@/lib/api";

import {
  MeetingAudioPlayer,
  type MeetingAudioPlayerHandle,
} from "./meeting-audio-player";

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

describe("MeetingAudioPlayer — seek handle + availability (Task #41)", () => {
  it("seekTo(seconds) sets currentTime and starts playback", () => {
    const play = vi
      .spyOn(window.HTMLMediaElement.prototype, "play")
      .mockResolvedValue(undefined);
    const ref = createRef<MeetingAudioPlayerHandle>();
    const { container } = render(
      <MeetingAudioPlayer ref={ref} sessionId="s9" storeAudio={true} />,
    );
    const audio = container.querySelector("audio") as HTMLAudioElement;
    ref.current?.seekTo(42);
    expect(audio.currentTime).toBe(42);
    expect(play).toHaveBeenCalled();
    play.mockRestore();
  });

  it("clamps a negative seek to 0", () => {
    vi.spyOn(window.HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const ref = createRef<MeetingAudioPlayerHandle>();
    const { container } = render(
      <MeetingAudioPlayer ref={ref} sessionId="s9" storeAudio={true} />,
    );
    const audio = container.querySelector("audio") as HTMLAudioElement;
    ref.current?.seekTo(-10);
    expect(audio.currentTime).toBe(0);
  });

  it("reports availability true once <audio> metadata loads", () => {
    const onAvail = vi.fn();
    const { container } = render(
      <MeetingAudioPlayer
        sessionId="s9"
        storeAudio={true}
        onAvailabilityChange={onAvail}
      />,
    );
    const audio = container.querySelector("audio") as HTMLAudioElement;
    fireEvent.loadedMetadata(audio);
    expect(onAvail).toHaveBeenCalledWith(true);
  });

  it("reports availability false when the meeting opted out of audio", () => {
    const onAvail = vi.fn();
    render(
      <MeetingAudioPlayer
        sessionId="s9"
        storeAudio={false}
        onAvailabilityChange={onAvail}
      />,
    );
    expect(onAvail).toHaveBeenCalledWith(false);
  });

  it("seekTo is a safe no-op when the player has self-hidden (no audio element)", () => {
    const ref = createRef<MeetingAudioPlayerHandle>();
    render(<MeetingAudioPlayer ref={ref} sessionId="s9" storeAudio={false} />);
    expect(() => ref.current?.seekTo(5)).not.toThrow();
  });
});
