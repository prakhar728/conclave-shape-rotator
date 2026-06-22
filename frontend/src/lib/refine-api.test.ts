import { beforeEach, describe, expect, it, vi } from "vitest";

import { refine } from "./api";

function mockFetch(body: unknown = {}) {
  const f = vi.fn().mockResolvedValue({ ok: true, json: async () => body });
  vi.stubGlobal("fetch", f);
  return f;
}

describe("refine api client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("getDraft GETs the v2 path with the session cookie", async () => {
    const f = mockFetch({ session_id: "s1", status: "draft" });
    await refine.getDraft("s1");
    expect(f).toHaveBeenCalledWith(
      "/api/transcripts/sessions/s1/v2",
      expect.objectContaining({ credentials: "same-origin" }),
    );
  });

  it("editToken POSTs the right body", async () => {
    const f = mockFetch({ decision: "text", v2: {} });
    await refine.editToken("s1", 0, 3, "Dstack");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/transcripts/sessions/s1/v2/edit-token");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ segment_id: 0, token_idx: 3, new_text: "Dstack" });
  });

  it("tagEntity POSTs span + type", async () => {
    const f = mockFetch({ v2: {} });
    await refine.tagEntity("s1", { segment_id: 0, token_start: 3, token_end: 5, surface: "DStack protocol", type: "project" });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/transcripts/sessions/s1/v2/tag-entity");
    expect(JSON.parse(init.body)).toEqual({ segment_id: 0, token_start: 3, token_end: 5, surface: "DStack protocol", type: "project" });
  });

  it("assignSpeaker POSTs name", async () => {
    const f = mockFetch({ v2: {} });
    await refine.assignSpeaker("s1", 0, "Alice");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/transcripts/sessions/s1/v2/assign-speaker");
    expect(JSON.parse(init.body)).toEqual({ segment_id: 0, name: "Alice" });
  });

  it("approve POSTs", async () => {
    const f = mockFetch({ session_id: "s1", status: "approved" });
    await refine.approve("s1");
    expect(f.mock.calls[0][0]).toBe("/api/transcripts/sessions/s1/approve");
    expect(f.mock.calls[0][1].method).toBe("POST");
  });

  it("suggestions GET the right paths", async () => {
    const f = mockFetch({ speakers: ["Alice"], vocab: ["datadog"] });
    await refine.speakerSuggestions("s1");
    expect(f.mock.calls[0][0]).toBe("/api/transcripts/sessions/s1/suggestions/speakers");
    await refine.vocabSuggestions("da");
    expect(f.mock.calls[1][0]).toBe("/api/transcripts/suggestions/vocab?prefix=da");
  });
});
