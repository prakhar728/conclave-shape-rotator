import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, feedback, type FeedbackItem } from "@/lib/api";

import { FeedbackInbox } from "./feedback-inbox";

const ITEM: FeedbackItem = {
  id: "f1",
  user_id: "u1",
  user_email: "alice@example.com",
  workspace_id: "ws1",
  category: "bug",
  body: "it crashed on save",
  page_context: "/meeting/abc",
  created_at: "2026-06-29T12:00:00Z",
};

describe("FeedbackInbox", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders submitted feedback rows with submitter + page-context", async () => {
    vi.spyOn(feedback, "list").mockResolvedValue({
      items: [ITEM],
      total: 1,
      limit: 100,
      offset: 0,
    });
    render(<FeedbackInbox />);

    await waitFor(() =>
      expect(screen.getByTestId("feedback-inbox")).toBeInTheDocument(),
    );
    expect(screen.getByText("it crashed on save")).toBeInTheDocument();
    expect(screen.getByText("alice@example.com")).toBeInTheDocument();
    expect(screen.getByText("/meeting/abc")).toBeInTheDocument();
    expect(screen.getByText("1 total")).toBeInTheDocument();
  });

  it("shows an empty state when there is no feedback", async () => {
    vi.spyOn(feedback, "list").mockResolvedValue({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
    });
    render(<FeedbackInbox />);
    await waitFor(() =>
      expect(screen.getByTestId("feedback-empty")).toBeInTheDocument(),
    );
  });

  it("shows a forbidden notice on 403 (non-admin)", async () => {
    vi.spyOn(feedback, "list").mockRejectedValue(
      new ApiError(403, "admin access required", "403 admin access required"),
    );
    render(<FeedbackInbox />);
    await waitFor(() =>
      expect(screen.getByTestId("feedback-forbidden")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("feedback-inbox")).toBeNull();
  });
});
