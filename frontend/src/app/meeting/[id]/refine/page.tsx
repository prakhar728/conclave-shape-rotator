/**
 * /meeting/[id]/refine — the transcript-refinement editor (Part 1).
 *
 * NEW additive route; the read-only /meeting/[id] view is untouched. Fetches the
 * editable v2 draft (server-side owner-gated) and renders the token editor.
 * Per-user — not collaborative.
 */
"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { use, useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { RefineActions } from "@/components/refine/refine-actions";
import { RefineDebugPanel } from "@/components/refine/refine-debug-panel";
import { RefineEditor } from "@/components/refine/refine-editor";
import { useRefineDraft } from "@/components/refine/use-refine-draft";
import { meetings, refine, type MeetingView } from "@/lib/api";

export default function RefinePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const searchParams = useSearchParams();
  const debug = searchParams.get("debug") === "1";
  const { me, draft, setDraft, error, preparing } = useRefineDraft(id);
  const [refreshKey, setRefreshKey] = useState(0);
  // Meeting context for owner-only speaker tagging (workspace + ownership +
  // already-resolved identities). Best-effort: tagging just stays hidden if it fails.
  const [meeting, setMeeting] = useState<MeetingView | null>(null);
  useEffect(() => {
    meetings.get(id).then(setMeeting).catch(() => {});
  }, [id]);

  if (error) {
    return (
      <PageError message={error}>
        <Link href={`/meeting/${id}`} className="text-sm underline">
          Back to meeting
        </Link>
      </PageError>
    );
  }
  if (preparing) return <PageLoading label="Preparing your transcript…" />;
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
        <RefineEditor
          draft={draft}
          sessionId={id}
          workspaceId={meeting?.workspace_id ?? null}
          canTag={Boolean(meeting?.is_owner)}
          resolvedSpeakers={meeting?.resolved_speakers}
          onDraftChange={(d) => {
            setDraft(d);
            setRefreshKey((k) => k + 1); // nudge the debug panel to re-read the server
          }}
        />
        <RefineActions
          draft={draft}
          sessionId={id}
          onApproved={() => {
            // Stay here and show the APPROVED, corrected transcript. (The meeting
            // view still renders raw_diarization — see transcript-refine-issues.md #2.)
            refine.getDraft(id).then(setDraft).catch(() => {});
          }}
        />
        {debug ? <RefineDebugPanel sessionId={id} refreshKey={refreshKey} /> : null}
      </main>
    </AppShell>
  );
}
