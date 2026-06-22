"use client";

import type { V2Annotation, V2Draft } from "@/lib/api";

import { tokenTint } from "./token-tints";

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

export function RefineEditor({ draft }: { draft: V2Draft }) {
  return (
    <div data-testid="refine-editor" className="space-y-5">
      {draft.segments.map((seg) => {
        const states = statesForSegment(draft.annotations, seg.segment_id);
        return (
          <div key={seg.segment_id} className="rounded-md border border-border p-3">
            <div className="mb-1 text-xs font-bold uppercase tracking-wide text-muted-foreground">
              {seg.speaker_name ?? seg.speaker_label}
            </div>
            <p className="leading-7">
              {seg.tokens.map((tok, i) => {
                const state = states.get(i);
                return (
                  <span
                    key={i}
                    data-token={i}
                    data-segment={seg.segment_id}
                    data-state={state ?? ""}
                    className={`tok rounded px-0.5 ${tokenTint(state)}`}
                  >
                    {tok}{" "}
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
