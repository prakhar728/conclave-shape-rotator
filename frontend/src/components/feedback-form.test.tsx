import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { feedback } from "@/lib/api";

import { FeedbackForm } from "./feedback-form";

describe("FeedbackForm", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("submits category + body + page_context and shows the success state", async () => {
    const spy = vi
      .spyOn(feedback, "submit")
      .mockResolvedValue({ id: "fb1", created_at: "2026-06-29T00:00:00Z" });

    render(<FeedbackForm pageContext="/meeting/abc" workspaceId="ws1" />);

    fireEvent.change(screen.getByLabelText("Feedback type"), {
      target: { value: "bug" },
    });
    fireEvent.change(screen.getByLabelText("Feedback body"), {
      target: { value: "  it crashed  " },
    });
    fireEvent.click(screen.getByText("Send feedback"));

    await waitFor(() =>
      expect(screen.getByTestId("feedback-success")).toBeInTheDocument(),
    );
    expect(spy).toHaveBeenCalledWith({
      category: "bug",
      body: "it crashed", // trimmed
      page_context: "/meeting/abc",
      workspace_id: "ws1",
    });
  });

  it("disables submit and does NOT call the API on an empty body", () => {
    const spy = vi.spyOn(feedback, "submit");
    render(<FeedbackForm />);

    const button = screen.getByText("Send feedback");
    expect(button).toBeDisabled();
    // Clicking a disabled button is a no-op, and a whitespace body stays blocked.
    fireEvent.change(screen.getByLabelText("Feedback body"), {
      target: { value: "   " },
    });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(spy).not.toHaveBeenCalled();
  });

  it("shows an error and stays on the form when the API fails", async () => {
    vi.spyOn(feedback, "submit").mockRejectedValue(new Error("boom"));
    render(<FeedbackForm />);

    fireEvent.change(screen.getByLabelText("Feedback body"), {
      target: { value: "something" },
    });
    fireEvent.click(screen.getByText("Send feedback"));

    await waitFor(() => expect(screen.getByText("boom")).toBeInTheDocument());
    expect(screen.queryByTestId("feedback-success")).toBeNull();
  });

  it("passes null page_context when omitted", async () => {
    const spy = vi
      .spyOn(feedback, "submit")
      .mockResolvedValue({ id: "fb2", created_at: "2026-06-29T00:00:00Z" });
    render(<FeedbackForm />);

    fireEvent.change(screen.getByLabelText("Feedback body"), {
      target: { value: "no context here" },
    });
    fireEvent.click(screen.getByText("Send feedback"));

    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(spy.mock.calls[0][0]).toMatchObject({
      category: "feature",
      body: "no context here",
      page_context: null,
      workspace_id: null,
    });
  });
});
