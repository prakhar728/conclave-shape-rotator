import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { workspaces } from "@/lib/api";

import { UploadTranscriptButton } from "./upload-transcript";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

function openAndSubmit() {
  render(<UploadTranscriptButton workspaceId="ws1" />);
  fireEvent.click(screen.getByRole("button", { name: "Upload transcript" })); // open the modal (icon button, labelled)
  fireEvent.change(screen.getByPlaceholderText(/Ada Lovelace/), {
    target: { value: "Speaker  0:01\nhi" },
  });
  fireEvent.click(screen.getByText("Upload & process"));
}

describe("UploadTranscriptButton", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    push.mockReset();
  });

  it("shows 'Already imported' on a duplicate, does NOT navigate", async () => {
    vi.spyOn(workspaces, "uploadTranscript").mockResolvedValue({
      session_id: "dup1",
      is_processing: false,
      status: "duplicate",
      v2_status: "approved",
      approved_at: "2026-06-22T18:00:00Z",
    } as never);
    openAndSubmit();
    await waitFor(() =>
      expect(screen.getByTestId("duplicate-notice")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("duplicate-notice")).toHaveTextContent(/approved/i);
    expect(push).not.toHaveBeenCalled();
  });

  it("navigates to the meeting on a fresh upload (accepted)", async () => {
    vi.spyOn(workspaces, "uploadTranscript").mockResolvedValue({
      session_id: "new1",
      is_processing: true,
      status: "accepted",
    } as never);
    openAndSubmit();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/meeting/new1"));
    expect(screen.queryByTestId("duplicate-notice")).toBeNull();
  });
});
