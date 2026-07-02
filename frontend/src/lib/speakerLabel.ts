/**
 * Normalize a raw diarizer speaker label to a human "Speaker N".
 *
 * Different engines emit different formats for the SAME concept: diart uses
 * `speaker0`/`speaker1`, the DiariZen GPU post-pass uses bare `0`/`1`/`2`, and
 * some paths already produce `Speaker 0`. When no confirmed name exists we still
 * want one consistent, readable label instead of a cryptic bare `2`.
 *
 * Only applied to the RAW-label fallback — a confirmed `speaker_name` always wins
 * over this. A label that isn't a recognizable speaker index (e.g. an actual
 * name) is returned unchanged.
 */
export function speakerLabel(raw: string | null | undefined): string {
  const s = (raw ?? "").trim();
  if (!s) return "Speaker";
  // Trailing integer → "Speaker N" (covers "2", "speaker2", "Speaker 2", "spk_2").
  const m = s.match(/(\d+)\s*$/);
  if (m && /^(speaker|spk|s)?[\s_-]*\d+$/i.test(s)) {
    return `Speaker ${m[1]}`;
  }
  return s; // a real name or an unrecognized label — leave it alone
}
