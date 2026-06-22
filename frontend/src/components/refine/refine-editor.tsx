"use client";

import { useEffect, useState } from "react";

import { refine, type V2Annotation, type V2Draft } from "@/lib/api";

import { tokenTint } from "./token-tints";

const ENTITY_TYPES = ["person", "project", "tech", "affiliation", "topic"];

/** Map each token index in a segment to its annotation state (known wins overlaps). */
function statesForSegment(annotations: V2Annotation[], segmentId: number): Map<number, string> {
  const m = new Map<number, string>();
  for (const a of annotations) {
    if (a.span.segment_id !== segmentId) continue;
    for (let i = a.span.token_start; i < a.span.token_end; i++) {
      const existing = m.get(i);
      if (!existing || a.state === "known") m.set(i, a.state);
    }
  }
  return m;
}

type Props = {
  draft: V2Draft;
  sessionId: string;
  onDraftChange: (d: V2Draft) => void;
};

export function RefineEditor({ draft, sessionId, onDraftChange }: Props) {
  const [editing, setEditing] = useState<{ seg: number; tok: number } | null>(null);
  const [assigning, setAssigning] = useState<number | null>(null);
  const [speakerNames, setSpeakerNames] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    refine
      .speakerSuggestions(sessionId)
      .then((r) => !cancelled && setSpeakerNames(r.speakers))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  // Reconcile with the server's returned v2 on success; on FAILURE surface it and
  // re-sync from the server (so the UI never shows an edit that didn't persist).
  const _ok = (v2: V2Draft) => {
    setSaveError(null);
    onDraftChange(v2);
  };
  const _onWriteError = () => {
    setSaveError(
      "Couldn't save your last change — it may not have persisted. Refreshed from the server.",
    );
    refine.getDraft(sessionId).then(onDraftChange).catch(() => {});
  };

  // All writes are LOCAL-FIRST: update the rendered draft immediately, fire the
  // server write in the background, reconcile (or surface the error) when it lands.
  function applyTokenEdit(seg: number, tok: number, text: string) {
    onDraftChange({
      ...draft,
      insights_stale: true,
      segments: draft.segments.map((s) =>
        s.segment_id === seg
          ? { ...s, tokens: s.tokens.map((t, i) => (i === tok ? text : t)) }
          : s,
      ),
    });
    setEditing(null);
    refine.editToken(sessionId, seg, tok, text).then((r) => _ok(r.v2)).catch(_onWriteError);
  }

  function tagToken(seg: number, tok: number, surface: string, type: string) {
    refine
      .tagEntity(sessionId, { segment_id: seg, token_start: tok, token_end: tok + 1, surface, type })
      .then((r) => _ok(r.v2))
      .catch(_onWriteError);
  }

  function assignSpeaker(seg: number, name: string) {
    onDraftChange({
      ...draft,
      insights_stale: true,
      segments: draft.segments.map((s) =>
        s.segment_id === seg ? { ...s, speaker_name: name } : s,
      ),
    });
    setAssigning(null);
    refine.assignSpeaker(sessionId, seg, name).then((r) => _ok(r.v2)).catch(_onWriteError);
  }

  return (
    <div data-testid="refine-editor" className="space-y-5">
      {saveError ? (
        <div
          data-testid="save-error"
          className="flex items-center justify-between rounded border border-destructive bg-destructive/10 px-3 py-2 text-xs text-destructive"
        >
          <span>{saveError}</span>
          <button onClick={() => setSaveError(null)} className="ml-2 underline">
            dismiss
          </button>
        </div>
      ) : null}
      {draft.segments.map((seg) => {
        const states = statesForSegment(draft.annotations, seg.segment_id);
        return (
          <div key={seg.segment_id} className="rounded-md border border-border p-3">
            <button
              data-speaker={seg.segment_id}
              onClick={() => setAssigning(assigning === seg.segment_id ? null : seg.segment_id)}
              className="mb-1 text-xs font-bold uppercase tracking-wide text-muted-foreground underline-offset-2 hover:underline"
            >
              {seg.speaker_name ?? seg.speaker_label}
            </button>

            {assigning === seg.segment_id && (
              <div data-testid={`speaker-assign-${seg.segment_id}`} className="mb-2 flex flex-wrap gap-1">
                {speakerNames.length === 0 ? (
                  <span className="text-xs text-muted-foreground">No suggestions yet</span>
                ) : (
                  speakerNames.map((name) => (
                    <button
                      key={name}
                      data-speaker-chip={name}
                      onClick={() => assignSpeaker(seg.segment_id, name)}
                      className="rounded-full border border-border px-2 py-0.5 text-xs hover:bg-accent"
                    >
                      {name}
                    </button>
                  ))
                )}
              </div>
            )}

            <p className="leading-7">
              {seg.tokens.map((tok, i) => {
                if (editing?.seg === seg.segment_id && editing.tok === i) {
                  return (
                    <input
                      key={i}
                      autoFocus
                      defaultValue={tok}
                      data-token-input={i}
                      className="rounded border border-foreground px-1 text-sm"
                      onKeyDown={(e) => {
                        if (e.key === "Enter")
                          applyTokenEdit(seg.segment_id, i, (e.target as HTMLInputElement).value);
                        if (e.key === "Escape") setEditing(null);
                      }}
                      onBlur={(e) => applyTokenEdit(seg.segment_id, i, e.target.value)}
                    />
                  );
                }
                const state = states.get(i);
                const taggable = state === "candidate" || state === "oov";
                return (
                  <span key={i} className="inline-flex items-baseline">
                    <span
                      data-token={i}
                      data-segment={seg.segment_id}
                      data-state={state ?? ""}
                      onClick={() => setEditing({ seg: seg.segment_id, tok: i })}
                      className={`tok cursor-text rounded px-0.5 ${tokenTint(state)}`}
                    >
                      {tok}
                    </span>
                    {taggable && (
                      <select
                        data-tag={`${seg.segment_id}-${i}`}
                        defaultValue=""
                        onChange={(e) => {
                          if (e.target.value) tagToken(seg.segment_id, i, tok, e.target.value);
                        }}
                        className="ml-0.5 rounded border border-dashed border-border text-[10px] text-muted-foreground"
                      >
                        <option value="">tag…</option>
                        {ENTITY_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    )}
                    {" "}
                  </span>
                );
              })}
            </p>
          </div>
        );
      })}
    </div>
  );
}
