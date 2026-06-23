import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, auth, refine } from "@/lib/api";

import { useRefineDraft } from "./use-refine-draft";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

const DRAFT = {
  session_id: "s1",
  status: "draft",
  segments: [],
  annotations: [],
  approved_at: null,
  insights_stale: false,
};
const ME = { user: { id: "u" } };

describe("useRefineDraft", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(auth, "me").mockResolvedValue(ME as never);
  });

  it("renders the draft when it's ready", async () => {
    vi.spyOn(refine, "getDraft").mockResolvedValue(DRAFT as never);
    const { result } = renderHook(() => useRefineDraft("s1"));
    await waitFor(() => expect(result.current.draft).toEqual(DRAFT));
    expect(result.current.preparing).toBe(false);
  });

  it("shows 'preparing' (polls) instead of dead-ending on a 404 (P0)", async () => {
    // The draft isn't ready yet → keep polling, surface a loader, not an error.
    vi.spyOn(refine, "getDraft").mockRejectedValue(new ApiError(404, "no draft", "404"));
    const { result, unmount } = renderHook(() => useRefineDraft("s1"));
    await waitFor(() => expect(result.current.preparing).toBe(true));
    expect(result.current.error).toBeNull();
    expect(result.current.draft).toBeNull();
    unmount(); // clears the pending poll timer
  });

  it("surfaces a 403 as an error (not preparing)", async () => {
    vi.spyOn(refine, "getDraft").mockRejectedValue(new ApiError(403, "no access", "403"));
    const { result } = renderHook(() => useRefineDraft("s1"));
    await waitFor(() => expect(result.current.error).toBeTruthy());
    expect(result.current.preparing).toBe(false);
  });
});
