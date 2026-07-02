import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { workspaces } from "@/lib/api";

import { RecordingProvider, useRecording } from "./recording-provider";

// ── Mocked Web Audio / mic / WebSocket ────────────────────────────────────────
// The provider owns the mic MediaStream, an AudioContext + AudioWorkletNode, and
// the capture WebSocket. jsdom has none of these, so we install minimal fakes and
// capture the socket instance to drive its lifecycle callbacks from the test.

const trackStop = vi.fn();
const ctxClose = vi.fn();
const nodeDisconnect = vi.fn();
const wsSend = vi.fn();
const wsClose = vi.fn();

class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  url: string;
  binaryType = "";
  readyState = 1; // pretend already-open so send()/stop() see OPEN
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((e: { code: number }) => void) | null = null;
  send = wsSend;
  close = wsClose;
  static instances: MockWebSocket[] = [];
  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }
}

/** The most-recently constructed capture socket (drive its callbacks from tests). */
function lastSock(): MockWebSocket {
  return MockWebSocket.instances[MockWebSocket.instances.length - 1];
}

class MockAudioContext {
  destination = {};
  audioWorklet = { addModule: vi.fn(async () => {}) };
  close = ctxClose;
  createGain() {
    return { gain: { value: 0 }, connect: (x: unknown) => x };
  }
  createMediaStreamSource() {
    return { connect: (x: unknown) => x };
  }
  createAnalyser() {
    return {
      fftSize: 0,
      smoothingTimeConstant: 0,
      frequencyBinCount: 64,
      getByteFrequencyData: () => {},
      connect: (x: unknown) => x,
    };
  }
}

class MockAudioWorkletNode {
  port: { onmessage: ((e: { data: ArrayBuffer }) => void) | null } = {
    onmessage: null,
  };
  disconnect = nodeDisconnect;
  connect(x: unknown) {
    return x;
  }
}

function Harness() {
  const rec = useRecording();
  return (
    <div>
      <span data-testid="status">{rec.recording?.status ?? "idle"}</span>
      <span data-testid="segs">{rec.recording?.segs.length ?? 0}</span>
      <span data-testid="error">{rec.recording?.error ?? ""}</span>
      <button onClick={() => rec.start("ws1", { storeAudio: true })}>start</button>
      <button
        onClick={() => rec.start("ws1", { agenda: "focus me", storeAudio: false })}
      >
        start-agenda
      </button>
      <button onClick={() => rec.stop()}>stop</button>
      <button onClick={() => rec.cancel()}>cancel</button>
    </div>
  );
}

function renderProvider() {
  return render(
    <RecordingProvider>
      <Harness />
    </RecordingProvider>,
  );
}

/** Click "start" and wait until the capture WebSocket has been constructed. */
async function startAndConnect() {
  fireEvent.click(screen.getByText("start"));
  await waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));
  act(() => lastSock().onopen?.());
}

beforeEach(() => {
  vi.restoreAllMocks();
  [trackStop, ctxClose, nodeDisconnect, wsSend, wsClose].forEach((m) =>
    m.mockReset(),
  );
  MockWebSocket.instances = [];
  Object.defineProperty(globalThis.navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: trackStop }] })),
    },
  });
  (globalThis as unknown as { AudioContext: unknown }).AudioContext =
    MockAudioContext;
  (globalThis as unknown as { AudioWorkletNode: unknown }).AudioWorkletNode =
    MockAudioWorkletNode;
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = MockWebSocket;
  globalThis.URL.createObjectURL = vi.fn(() => "blob:worklet");
  vi.spyOn(workspaces, "recordAgenda").mockResolvedValue(undefined as never);
});

describe("RecordingProvider", () => {
  it("goes idle → starting → recording once the WS opens", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("start"));
    expect(screen.getByTestId("status").textContent).toBe("starting");
    await waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));
    act(() => lastSock().onopen?.());
    expect(screen.getByTestId("status").textContent).toBe("recording");
  });

  it("appends live segments arriving over the WS", async () => {
    renderProvider();
    await startAndConnect();
    act(() =>
      lastSock().onmessage?.({
        data: JSON.stringify({ start: 0, end: 1.2, speaker: "S0", text: "hi" }),
      }),
    );
    expect(screen.getByTestId("segs").textContent).toBe("1");
  });

  it("MUTATION TARGET — cancel aborts WITHOUT finalizing and fully tears down (no leak)", async () => {
    renderProvider();
    await startAndConnect();
    expect(screen.getByTestId("status").textContent).toBe("recording");

    fireEvent.click(screen.getByText("cancel"));

    // Cancel must NOT send the empty end-frame — that is stop's meeting-end signal
    // and would push a canceled recording into the transcription pipeline.
    expect(wsSend).not.toHaveBeenCalledWith(expect.any(ArrayBuffer));
    // Instead it closes with the dedicated abort code so capture skips finalize…
    expect(wsClose).toHaveBeenCalledWith(4001, "canceled");
    // …and every transport handle is released — this is what the mutation-audit
    // breaks (skip a close/stop → these go RED).
    expect(trackStop).toHaveBeenCalled();
    expect(ctxClose).toHaveBeenCalled();
    expect(screen.getByTestId("status").textContent).toBe("idle");
  });

  it("on the finalize `done` message → status done + torn down", async () => {
    renderProvider();
    await startAndConnect();
    act(() => lastSock().onmessage?.({ data: JSON.stringify({ type: "done" }) }));
    expect(screen.getByTestId("status").textContent).toBe("done");
    expect(trackStop).toHaveBeenCalled();
    expect(ctxClose).toHaveBeenCalled();
  });

  it("a WS 1008 close surfaces the bad-token reject as an error", async () => {
    renderProvider();
    fireEvent.click(screen.getByText("start"));
    await waitFor(() => expect(MockWebSocket.instances.length).toBeGreaterThan(0));
    act(() => lastSock().onclose?.({ code: 1008 }));
    expect(screen.getByTestId("status").textContent).toBe("error");
    expect(screen.getByTestId("error").textContent).toMatch(/token/i);
  });

  it("stashes the agenda (Task #12) only when one was typed", async () => {
    renderProvider();
    // With an agenda → recordAgenda called with the uid + trimmed text.
    fireEvent.click(screen.getByText("start-agenda"));
    await waitFor(() =>
      expect(workspaces.recordAgenda).toHaveBeenCalledWith("ws1", {
        uid: expect.stringMatching(/^inperson-/),
        agenda: "focus me",
      }),
    );
  });

  it("does NOT stash an agenda when none was typed", async () => {
    renderProvider();
    await startAndConnect();
    expect(workspaces.recordAgenda).not.toHaveBeenCalled();
  });
});
