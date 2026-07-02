import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { meetings, type Meeting } from "@/lib/api";

import { FailedMeetingCard } from "./failed-meeting-card";

const meeting: Meeting = {
  session_id: "f1",
  date: "2026-07-02",
  source: "capture",
  summary: null,
  enrichment_state: "failed",
};

describe("FailedMeetingCard", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(() => {
    // @ts-expect-error — restore confirm between tests
    delete window.confirm;
  });

  it("shows the couldn't-generate-insights state with Retry + Delete", () => {
    render(<FailedMeetingCard meeting={meeting} onChanged={vi.fn()} />);
    expect(screen.getByTestId("failed-card")).toHaveTextContent(
      "Couldn’t generate insights",
    );
    expect(screen.getByTestId("failed-retry")).toBeInTheDocument();
    expect(screen.getByTestId("failed-delete")).toBeInTheDocument();
  });

  it("Retry re-enqueues enrich and refreshes", async () => {
    const spy = vi
      .spyOn(meetings, "retryEnrich")
      .mockResolvedValue({ session_id: "f1", status: "pending" });
    const onChanged = vi.fn();
    render(<FailedMeetingCard meeting={meeting} onChanged={onChanged} />);
    fireEvent.click(screen.getByTestId("failed-retry"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("f1"));
    expect(onChanged).toHaveBeenCalled();
  });

  it("Delete confirms, deletes, and refreshes", async () => {
    window.confirm = vi.fn(() => true);
    const spy = vi
      .spyOn(meetings, "delete")
      .mockResolvedValue({ deleted: true, session_id: "f1" });
    const onChanged = vi.fn();
    render(<FailedMeetingCard meeting={meeting} onChanged={onChanged} />);
    fireEvent.click(screen.getByTestId("failed-delete"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("f1"));
    expect(onChanged).toHaveBeenCalled();
  });

  it("Delete does nothing when the confirm is cancelled", () => {
    window.confirm = vi.fn(() => false);
    const spy = vi.spyOn(meetings, "delete");
    render(<FailedMeetingCard meeting={meeting} onChanged={vi.fn()} />);
    fireEvent.click(screen.getByTestId("failed-delete"));
    expect(spy).not.toHaveBeenCalled();
  });
});
