/**
 * Task #37 — speaker-turn coalescing on the client (mirrors `transcripts/turns.py`).
 *
 * Coalesce consecutive same-speaker spans into one turn — used by the live page
 * (over the streaming spans, so the open turn GROWS) and the refine editor (to group
 * v2 segments under one speaker header). The read view uses the server-computed
 * `turns` directly. Keep this in lockstep with the Python.
 *
 * Projection only: a turn WRAPS its spans (`turn.spans`) so clips/edit/seek keep
 * operating on the underlying spans.
 */

/** Same-speaker gap (s) beyond which we insert a paragraph break inside the turn. */
export const PARAGRAPH_GAP_SEC = 10.0;

export type SpeakerKeyable = {
  speaker?: string | null;
  speaker_label?: string | null;
  speaker_name?: string | null;
  voiceprint_id?: string | null;
  proposed_name?: string | null;
};

/**
 * Stable merge key: resolved identity (voiceprint → confirmed name) wins so the same
 * person merges across different diarizer local labels; otherwise the raw local label
 * keeps two distinct unknowns apart. A `proposed_name` (unconsented) is NOT a key.
 */
export function speakerKey(seg: SpeakerKeyable): string {
  if (seg.voiceprint_id) return `vp:${seg.voiceprint_id}`;
  if (seg.speaker_name) return `name:${seg.speaker_name}`;
  return `local:${seg.speaker ?? seg.speaker_label ?? ""}`;
}

/** Consecutive runs of items sharing a key (the primitive both the editor + live use). */
export function groupConsecutive<T>(items: T[], keyOf: (t: T) => string): T[][] {
  const out: T[][] = [];
  let cur: T[] | null = null;
  let curKey: string | null = null;
  for (const it of items) {
    const k = keyOf(it);
    if (cur && k === curKey) {
      cur.push(it);
    } else {
      cur = [it];
      curKey = k;
      out.push(cur);
    }
  }
  return out;
}

type Span = SpeakerKeyable & { text?: string | null; start?: number | null; end?: number | null };

export type Turn<S extends Span> = {
  speaker?: string | null;
  speaker_name?: string | null;
  proposed_name?: string | null;
  voiceprint_id?: string | null;
  consented?: boolean | null;
  start: number | null;
  end: number | null;
  text: string;
  spans: S[];
};

/**
 * Full turn coalescing over time-ordered spans (live page). Empty/whitespace spans
 * never open or flip a turn — they're absorbed into the open turn (kept, `end`
 * extended). A big same-speaker gap inserts a paragraph break (still one turn).
 */
export function groupIntoTurns<S extends Span>(segments: S[]): Turn<S>[] {
  const turns: Turn<S>[] = [];
  let open: (Turn<S> & { _prevEnd: number | null }) | null = null;
  let openKey: string | null = null;

  for (const seg of segments) {
    const text = (seg.text ?? "").trim();
    if (!text) {
      if (open) {
        open.spans.push(seg);
        if (seg.end != null) open.end = seg.end;
      }
      continue;
    }
    const key = speakerKey(seg);
    if (open && key === openKey) {
      const gap =
        seg.start != null && open._prevEnd != null ? seg.start - open._prevEnd : null;
      const sep = gap != null && gap > PARAGRAPH_GAP_SEC ? "\n\n" : " ";
      open.text = open.text ? `${open.text}${sep}${text}` : text;
      open.spans.push(seg);
      if (seg.end != null) open.end = seg.end;
      open._prevEnd = seg.end ?? open._prevEnd;
      continue;
    }
    if (open) turns.push(strip(open));
    open = {
      speaker: seg.speaker ?? seg.speaker_label ?? null,
      speaker_name: seg.speaker_name ?? null,
      proposed_name: seg.proposed_name ?? null,
      voiceprint_id: seg.voiceprint_id ?? null,
      consented: (seg as { consented?: boolean | null }).consented ?? null,
      start: seg.start ?? null,
      end: seg.end ?? null,
      text,
      spans: [seg],
      _prevEnd: seg.end ?? null,
    };
    openKey = key;
  }
  if (open) turns.push(strip(open));
  return turns;
}

function strip<S extends Span>(t: Turn<S> & { _prevEnd: number | null }): Turn<S> {
  const { _prevEnd, ...rest } = t;
  void _prevEnd;
  return rest;
}
