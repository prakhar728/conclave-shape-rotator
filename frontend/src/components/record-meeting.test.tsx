import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { workspaces } from "@/lib/api";

import { RecordMeetingButton } from "./record-meeting";
import { RecordingProvider } from "./recording-provider";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

// Minimal Web Audio / mic / WS fakes so start() → begin() doesn't throw when the
// dialog kicks off a session (we only assert the navigation here).
beforeEach(() => {
  push.mockReset();
  Object.defineProperty(globalThis.navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [] })) },
  });
  (globalThis as unknown as { AudioContext: unknown }).AudioContext = class {
    destination = {};
    audioWorklet = { addModule: vi.fn(async () => {}) };
    close() {}
    createGain() {
      return { gain: {}, connect: (x: unknown) => x };
    }
    createMediaStreamSource() {
      return { connect: (x: unknown) => x };
    }
  };
  (globalThis as unknown as { AudioWorkletNode: unknown }).AudioWorkletNode =
    class {
      port = {};
      connect(x: unknown) {
        return x;
      }
      disconnect() {}
    };
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = class {
    readyState = 0;
    binaryType = "";
    send() {}
    close() {}
  };
  globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
  vi.spyOn(workspaces, "recordAgenda").mockResolvedValue(undefined as never);
});

describe("RecordMeetingButton", () => {
  it("Start navigates to the dedicated /recording/[id] page", async () => {
    render(
      <RecordingProvider>
        <RecordMeetingButton workspaceId="ws1" />
      </RecordingProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Record meeting" })); // open the dialog (icon button, labelled)
    fireEvent.click(screen.getByText("Start recording"));
    await waitFor(() => expect(push).toHaveBeenCalledTimes(1));
    // The id is created before navigation and keys the route.
    expect(push.mock.calls[0][0]).toMatch(/^\/recording\/inperson-/);
  });
});
