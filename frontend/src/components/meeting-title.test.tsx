import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { meetings } from "@/lib/api";

import { MeetingTitleHeading } from "./meeting-title";

describe("MeetingTitleHeading", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the title and no edit control for a non-owner", () => {
    render(
      <MeetingTitleHeading
        sessionId="s1"
        title="Board sync"
        summary="body"
        isOwner={false}
      />,
    );
    expect(screen.getByTestId("meeting-title")).toHaveTextContent("Board sync");
    expect(screen.queryByTestId("title-edit")).toBeNull();
  });

  it("falls back to the summary lead when there's no title", () => {
    render(
      <MeetingTitleHeading
        sessionId="s1"
        title={null}
        summary={"First line.\nSecond line."}
        isOwner={false}
      />,
    );
    expect(screen.getByTestId("meeting-title")).toHaveTextContent("First line");
  });

  it("owner can rename: PATCHes and reports the new title", async () => {
    const spy = vi
      .spyOn(meetings, "rename")
      .mockResolvedValue({ session_id: "s1", title: "New name", manual: true });
    const onRenamed = vi.fn();
    render(
      <MeetingTitleHeading
        sessionId="s1"
        title="Old name"
        summary="body"
        isOwner={true}
        onRenamed={onRenamed}
      />,
    );
    fireEvent.click(screen.getByTestId("title-edit"));
    const input = screen.getByTestId("title-input") as HTMLInputElement;
    // Seeds with the current explicit title.
    expect(input.value).toBe("Old name");
    fireEvent.change(input, { target: { value: "New name" } });
    fireEvent.click(screen.getByTestId("title-save"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("s1", "New name"));
    expect(onRenamed).toHaveBeenCalledWith("New name");
  });

  it("owner can clear the override (blank) → reverts to the auto title", async () => {
    const spy = vi
      .spyOn(meetings, "rename")
      .mockResolvedValue({ session_id: "s1", title: "Auto title", manual: false });
    const onRenamed = vi.fn();
    render(
      <MeetingTitleHeading
        sessionId="s1"
        title="Pinned"
        summary="body"
        isOwner={true}
        onRenamed={onRenamed}
      />,
    );
    fireEvent.click(screen.getByTestId("title-edit"));
    fireEvent.change(screen.getByTestId("title-input"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("title-save"));
    await waitFor(() => expect(spy).toHaveBeenCalledWith("s1", ""));
    expect(onRenamed).toHaveBeenCalledWith("Auto title");
  });
});
