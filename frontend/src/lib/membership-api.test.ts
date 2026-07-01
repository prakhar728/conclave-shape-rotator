import { beforeEach, describe, expect, it, vi } from "vitest";

import { meetingOwner, workspaces } from "./api";

function mockFetch(body: unknown = {}) {
  const f = vi.fn().mockResolvedValue({ ok: true, json: async () => body });
  vi.stubGlobal("fetch", f);
  return f;
}

describe("Task #32 workspace membership api client", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("inviteMember POSTs email + role to the members endpoint", async () => {
    const f = mockFetch({ invite: { id: "inv_1", email: "b@x.com", role: "member" } });
    await workspaces.inviteMember("ws1", "b@x.com");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/workspaces/ws1/members");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ email: "b@x.com", role: "member" });
  });

  it("listMembers GETs the members endpoint", async () => {
    const f = mockFetch({ members: [], invites: [] });
    await workspaces.listMembers("ws1");
    expect(f.mock.calls[0][0]).toBe("/api/workspaces/ws1/members");
  });

  it("removeMember DELETEs the member", async () => {
    const f = mockFetch({ ok: true, removed: "usr_2" });
    await workspaces.removeMember("ws1", "usr_2");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/workspaces/ws1/members/usr_2");
    expect(init.method).toBe("DELETE");
  });

  it("acceptInvite POSTs the token", async () => {
    const f = mockFetch({ workspace: { id: "ws1" }, role: "member" });
    await workspaces.acceptInvite("tok123");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/workspaces/accept-invite");
    expect(JSON.parse(init.body)).toEqual({ token: "tok123" });
  });

  it("recordRecorder POSTs the uid (no identity in body)", async () => {
    const f = mockFetch(null);
    await workspaces.recordRecorder("ws1", { uid: "inperson-1" });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/workspaces/ws1/record/recorder");
    expect(JSON.parse(init.body)).toEqual({ uid: "inperson-1" });
  });

  it("shareWorkspace POSTs the share flag", async () => {
    const f = mockFetch({ ok: true, shared_to_workspace: true });
    await meetingOwner.shareWorkspace("s1", true);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/meetings/s1/share-workspace");
    expect(JSON.parse(init.body)).toEqual({ share: true });
  });

  it("shareMember POSTs the member email", async () => {
    const f = mockFetch({ ok: true, email: "m@x.com" });
    await meetingOwner.shareMember("s1", "m@x.com");
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/meetings/s1/share-member");
    expect(JSON.parse(init.body)).toEqual({ email: "m@x.com" });
  });

  it("setOwnerOnly POSTs the lock flag", async () => {
    const f = mockFetch({ ok: true, owner_only: true });
    await meetingOwner.setOwnerOnly("s1", true);
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/meetings/s1/owner-only");
    expect(JSON.parse(init.body)).toEqual({ locked: true });
  });
});
