import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { dataExport } from "@/lib/api";

import { DataExportControl } from "./data-export-control";

describe("DataExportControl", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("audio OFF → synchronous download, no queue job", () => {
    const start = vi.spyOn(dataExport, "startJob");
    const clicks: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push(this.href);
    });

    render(<DataExportControl />);
    fireEvent.click(screen.getByRole("button", { name: "Download my data" }));

    expect(start).not.toHaveBeenCalled(); // never touches the async queue
    expect(clicks.some((h) => h.endsWith("/api/users/me/export"))).toBe(true);
  });

  it("audio ON → rides the queue, polls, then downloads when done", async () => {
    vi.useFakeTimers();
    vi.spyOn(dataExport, "startJob").mockResolvedValue({
      export_id: "exp_1",
      status: "pending",
      include_audio: true,
    });
    const statusSpy = vi
      .spyOn(dataExport, "jobStatus")
      .mockResolvedValueOnce({
        export_id: "exp_1",
        status: "processing",
        include_audio: true,
      })
      .mockResolvedValueOnce({
        export_id: "exp_1",
        status: "done",
        include_audio: true,
      });
    const clicks: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicks.push(this.href);
    });

    render(<DataExportControl />);
    fireEvent.click(screen.getByLabelText(/Include audio recordings/));
    fireEvent.click(screen.getByRole("button", { name: "Download my data" }));

    await vi.waitFor(() => expect(dataExport.startJob).toHaveBeenCalledWith(true));

    // Two poll ticks: processing → done.
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(2000);

    expect(statusSpy).toHaveBeenCalledTimes(2);
    expect(clicks.some((h) => h.endsWith("/api/users/me/export/jobs/exp_1/download"))).toBe(
      true,
    );
  });
});
