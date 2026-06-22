/**
 * /meeting/[id]/refine — the transcript-refinement editor (Part 1).
 *
 * NEW additive route; the read-only /meeting/[id] view is untouched. Fetches the
 * editable v2 draft (server-side owner-gated) and renders the token editor.
 * Per-user — not collaborative.
 */
"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { use, useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { RefineEditor } from "@/components/refine/refine-editor";
import { ApiError, auth, refine, type MeResponse, type V2Draft } from "@/lib/api";

export default function RefinePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [draft, setDraft] = useState<V2Draft | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [meResp, d] = await Promise.all([auth.me(), refine.getDraft(id)]);
        if (cancelled) return;
        setMe(meResp);
        setDraft(d);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError) {
          if (err.status === 401) {
            router.push("/login");
            return;
          }
          if (err.status === 403) {
            setError("You don't have access to this transcript.");
            return;
          }
          if (err.status === 404) {
            setError("No draft to review for this meeting yet.");
            return;
          }
        }
        setError(err instanceof Error ? err.message : "Failed to load the draft");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, router]);

  if (error) {
    return (
      <PageError message={error}>
        <Link href={`/meeting/${id}`} className="text-sm underline">
          Back to meeting
        </Link>
      </PageError>
    );
  }
  if (!me || !draft) return <PageLoading />;

  return (
    <AppShell user={me.user}>
      <main className="mx-auto max-w-3xl px-6 py-10">
        <div className="mb-6">
          <Link href={`/meeting/${id}`} className="text-xs text-muted-foreground">
            ← Back to meeting
          </Link>
          <h1 className="mt-2 font-heading text-2xl font-black">Review transcript</h1>
          <p className="text-sm text-muted-foreground">
            Fix names and words, confirm entities, then approve.
          </p>
        </div>
        <RefineEditor draft={draft} sessionId={id} onDraftChange={setDraft} />
      </main>
    </AppShell>
  );
}
