/**
 * /workspace/[id]/members — owner-only workspace membership management (Task #32).
 *
 * Invite by email, see current members + pending invites, and remove members.
 * Non-owners get 403 from the backend (owner-only manage, §0b-C); we surface that
 * as a clean message. The invitee joins when they accept the emailed link, or
 * automatically on their first sign-in (invites are hydrated by email).
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  auth,
  workspaces,
  type MeResponse,
  type WorkspaceInvite,
  type WorkspaceMember,
} from "@/lib/api";

export default function MembersPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [members, setMembers] = useState<WorkspaceMember[] | null>(null);
  const [invites, setInvites] = useState<WorkspaceInvite[]>([]);
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [meResp, list] = await Promise.all([
          auth.me(),
          workspaces.listMembers(id),
        ]);
        if (cancelled) return;
        setMe(meResp);
        setMembers(list.members);
        setInvites(list.invites);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        if (err instanceof ApiError && err.status === 403) {
          setError("Only the workspace owner can manage members.");
          return;
        }
        if (err instanceof ApiError && err.status === 404) {
          setError("Workspace not found or you don't have access.");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, router]);

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await workspaces.inviteMember(id, email.trim());
      setInvites((prev) => [r.invite, ...prev.filter((i) => i.email !== r.invite.email)]);
      setNotice(`Invited ${r.invite.email}.`);
      setEmail("");
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("That person is already a member.");
      } else if (err instanceof ApiError && err.status === 422) {
        setError("Enter a valid email address.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to invite");
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleRemove(memberUserId: string) {
    setBusy(true);
    setError(null);
    try {
      await workspaces.removeMember(id, memberUserId);
      setMembers((prev) => (prev ?? []).filter((m) => m.user_id !== memberUserId));
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setError("You can't remove the last owner.");
      } else {
        setError(err instanceof Error ? err.message : "Failed to remove");
      }
    } finally {
      setBusy(false);
    }
  }

  if (error && members === null) {
    return (
      <PageError message={error}>
        <Link
          href={`/workspace/${id}`}
          className="mt-3 inline-block text-xs text-muted-foreground hover:text-foreground"
        >
          Back to workspace
        </Link>
      </PageError>
    );
  }
  if (!me || members === null) return <PageLoading />;

  return (
    <AppShell user={me.user}>
      <main className="w-full px-6 py-10 md:px-8">
        <div className="mb-8">
          <Link
            href={`/workspace/${id}`}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            ← Workspace
          </Link>
          <h1 className="mt-2 text-2xl font-bold tracking-tight md:text-3xl">
            Members
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Invite people to this workspace. They see only the meetings you share.
          </p>
        </div>

        <form onSubmit={handleInvite} className="mb-8 flex flex-wrap items-center gap-2">
          <Input
            type="email"
            placeholder="teammate@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={busy}
            className="min-w-[14rem] flex-1"
          />
          <Button type="submit" disabled={busy || !email.trim()}>
            Invite
          </Button>
        </form>

        {notice ? <p className="mb-4 text-xs text-muted-foreground">{notice}</p> : null}
        {error ? <p className="mb-4 text-xs text-destructive">{error}</p> : null}

        <section>
          <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-muted-foreground">
            Members
          </h2>
          <ul className="flex flex-col gap-1">
            {members.map((m) => (
              <li
                key={m.user_id}
                className="flex items-center justify-between gap-3 rounded-none border border-border px-3 py-2 text-sm"
              >
                <span>
                  {m.email ?? m.user_id}
                  <span className="ml-2 text-xs capitalize text-muted-foreground">
                    {m.role}
                  </span>
                </span>
                {m.user_id !== me.user.id ? (
                  <button
                    type="button"
                    onClick={() => handleRemove(m.user_id)}
                    disabled={busy}
                    className="text-xs text-destructive hover:underline disabled:opacity-50"
                  >
                    Remove
                  </button>
                ) : (
                  <span className="text-xs text-muted-foreground">You</span>
                )}
              </li>
            ))}
          </ul>
        </section>

        {invites.length > 0 ? (
          <section className="mt-8">
            <h2 className="mb-3 text-xs font-bold uppercase tracking-widest text-muted-foreground">
              Pending invites
            </h2>
            <ul className="flex flex-col gap-1">
              {invites.map((i) => (
                <li
                  key={i.id}
                  className="flex items-center justify-between gap-3 rounded-none border border-dashed border-border px-3 py-2 text-sm text-muted-foreground"
                >
                  <span>{i.email}</span>
                  <span className="text-xs">invited</span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </main>
    </AppShell>
  );
}
