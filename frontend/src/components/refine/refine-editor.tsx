"use client";

import { useEffect, useRef, useState } from "react";

import { SpeakerTagForm } from "@/components/speaker-tag-form";
import { meetings as meetingsApi, refine, type V2Annotation, type V2Draft } from "@/lib/api";

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
  // Owner + workspace → enables the VFTE name+email speaker tagging (same consent
  // path as the meeting transcript page). `resolvedSpeakers` seeds the label→name
  // overlay so already-confirmed identities render in the editor.
  workspaceId?: string | null;
  canTag?: boolean;
  resolvedSpeakers?: Record<string, unknown>;
};

export function RefineEditor({
  draft,
  sessionId,
  onDraftChange,
  workspaceId = null,
  canTag = false,
  resolvedSpeakers,
}: Props) {
  // The single SELECTED token. Clicking ANY word selects it and opens an inline panel
  // (edit + tag) — so tagging is available on every word (including ones you just
  // edited), and nothing clutters the text until a word is actually selected.
  const [selected, setSelected] = useState<{ seg: number; tok: number } | null>(null);
  const [editValue, setEditValue] = useState<string>("");
  const [vocabHints, setVocabHints] = useState<string[]>([]);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [assigning, setAssigning] = useState<number | null>(null);
  const [speakerNames, setSpeakerNames] = useState<string[]>([]);
  const [saveError, setSaveError] = useState<string | null>(null);
  // VFTE speaker tagging: label→identity overlay (seeded from the meeting), the
  // awaiting-confirm map, and the tag form's busy/error — mirrors transcript-panel.
  const [resolved, setResolved] = useState<Record<string, unknown>>(resolvedSpeakers ?? {});
  const [pending, setPending] = useState<Record<string, string>>({});
  const [tagBusy, setTagBusy] = useState(false);
  const [tagErr, setTagErr] = useState<string | null>(null);
  const taggable = Boolean(canTag && workspaceId);

  useEffect(() => {
    if (resolvedSpeakers) setResolved(resolvedSpeakers);
  }, [resolvedSpeakers]);

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

  // Display name precedence: a manual v2 assignment wins; else the VFTE-resolved
  // identity for this label; else the raw diarizer label.
  const displayName = (seg: V2Draft["segments"][number]): string =>
    seg.speaker_name ??
    (resolved[seg.speaker_label] as { name?: string } | undefined)?.name ??
    seg.speaker_label;

  // Tag a whole speaker (by label) with name+email → VFTE consent binding. Confirmed
  // self/dev tags flip the name in place; tagging someone else is "pending" until they
  // confirm on their consent dashboard — identical to the meeting transcript page.
  async function submitTag(label: string, name: string, email: string) {
    if (!workspaceId) return;
    setTagBusy(true);
    setTagErr(null);
    try {
      const res = await meetingsApi.tagSpeaker(workspaceId, sessionId, { label, name, email });
      setAssigning(null);
      if (res.status === "confirmed") {
        setResolved((r) => ({ ...r, [label]: { ...(r[label] as object), name: res.name ?? name } }));
        setPending((p) => {
          const next = { ...p };
          delete next[label];
          return next;
        });
      } else {
        setPending((p) => ({ ...p, [label]: name }));
      }
    } catch (e) {
      setTagErr(e instanceof Error ? e.message : "Tag failed");
    } finally {
      setTagBusy(false);
    }
  }

  const tokenText = (seg: number, tok: number): string =>
    draft.segments.find((s) => s.segment_id === seg)?.tokens[tok] ?? "";

  // Reset edit value and hints when a new token is selected.
  // Placed after tokenText so the closure captures the current definition.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (selected) {
      setEditValue(tokenText(selected.seg, selected.tok));
    }
    setVocabHints([]);
    if (debounceRef.current) clearTimeout(debounceRef.current);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  // Commit a (possibly edited) token and optionally tag it in ONE sequential write, so
  // the tag sees the edited text and neither clobbers the other. Local-first: update
  // the rendered draft immediately, fire the server write, reconcile when it lands.
  function commitToken(seg: number, tok: number, text: string, tag?: string) {
    setSelected(null);
    const changed = text !== tokenText(seg, tok);
    if (!changed && !tag) return;
    if (changed) {
      onDraftChange({
        ...draft,
        insights_stale: true,
        segments: draft.segments.map((s) =>
          s.segment_id === seg
            ? { ...s, tokens: s.tokens.map((t, i) => (i === tok ? text : t)) }
            : s,
        ),
      });
    }
    let p: Promise<{ v2: V2Draft } | null> = changed
      ? refine.editToken(sessionId, seg, tok, text)
      : Promise.resolve(null);
    if (tag) {
      p = p.then(() =>
        refine.tagEntity(sessionId, {
          segment_id: seg,
          token_start: tok,
          token_end: tok + 1,
          surface: text,
          type: tag,
        }),
      );
    }
    p.then((r) => r && _ok(r.v2)).catch(_onWriteError);
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
            <div className="mb-1 flex items-center gap-2">
              <button
                data-speaker={seg.segment_id}
                onClick={() => setAssigning(assigning === seg.segment_id ? null : seg.segment_id)}
                className="text-xs font-bold uppercase tracking-wide text-muted-foreground underline-offset-2 hover:underline"
              >
                {displayName(seg)}
              </button>
              {pending[seg.speaker_label] ? (
                <span className="rounded-full border border-amber-500/60 px-2 py-0.5 text-[0.65rem] text-amber-600">
                  pending: {pending[seg.speaker_label]}
                </span>
              ) : null}
            </div>

            {assigning === seg.segment_id && (
              <div data-testid={`speaker-assign-${seg.segment_id}`} className="mb-2 space-y-2">
                <div className="flex flex-wrap gap-1">
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
                {taggable ? (
                  <SpeakerTagForm
                    label={seg.speaker_label}
                    busy={tagBusy}
                    err={tagErr}
                    onCancel={() => setAssigning(null)}
                    onSubmit={submitTag}
                  />
                ) : null}
              </div>
            )}

            <p className="leading-7">
              {seg.tokens.map((tok, i) => {
                const isSelected = selected?.seg === seg.segment_id && selected.tok === i;
                if (isSelected) {
                  // Inline panel for the selected word: edit (input) + tag (any word).
                  return (
                    <span
                      key={i}
                      data-token-edit={i}
                      className="relative mx-0.5 inline-flex items-baseline gap-1 rounded bg-accent/50 px-1 align-baseline ring-1 ring-foreground/30"
                      onBlur={(e) => {
                        // Only close/commit when focus leaves the WHOLE panel — moving
                        // between the input, the tag menu, and the vocab dropdown must not dismiss it.
                        if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
                        commitToken(seg.segment_id, i, editValue);
                      }}
                    >
                      <input
                        ref={inputRef}
                        autoFocus
                        value={editValue}
                        data-token-input={i}
                        className="w-24 rounded border border-foreground px-1 text-sm"
                        onChange={(e) => {
                          const val = e.target.value;
                          setEditValue(val);
                          if (debounceRef.current) clearTimeout(debounceRef.current);
                          if (!val) {
                            setVocabHints([]);
                            return;
                          }
                          debounceRef.current = setTimeout(() => {
                            refine
                              .vocabSuggestions(val)
                              .then((r) => setVocabHints(r.vocab.slice(0, 8)))
                              .catch(() => {});
                          }, 150);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") commitToken(seg.segment_id, i, editValue);
                          if (e.key === "Escape") setSelected(null);
                        }}
                      />
                      {vocabHints.length > 0 && (
                        <span
                          data-testid="vocab-suggestions"
                          className="absolute left-0 top-full z-10 mt-0.5 flex flex-col rounded border border-border bg-background shadow"
                        >
                          {vocabHints.map((term) => (
                            <button
                              key={term}
                              data-vocab-option={term}
                              type="button"
                              className="px-2 py-0.5 text-left text-sm hover:bg-accent"
                              onMouseDown={(e) => {
                                // Prevent blur from firing before click is handled.
                                e.preventDefault();
                              }}
                              onClick={() => {
                                setEditValue(term);
                                setVocabHints([]);
                                inputRef.current?.focus();
                              }}
                            >
                              {term}
                            </button>
                          ))}
                        </span>
                      )}
                      <select
                        data-tag={`${seg.segment_id}-${i}`}
                        defaultValue=""
                        onChange={(e) => {
                          if (!e.target.value) return;
                          commitToken(seg.segment_id, i, editValue, e.target.value);
                        }}
                        className="rounded border border-dashed border-border text-[10px] text-muted-foreground"
                      >
                        <option value="">tag…</option>
                        {ENTITY_TYPES.map((t) => (
                          <option key={t} value={t}>
                            {t}
                          </option>
                        ))}
                      </select>
                    </span>
                  );
                }
                const state = states.get(i);
                return (
                  <span key={i} className="inline-flex items-baseline">
                    <span
                      data-token={i}
                      data-segment={seg.segment_id}
                      data-state={state ?? ""}
                      onClick={() => setSelected({ seg: seg.segment_id, tok: i })}
                      className={`tok cursor-pointer rounded px-0.5 ${tokenTint(state)}`}
                    >
                      {tok}
                    </span>{" "}
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
