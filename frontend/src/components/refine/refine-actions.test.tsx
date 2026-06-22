import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { refine, type V2Draft } from "@/lib/api";

import { RefineActions } from "./refine-actions";

function draft(overrides: Partial<V2Draft> = {}): V2Draft {
  return {
    session_id: "s1",
    status: "draft",
    approved_at: null,
    insights_stale: true,
    segments: [],
    annotations: [],
    ...overrides,
  };
}

describe("RefineActions", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("shows the stale badge when insights are stale (F3/FE-3)", () => {
    render(<RefineActions draft={draft()} sessionId="s1" onApproved={() => {}} />);
    expect(screen.getByTestId("stale-badge")).toBeInTheDocument();
  });

  it("hides the badge when insights are fresh", () => {
    render(<RefineActions draft={draft({ insights_stale: false })} sessionId="s1" onApproved={() => {}} />);
    expect(screen.queryByTestId("stale-badge")).toBeNull();
  });

  it("approves then calls onApproved (navigation)", async () => {
    const spy = vi.spyOn(refine, "approve").mockResolvedValue({ session_id: "s1", status: "approved" });
    const onApproved = vi.fn();
    render(<RefineActions draft={draft()} sessionId="s1" onApproved={onApproved} />);
    fireEvent.click(screen.getByTestId("approve-btn"));
    await waitFor(() => expect(onApproved).toHaveBeenCalled());
    expect(spy).toHaveBeenCalledWith("s1");
  });

  it("disables the button once approved", () => {
    render(<RefineActions draft={draft({ status: "approved" })} sessionId="s1" onApproved={() => {}} />);
    expect(screen.getByTestId("approve-btn")).toBeDisabled();
  });
});
