# NO-SLOP-LIST

Rules that keep the Conclave frontend from looking AI-generated ("vibecoded").
Each is a **hard no** unless there is a real, specific reason. When you catch a
new kind of slop, add it here.

Canonical look: **clean + calm** — monochrome with cyber-green accents, flat
surfaces (no shadows), **softly rounded** (rounded-lg), **sentence case** (not
shouty all-caps), lighter weights, generous whitespace, hairline dividers.
Fonts: Inter / Space Grotesk / JetBrains Mono.

## Visual
1. **No box shadows.** None. No `shadow-sm/md/lg/xl/2xl`, no offset "brutalist"
   shadows (`shadow-[2px_2px_0px…]`), no glow, no soft drop shadows. Separate
   surfaces with a **hairline `border-border`** or a background-contrast change,
   never a shadow.
2. **Consistent soft rounding.** Cards/controls use `rounded-lg` (small
   things `rounded-md`); don't mix random radii. `rounded-full` only for true
   circles (status/pulse dots, spinners, avatars). Avoid oversized `rounded-3xl`.
2b. **Sentence case, never SHOUTY ALL-CAPS.** No `uppercase` headings/labels/
   nav. No `font-black` walls of caps. Titles are sentence case, normal weight.
3. **Tokens, not raw colors.** Use `--color-*` / signal tokens (`signal-warn`,
   `signal-entity`, `signal-positive`, `attested`, `destructive`). Never raw
   Tailwind palette literals (`bg-emerald-100`, `text-amber-600`, `bg-blue-500`).
4. **One type system.** Inter (sans) / Space Grotesk (headings) / JetBrains Mono.
   No new fonts, no serif drop-ins.
5. **No gradients / atmosphere effects** unless a real design calls for it. No
   dotted-grid canvases, no shimmer for shimmer's sake.

## Icons
6. **No random or decorative icons.** An icon must earn its place — nav, an
   action, or a status. Never an icon just to fill space or "look designed".
7. **lucide only.** One icon set. No second set, and **no emoji as UI** (no ✨,
   ✦, ▶ as buttons/labels).
8. **One icon per thing.** Don't pair an icon with another redundant icon or
   with text that says the same word.

## Copy
9. **No extra text.** No filler subtitles, no "Welcome to your dashboard", no
   explaining the obvious. Say it once, plainly.
10. **No em dashes (—).** They read as AI. Use periods, commas, or colons.
11. **No invented / marketing claims.** Never state a capability the product
    doesn't have. Trust claims especially must reflect reality — e.g. an
    "Attested" badge must come from a real attestation quote, never hardcoded.
12. **No redundant labels.** Don't repeat the section name on every row/chip.

## Structure
13. **No nested boxes.** No box inside a box inside a box. Never stack
    `border` + `shadow` + `bg` on the same element to make it "pop".
14. **No dead code / dead CSS.** Grep-confirm a class/utility is referenced
    before keeping it. Delete orphaned styles and unused imports.
15. **No stale design vocab** in comments or class names (Vantage, Emerald,
    Editorial-Vault, Enclave-Light). One name only: Motto Brutalist.
16. **Honest states.** Loading / empty / error / local states must reflect
    reality — local shows "local", not a fake "attested / verified" badge.

## Process
17. Prefer removing over adding. If an element, icon, border, shadow, or line of
    copy isn't doing real work, delete it.
