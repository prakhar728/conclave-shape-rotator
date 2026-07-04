# Port-from-OS spec — in-person UI features to add to the Conclave web frontend

Features built in **Shape Rotator OS** (`apps/os` in-person recording tab) that the
Conclave **web frontend** does **not** have yet. Each is self-contained and portable.

> **Already in the web app — do NOT re-build these:**
> `speakerLabel()` ("Speaker N" normalization, `lib/speakerLabel.ts`), click-to-tag on the
> speaker label (`transcript-panel.tsx` P4 + `speaker-tag-form.tsx`), the waveform audio
> player + `computePeaks` (`meeting-audio-player.tsx`), and Task-#37 turn coalescing.
> The gaps below are what's genuinely missing.

---

## 1. Deterministic per-speaker colors (color hashing) — **HIGH VALUE**

**What:** every speaker gets a stable, distinct, bright color derived from their label —
so the transcript scans like a chat and you instantly see who's who.

**Web gap:** the transcript renders `speakerLabel(turn.speaker)` in a single accent color.
No per-speaker color anywhere.

**Algorithm (the load-bearing part).** Normalize the label first (reuse `speakerLabel`),
then spread hues by the **golden angle** off the speaker number — a plain `hash % 360`
clusters consecutive speakers into near-identical hues (observed: "Speaker 0/1/2" → all
green). Golden-angle guarantees separation.

```ts
// speakerColor.ts  — deterministic bright colour per speaker
export function speakerColor(label: string): string {
  const s = speakerLabel(label);                 // "speaker0" | "0" | "Speaker 0" → "Speaker 0"
  const m = s.match(/^Speaker (\d+)$/);
  let hue: number;
  if (m) {
    hue = (20 + parseInt(m[1], 10) * 137.508) % 360;   // golden-angle spread; +20 keeps 0 off pure red
  } else {
    // resolved names / odd labels → FNV-1a hash + avalanche → hue
    let h = 2166136261;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    h ^= h >>> 13; h = Math.imul(h, 0x5bd1e995); h ^= h >>> 15;
    hue = (h >>> 0) % 360;
  }
  return `hsl(${Math.round(hue)}, 78%, 64%)`;     // fixed S/L → always bright + legible on dark
}
```

Result: Speaker 0 → orange, 1 → green, 2 → purple, 3 → lime, 4 → blue, 5 → pink.

**Apply:** color the speaker label `<span style={{ color: speakerColor(turn.speaker) }}>`
in each transcript turn, and the speaker tag rows. **Normalize before hashing** so
`speaker0` (live) and `0` (post-pass) get the *same* color across live + final views.

---

## 2. Color-coded waveform — "speaker frequency" in the audio — **HIGH VALUE**

**What:** the audio player's waveform bars are **tinted by whoever is speaking at that
moment**. One glance shows the conversation's rhythm and who dominated.

**Web gap:** `meeting-audio-player.tsx` already decodes peaks (`computePeaks`) but draws them
monochrome (`bg-foreground` played / `bg-muted` unplayed). Only the color is missing.

**Implementation:** keep the existing peaks. For bar `i`, its time is
`t = (i / peaks.length) * duration`; find the segment active at `t` and tint the bar with
`speakerColor(segment.speaker)`. Played bars full-opacity, unplayed dimmed.

```ts
function speakerColorAt(t: number, segs: {start: number; speaker: string}[]): string {
  let cur = null;
  for (const s of segs) { if (s.start <= t) cur = s; else break; }   // segs sorted by start
  return cur ? speakerColor(cur.speaker) : "var(--muted)";
}

// in the peaks.map(...) render:
const t = (i / peaks.length) * duration;
const played = (i + 0.5) / peaks.length <= frac;
<div style={{
  height: `${Math.max(8, p * 100)}%`,
  background: speakerColorAt(t, segments),
  opacity: played ? 1 : 0.28,
}} />
```

**Requires:** pass the meeting's `segments` (with `start` + `speaker`) into
`MeetingAudioPlayer` as a prop. (Also nice: the OS uses ~140 bars for finer detail.)

---

## 3. Pause / resume recording — **MEDIUM VALUE**

**What:** pause mid-recording and resume seamlessly — the paused span is simply **not
recorded** (no dead air; timestamps stay continuous).

**Web gap:** the web recorder (`record-meeting.tsx` / `recording-provider.tsx`) has no
pause/resume.

**Implementation:** a `paused` flag. While paused: (a) **don't send PCM frames** to the
diart WebSocket (drop them in the worklet→socket forward), and (b) **freeze the elapsed
timer**. Resume flips it back. The WebSocket stays open the whole time (no reconnect).
Add a Pause/Resume button; show "paused" state (stop the pulsing live dot).

---

## 4. Speaker dedup / merge by normalized label — **ROBUSTNESS**

**What:** when the backend emits **mixed labels for one person** (diart `speaker1` +
DiariZen `1` in the same authoritative transcript), group speakers by their normalized
display name and treat a group as **resolved if ANY raw variant is resolved** — so a
recognized speaker never *also* shows a stray "please tag me" row.

**Web gap:** likely present (same backend). Verify the speaker/tag list: if it keys off raw
labels, a recognized person can appear twice.

**Note:** the real fix is **backend-side** — the reconcile should emit one consistent label
per speaker in the authoritative transcript. This UI merge is a safety net until then.

---

## 5. One-click quick-record + hotkey — **OPTIONAL / UX**

The OS adds a Conclave-logo FAB and `Option+R` that jump straight into recording with no
agenda. The web could add a keyboard shortcut / prominent quick-start for the same "hit
record and go" flow.

---

## Summary

| # | Feature | Web today | Effort | Value |
|---|---------|-----------|--------|-------|
| 1 | Per-speaker color hashing (golden-angle) | none | S | High |
| 2 | Color-coded waveform (speaker frequency) | monochrome | S–M | High |
| 3 | Pause / resume recording | none | M | Medium |
| 4 | Speaker dedup by normalized label | maybe buggy | S | Robustness |
| 5 | Quick-record + hotkey | full recorder only | S | Optional |

**Reference implementation:** `apps/os/src/renderer/inperson-record.js` in the
shape-rotator-os repo — `speakerColor`, `speakerColorAt`, `computePeaks`/`buildWaveform`,
`fmtSpeaker`, `pauseToggle`, and the `speakersHTML` dedup are all there in ~vanilla JS,
directly translatable to the React/TS components above.
