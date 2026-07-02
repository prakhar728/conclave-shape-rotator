import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── next/navigation ──────────────────────────────────────────────────────────
const replace = vi.fn();
const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push }),
  usePathname: () => "/recording/inperson-1",
}));

// ── AppShell chrome — render children only ────────────────────────────────────
vi.mock("@/components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  PageHeader: ({ title }: { title: React.ReactNode }) => <h1>{title}</h1>,
}));

// ── RecordingProvider — drive the owned/not-owned state per test ──────────────
const stop = vi.fn();
const cancel = vi.fn();
const clear = vi.fn();
let mockRecording: unknown = null;
vi.mock("@/components/recording-provider", () => ({
  useRecording: () => ({ recording: mockRecording, stop, cancel, clear }),
  fmt: (s: number) => `00:${String(s).padStart(2, "0")}`,
}));

// ── SSE (backend live tail) — capture the EventSource so we can push frames ────
class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  close = vi.fn();
  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }
}

// ── Resolve use(params) synchronously (jsdom has no concurrent runtime) ────────
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof React>();
  const cache = new WeakMap<Promise<unknown>, unknown>();
  return {
    ...actual,
    use: <T,>(value: T | Promise<T>): T => {
      if (value && typeof (value as Promise<T>).then === "function") {
        const p = value as Promise<T>;
        if (!cache.has(p)) {
          p.then((v) => cache.set(p, v));
          throw p;
        }
        return cache.get(p) as T;
      }
      return actual.use(value as never);
    },
  };
});

import RecordingPage from "./page";
import { auth, live } from "@/lib/api";

const ME = { user: { id: "u1", email: "a@b.com" }, workspace: null };

function renderPage() {
  return render(<RecordingPage params={Promise.resolve({ id: "inperson-1" })} />);
}

beforeEach(() => {
  replace.mockReset();
  push.mockReset();
  stop.mockReset();
  cancel.mockReset();
  clear.mockReset();
  mockRecording = null;
  MockEventSource.instances = [];
  (globalThis as unknown as { EventSource: unknown }).EventSource =
    MockEventSource;
  vi.spyOn(auth, "me").mockResolvedValue(ME as never);
  vi.spyOn(live, "open").mockImplementation(
    (id: string) => new MockEventSource(live.streamUrl(id)) as unknown as EventSource,
  );
});

describe("RecordingPage", () => {
  it("owner view: shows Recording + segments + a working Stop, and does NOT open SSE", async () => {
    mockRecording = {
      id: "inperson-1",
      workspaceId: "ws1",
      status: "recording",
      seconds: 5,
      segs: [{ start: 0, end: 1, speaker: "S0", text: "hi" }],
      error: null,
      storeAudio: true,
    };
    renderPage();
    // The AIVoiceInput spinner is both the recording indicator and the stop
    // control (no separate "RECORDING" headline anymore).
    await waitFor(() =>
      expect(screen.getByLabelText("Stop recording")).toBeInTheDocument(),
    );
    expect(screen.getByText("hi")).toBeInTheDocument();
    // Owner drives from the provider WS — no duplicate SSE subscription.
    expect(live.open).not.toHaveBeenCalled();

    fireEvent.click(screen.getByLabelText("Stop recording"));
    expect(stop).toHaveBeenCalledTimes(1);
  });

  it("redirects to /meeting/[id] on the finalize `done` signal", async () => {
    mockRecording = {
      id: "inperson-1",
      workspaceId: "ws1",
      status: "done",
      seconds: 9,
      segs: [],
      error: null,
      storeAudio: true,
    };
    renderPage();
    await waitFor(() =>
      expect(replace).toHaveBeenCalledWith("/meeting/inperson-1"),
    );
    expect(clear).toHaveBeenCalled();
  });

  it("non-owner view (reload / 2nd viewer): opens SSE + shows the disconnected buffer", async () => {
    mockRecording = null; // provider doesn't hold this session
    renderPage();
    await waitFor(() => expect(auth.me).toHaveBeenCalled());
    // SSE fallback opened against the live tail.
    await waitFor(() => expect(live.open).toHaveBeenCalledWith("inperson-1"));
    expect(screen.getByText("Disconnected view")).toBeInTheDocument();

    // A buffered segment arriving over SSE renders.
    const es = MockEventSource.instances[0];
    expect(es).toBeDefined();
    es.onmessage?.({
      data: JSON.stringify({ start: 0, end: 2, speaker: "S1", text: "buffered" }),
    });
    await waitFor(() =>
      expect(screen.getByText("buffered")).toBeInTheDocument(),
    );
  });
});
