import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { refine, type V2Debug } from "@/lib/api";

import { RefineDebugPanel } from "./refine-debug-panel";

const debugData: V2Debug = {
  status: "draft",
  insights_stale: true,
  segments: [{ speaker: "Alice", text: "we use Dstack" }],
  annotations: [{ surface: "Dstack", state: "known", type: "project", source: "user" }],
  vocab: [{ surface: "dstack", type: "project", provenance: "user" }],
  recent_corrections: [],
  trust_state: "gated",
  entity_count: 0,
  fact_count: 0,
};

describe("RefineDebugPanel", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("renders the backend trail re-fetched from the server", async () => {
    vi.spyOn(refine, "debug").mockResolvedValue(debugData);
    render(<RefineDebugPanel sessionId="s1" />);
    await waitFor(() => expect(screen.getByText(/Dstack/)).toBeInTheDocument());
    const panel = screen.getByTestId("debug-panel");
    expect(panel).toHaveTextContent("project");
    expect(panel).toHaveTextContent("draft");
    expect(panel).toHaveTextContent("trust");
  });

  it("re-fetches on Refresh click (proves it reads the server, not local state)", async () => {
    const spy = vi.spyOn(refine, "debug").mockResolvedValue(debugData);
    render(<RefineDebugPanel sessionId="s1" />);
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByTestId("debug-refresh"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
  });
});
