import { describe, expect, it } from "vitest";

import type { Meeting } from "@/lib/api";

import { lifecycleOf } from "./meetingLifecycle";

function m(over: Partial<Meeting>): Meeting {
  return { session_id: "s", date: "2026-07-02", source: "capture", summary: null, ...over };
}

describe("lifecycleOf", () => {
  it("prefers the server enrichment_state", () => {
    expect(lifecycleOf(m({ enrichment_state: "processing" }))).toBe("processing");
    expect(lifecycleOf(m({ enrichment_state: "failed" }))).toBe("failed");
    expect(lifecycleOf(m({ enrichment_state: "done" }))).toBe("done");
  });

  it("does not treat a failed meeting as done just because is_processing is false", () => {
    expect(lifecycleOf(m({ enrichment_state: "failed", is_processing: false }))).toBe(
      "failed",
    );
  });

  it("falls back to the legacy is_processing bool when enrichment_state is absent", () => {
    expect(lifecycleOf(m({ is_processing: true }))).toBe("processing");
    expect(lifecycleOf(m({ is_processing: false }))).toBe("done");
    expect(lifecycleOf(m({}))).toBe("done");
  });
});
