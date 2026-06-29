import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { shapeContrib } from "@/lib/api";

import { ContributeShapeOS } from "./contribute-shapeos";

describe("ContributeShapeOS (Task #20)", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("disables the button until v2 is approved", () => {
    render(<ContributeShapeOS sessionId="s1" approved={false} />);
    expect(screen.getByTestId("contribute-shapeos-btn")).toBeDisabled();
  });

  it("enables the button once approved", () => {
    render(<ContributeShapeOS sessionId="s1" approved={true} />);
    expect(screen.getByTestId("contribute-shapeos-btn")).toBeEnabled();
  });

  it("requires a confirm step before posting (consent/opt-in)", async () => {
    const spy = vi.spyOn(shapeContrib, "contribute");
    render(<ContributeShapeOS sessionId="s1" approved={true} />);
    fireEvent.click(screen.getByTestId("contribute-shapeos-btn"));
    // Nothing posted yet — the confirm panel appears first.
    expect(spy).not.toHaveBeenCalled();
    expect(screen.getByTestId("contribute-shapeos-confirm")).toBeInTheDocument();
  });

  it("posts on confirm and shows the inbox ✓ receipt", async () => {
    const spy = vi.spyOn(shapeContrib, "contribute").mockResolvedValue({
      inbox: { ok: true, status: "ok", parts: 1, http_statuses: [201] },
    });
    render(<ContributeShapeOS sessionId="s1" approved={true} />);
    fireEvent.click(screen.getByTestId("contribute-shapeos-btn"));
    fireEvent.click(screen.getByTestId("contribute-shapeos-confirm-btn"));
    await waitFor(() => expect(screen.getByTestId("shapeos-posted")).toBeInTheDocument());
    expect(spy).toHaveBeenCalledWith("s1");
  });

  it("surfaces a server-side rejection without a false receipt", async () => {
    vi.spyOn(shapeContrib, "contribute").mockResolvedValue({
      inbox: { ok: false, status: "rejected", parts: 0, http_statuses: [422] },
    });
    render(<ContributeShapeOS sessionId="s1" approved={true} />);
    fireEvent.click(screen.getByTestId("contribute-shapeos-btn"));
    fireEvent.click(screen.getByTestId("contribute-shapeos-confirm-btn"));
    await waitFor(() =>
      expect(screen.getByText(/rejected the transcript/i)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("shapeos-posted")).toBeNull();
  });
});
