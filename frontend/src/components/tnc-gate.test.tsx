import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { auth, tnc } from "@/lib/api";

import { TncGate } from "./tnc-gate";

let pathname = "/dashboard";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

const _me = (needs: boolean) => ({
  user: {
    id: "u1",
    email: "a@x.com",
    display_name: null,
    created_at: "2026-06-30",
    tnc_needs_acceptance: needs,
  },
  workspace: null,
});

const _tnc = {
  version: "tnc-v0",
  text: "Terms & Conditions — Early Access (pre-production)\n- do not rely on it",
  accepted_at: null,
  accepted_version: null,
  needs_acceptance: true,
};

describe("TncGate", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    pathname = "/dashboard";
  });

  it("BLOCKS the app until the user accepts, then dismisses", async () => {
    vi.spyOn(auth, "me").mockResolvedValue(_me(true) as never);
    vi.spyOn(tnc, "get").mockResolvedValue(_tnc as never);
    const accept = vi
      .spyOn(tnc, "accept")
      .mockResolvedValue({ ..._tnc, needs_acceptance: false } as never);

    render(
      <TncGate>
        <div>app content</div>
      </TncGate>,
    );

    // The blocking dialog appears with the terms copy.
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText(/pre-production/)).toBeInTheDocument();

    fireEvent.click(screen.getByText("I accept"));

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(accept).toHaveBeenCalledWith("tnc-v0");
  });

  it("does NOT block when the user has already accepted", async () => {
    vi.spyOn(auth, "me").mockResolvedValue(_me(false) as never);
    const get = vi.spyOn(tnc, "get");

    render(
      <TncGate>
        <div>app content</div>
      </TncGate>,
    );

    await waitFor(() => expect(auth.me).toHaveBeenCalled());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(get).not.toHaveBeenCalled(); // no copy fetched when not needed
  });

  it("never gates the login screen (no me() probe)", async () => {
    pathname = "/login";
    const me = vi.spyOn(auth, "me");
    render(
      <TncGate>
        <div>login</div>
      </TncGate>,
    );
    await Promise.resolve();
    expect(me).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
