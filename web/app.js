// Conclave cohort-context dashboard — Phase 1 (`IMPLEMENTATION_PLAN.md` §G13).
//
// Fetches the read API, renders one card per session, mounts a shape-ui
// glyph per card keyed on session_id. Per the §G13 critical note we use
// the per-card `mountShape(canvas, opts)` path, not the shared overlay
// — keeps each card self-contained and lets the renderer scale to
// however many sessions the cohort produces.
//
// F2 (§D.3): two views, hash-routed in one SPA:
//   - `` (no hash)            → grid of mini-preview cards
//   - `#/sessions/<id>`       → full per-meeting detail page
// Cards on the grid are themselves the link — clicking anywhere on the
// card pushes the hash. Detail view re-uses the same `signals_by_kind`
// section rendering as the (now removed) full-card view so there's a
// single helper to maintain.

import { mountShape } from "/dashboard/shape-ui/shape-canvas.js";

const SESSIONS_URL = "/transcripts/sessions";
const ROSTER_URL = "/transcripts/_cohort/roster";
const ME_ACTION_ITEMS_URL = "/transcripts/me/action-items";

// F3 (§D.1): viewer identity — demo-hardcoded picker. Stored under a
// stable localStorage key so the picker only appears once per browser.
// Cleared via the masthead "switch identity" link. There is no real
// auth here — Phase 1.5 swaps the picker for an auth callback and
// every API call site stays identical (the helpers below take care
// of threading whatever identity is current).
const VIEWER_STORAGE_KEY = "conclaveViewerId";

function getViewer() {
  try {
    const v = localStorage.getItem(VIEWER_STORAGE_KEY);
    return v && v.trim() ? v : null;
  } catch {
    return null;
  }
}

function setViewer(v) {
  try {
    // Empty string == "explicit anonymous" (distinct from key absent,
    // which means first visit and triggers the picker). Non-empty
    // strings are the picked record_id.
    localStorage.setItem(VIEWER_STORAGE_KEY, v || "");
  } catch { /* localStorage disabled — picker still works for this tab */ }
}

function withViewer(url) {
  const v = getViewer();
  if (!v) return url;
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}viewer=${encodeURIComponent(v)}`;
}

async function loadSessions() {
  const url = withViewer(SESSIONS_URL);
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`GET ${SESSIONS_URL} → ${r.status}`);
  return r.json();
}

async function loadDetail(sessionId) {
  const url = withViewer(`${SESSIONS_URL}/${encodeURIComponent(sessionId)}`);
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`GET ${SESSIONS_URL}/${sessionId} → ${r.status}`);
  return r.json();
}

async function loadRoster() {
  const r = await fetch(ROSTER_URL, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`GET ${ROSTER_URL} → ${r.status}`);
  return r.json();
}

async function loadMyActionItems() {
  // Server requires ?viewer=; we surface the same 400 to the user.
  const v = getViewer();
  if (!v) throw new Error("anonymous viewer has no personal queue — pick an identity");
  const url = `${ME_ACTION_ITEMS_URL}?viewer=${encodeURIComponent(v)}`;
  const r = await fetch(url, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`GET ${ME_ACTION_ITEMS_URL} → ${r.status}`);
  return r.json();
}

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2).toLowerCase(), v);
    else if (v != null) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
}

// ── shared renderers ───────────────────────────────────────────────────

function renderSpeakerChips(resolved) {
  const entries = Object.entries(resolved || {});
  if (!entries.length) return el("span", { class: "card-meta" }, "no speakers resolved");
  return el(
    "div",
    { class: "chips" },
    entries.map(([label, meta]) =>
      el("span", { class: "chip", title: meta.record_id }, label)
    )
  );
}

// v2.2 (§D.4): the section header carries the kind label; per-item rows
// no longer render an inner kind badge or the source_quote. source_quote
// stays in the API payload for audit/backend use; the dashboard renders
// only the extracted text + speaker attribution (the standing instruction
// we kept missing in v2.1).
function renderSignal(s) {
  // v1 renames: `speakers` → `said_by`; new `about_person`.
  const said_by = s.said_by || s.speakers || [];
  const about = s.about_person || [];
  return el(
    "li",
    { class: "signal" },
    el("div", { class: "signal-text" }, s.text),
    said_by.length || about.length
      ? el(
          "span",
          { class: "signal-attribution" },
          said_by.length ? el("span", { class: "signal-saidby" }, said_by.join(" · ")) : null,
          about.length ? el("span", { class: "signal-about" }, ` → about: ${about.join(", ")}`) : null
        )
      : null
  );
}

// F1 (§D.4): section render order is locked server-side via the
// `signals_by_kind` key insertion order (see `_SIGNAL_KIND_GROUPS` in
// `api/transcripts_routes.py`). We trust that order here — frontend
// stays a thin consumer. Empty sections are skipped (no "INSIGHTS (0)"
// clutter); their absence is the signal.
// v2.2 collapsed to 3 sections: action_items (decisions absorbed),
// open_questions, insights (impactful_points absorbed).
const _SECTION_LABELS = {
  action_items:   "ACTION ITEMS",
  open_questions: "OPEN QUESTIONS",
  insights:       "INSIGHTS",
};
// Singular form per plural — drives the per-section color class so
// the header inherits the section's accent.
const _SECTION_KIND = {
  action_items:   "action_item",
  open_questions: "open_question",
  insights:       "insight",
};

function renderSignalSections(detail) {
  const sbk = (detail && detail.signals_by_kind) || {};
  const sections = [];
  for (const plural of Object.keys(sbk)) {
    const items = sbk[plural] || [];
    if (!items.length) continue; // skip empty per §D.4
    const label = _SECTION_LABELS[plural] || plural.toUpperCase().replace(/_/g, " ");
    const kind = _SECTION_KIND[plural] || "";
    sections.push(
      el(
        "section",
        { class: `signal-section signal-section-${kind}` },
        el(
          "div",
          { class: `signal-section-head signal-kind ${kind}` },
          el("span", { class: "signal-section-label" }, label),
          el("span", { class: "signal-section-count" }, `(${items.length})`)
        ),
        el("ul", { class: "signals" }, items.map(renderSignal))
      )
    );
  }
  if (!sections.length) return null;
  return el("div", { class: "signal-sections" }, sections);
}

function renderEntities(entities) {
  if (!entities || !entities.length) return null;
  // v1 entity additions: cohort_status (member/external/unknown) drives chip
  // styling; affiliation appears as a subtitle ("Alex (flashbots?)" → "ext · flashbots").
  return el(
    "div",
    { class: "entities" },
    entities.map((e) => {
      const cs = e.cohort_status;
      const chipClass = `entity${cs ? ` entity-${cs}` : ""}`;
      const aff = e.affiliation ? ` · ${e.affiliation}` : "";
      return el(
        "span",
        { class: chipClass, title: e.evidence || "" },
        e.name,
        " ",
        el("span", { class: "entity-type" }, `(${e.type}${aff})`)
      );
    })
  );
}

function renderTopics(topics) {
  if (!topics || !topics.length) return null;
  return el(
    "div",
    { class: "topics" },
    topics.map((t) => el("span", { class: "topic" }, t))
  );
}

// ── F2: card preview vs detail view ────────────────────────────────────

// v2.2 importance rule (§D.3): action_items first (which now include the
// old decisions), then insights (which now include the old impactful
// points). Open questions are skipped from the preview (less actionable
// at a glance) but always present in detail.
const _PREVIEW_KIND_ORDER = ["action_items", "insights"];
const _PREVIEW_MAX = 3;

function pickTopSignals(detail) {
  const sbk = (detail && detail.signals_by_kind) || {};
  const picked = [];
  for (const plural of _PREVIEW_KIND_ORDER) {
    for (const s of sbk[plural] || []) {
      picked.push({ kind_plural: plural, signal: s });
      if (picked.length >= _PREVIEW_MAX) return picked;
    }
  }
  return picked;
}

function renderPreviewSignal({ kind_plural, signal }) {
  const kind = _SECTION_KIND[kind_plural] || "";
  return el(
    "li",
    { class: "preview-signal" },
    el(
      "span",
      { class: `preview-signal-kind signal-kind ${kind}` },
      (_SECTION_LABELS[kind_plural] || kind).split(" ")[0] // short tag
    ),
    el("span", { class: "preview-signal-text" }, signal.text)
  );
}

function renderPreviewSignals(detail) {
  const top = pickTopSignals(detail);
  if (!top.length) return null;
  return el("ul", { class: "preview-signals" }, top.map(renderPreviewSignal));
}

// F4 (§D.1): visibility toggle UI. Rendered only when the current
// viewer is the card's owner — the backend enforces the same rule, so
// this is a UX concern, not a security one. Clicking flips the
// visibility via POST /transcripts/sessions/{id}/visibility; on
// success we mutate the in-memory card so the UI reflects the new
// state without a refetch.
async function flipVisibility(card, btn) {
  const target = card.visibility === "cohort" ? "owner-only" : "cohort";
  const viewer = getViewer();
  btn.disabled = true;
  try {
    const r = await fetch(`${SESSIONS_URL}/${encodeURIComponent(card.session_id)}/visibility`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ visibility: target, viewer }),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const payload = await r.json();
    card.visibility = payload.visibility;
    btn.textContent = visibilityToggleLabel(card);
    btn.setAttribute("data-state", card.visibility);
  } catch (err) {
    btn.textContent = `! ${err.message}`;
  } finally {
    btn.disabled = false;
  }
}

function visibilityToggleLabel(card) {
  // Verb describes the action the click performs (not the current state)
  return card.visibility === "cohort" ? "hide from cohort" : "show to cohort";
}

function renderVisibilityToggle(card) {
  const viewer = getViewer();
  if (!viewer || !card.owner || viewer !== card.owner) return null;
  const btn = el(
    "button",
    {
      type: "button",
      class: "visibility-toggle",
      "data-state": card.visibility || "cohort",
      title: `current: ${card.visibility || "cohort"}`,
      onclick: (e) => {
        e.preventDefault();
        e.stopPropagation(); // don't trigger the card's navigate-to-detail
        flipVisibility(card, e.currentTarget);
      },
    },
    visibilityToggleLabel(card)
  );
  return btn;
}

function buildMeta(card) {
  return [
    card.date,
    `source: ${card.source}`,
    card.chunk_count != null ? `${card.chunk_count} chunk${card.chunk_count === 1 ? "" : "s"}` : null,
    card.model_id ? `model: ${card.model_id}` : null,
    card.participants_count ? `${card.participants_count} attendees` : null,
  ].filter(Boolean);
}

function mountGlyph(glyph, seed, sessionId) {
  requestAnimationFrame(() => {
    try {
      mountShape(glyph.querySelector("canvas"), { seed, palette: "auto" });
    } catch (err) {
      // The glyph is decoration — if shape-ui fails (very rare), the card
      // is still useful. Log instead of poisoning the whole grid.
      console.warn("shape mount failed for", sessionId, err);
    }
  });
}

// Mini-preview card for the grid. Clicking anywhere on the card
// navigates to the detail page via the hash router.
function renderCardPreview(card, detail) {
  const glyph = el("div", { class: "card-glyph" }, el("canvas"));
  const summary = card.summary
    ? el("p", { class: "card-summary" }, card.summary)
    : el("p", { class: "card-summary empty" }, "(not yet enriched)");

  const counts = [
    `${card.signal_count || 0} signal${card.signal_count === 1 ? "" : "s"}`,
    `${card.entity_count || 0} entit${card.entity_count === 1 ? "y" : "ies"}`,
    card.topics && card.topics.length ? `${card.topics.length} topic${card.topics.length === 1 ? "" : "s"}` : null,
  ].filter(Boolean).join(" · ");

  const node = el(
    "article",
    {
      class: "card card-preview",
      "data-session-id": card.session_id,
      role: "link",
      tabindex: "0",
      "aria-label": `Open ${card.session_id}`,
      onclick: () => navigateToDetail(card.session_id),
      onkeydown: (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          navigateToDetail(card.session_id);
        }
      },
    },
    el(
      "div",
      { class: "card-head" },
      el(
        "div",
        {},
        el("h2", { class: "card-title" }, card.session_id.replace(/-/g, " · ")),
        el("div", { class: "card-meta" }, buildMeta(card).map((m) => el("span", {}, m)))
      ),
      glyph
    ),
    renderSpeakerChips(card.resolved_speakers),
    renderTopics(card.topics),
    summary,
    renderPreviewSignals(detail),
    el("div", { class: "card-counts" }, counts),
    renderVisibilityToggle(card),
    el("div", { class: "card-cta" }, "view detail →")
  );

  mountGlyph(glyph, card.seed, card.session_id);
  return node;
}

// Detail page: everything in depth — full ordered signal sections,
// all entities, all topics, back-link.
function renderDetail(card, detail) {
  const glyph = el("div", { class: "card-glyph card-glyph-large" }, el("canvas"));
  const summary = card.summary
    ? el("p", { class: "card-summary" }, card.summary)
    : el("p", { class: "card-summary empty" }, "(not yet enriched)");

  const back = el(
    "a",
    {
      class: "detail-back",
      href: "#",
      onclick: (e) => {
        e.preventDefault();
        navigateToGrid();
      },
    },
    "← back to grid"
  );

  const node = el(
    "article",
    { class: "detail-view", "data-session-id": card.session_id },
    back,
    el(
      "div",
      { class: "detail-head" },
      el(
        "div",
        {},
        el("h1", { class: "detail-title" }, card.session_id.replace(/-/g, " · ")),
        el("div", { class: "card-meta" }, buildMeta(card).map((m) => el("span", {}, m)))
      ),
      glyph
    ),
    renderSpeakerChips(card.resolved_speakers),
    renderTopics(card.topics),
    summary,
    renderVisibilityToggle(card),
    renderSignalSections(detail),
    renderEntities(detail && detail.entities)
  );

  mountGlyph(glyph, card.seed, card.session_id);
  return node;
}

// ── hash router ────────────────────────────────────────────────────────

const _DETAIL_HASH_RE = /^#\/sessions\/([^/]+)$/;
const _ME_ACTION_ITEMS_HASH = "#/me/action-items";

function parseRoute() {
  const h = location.hash || "";
  const m = _DETAIL_HASH_RE.exec(h);
  if (m) return { name: "detail", session_id: decodeURIComponent(m[1]) };
  if (h === _ME_ACTION_ITEMS_HASH) return { name: "me_action_items" };
  return { name: "grid" };
}

function navigateToDetail(sessionId) {
  location.hash = `#/sessions/${encodeURIComponent(sessionId)}`;
}

function navigateToGrid() {
  // history.back if there's something to go back to, else clear hash.
  if (history.length > 1 && document.referrer && location.hash) {
    history.back();
  } else {
    location.hash = "";
  }
}

function navigateToMyActionItems() {
  location.hash = _ME_ACTION_ITEMS_HASH;
}

// ── grid + detail render dispatch ──────────────────────────────────────

function updateCounts(cards) {
  const sig = cards.reduce((n, c) => n + (c.signal_count || 0), 0);
  const ent = cards.reduce((n, c) => n + (c.entity_count || 0), 0);
  document.getElementById("counts").textContent =
    `${cards.length} session${cards.length === 1 ? "" : "s"} · ${sig} signal${sig === 1 ? "" : "s"} · ${ent} entit${ent === 1 ? "y" : "ies"}`;
}

function renderEmpty(root) {
  root.appendChild(
    el(
      "div",
      { class: "empty-state" },
      "No sessions yet.",
      el("br"),
      "Ingest some transcripts and enrich them:",
      el(
        "code",
        {},
        "python -m transcripts.cli ingest tests/fixtures/transcripts/\n" +
          "python -m transcripts.cli enrich --pending"
      )
    )
  );
}

// Module-level cache so navigating between grid and detail doesn't
// refetch every time. The dashboard data is small enough that one
// fetch on first load is plenty.
let _cardsCache = null;
let _detailsCache = {}; // session_id → detail | null

async function ensureCards() {
  if (_cardsCache) return _cardsCache;
  _cardsCache = await loadSessions();
  // Hydrate all details in parallel; cheap, all local.
  const details = await Promise.all(
    _cardsCache.map((c) => loadDetail(c.session_id).catch(() => null))
  );
  _cardsCache.forEach((c, i) => { _detailsCache[c.session_id] = details[i]; });
  return _cardsCache;
}

async function renderGrid() {
  const root = document.getElementById("cards");
  root.className = "grid";
  root.innerHTML = "";
  let cards;
  try {
    cards = await ensureCards();
  } catch (err) {
    root.appendChild(el("div", { class: "empty-state" }, `API error: ${err.message}`));
    return;
  }
  if (!cards.length) {
    renderEmpty(root);
    updateCounts([]);
    return;
  }
  updateCounts(cards);
  cards.forEach((c) =>
    root.appendChild(renderCardPreview(c, _detailsCache[c.session_id]))
  );
}

async function renderDetailRoute(sessionId) {
  const root = document.getElementById("cards");
  root.className = "detail";
  root.innerHTML = "";
  let cards;
  try {
    cards = await ensureCards();
  } catch (err) {
    root.appendChild(el("div", { class: "empty-state" }, `API error: ${err.message}`));
    return;
  }
  const card = cards.find((c) => c.session_id === sessionId);
  if (!card) {
    root.appendChild(
      el(
        "div",
        { class: "empty-state" },
        `Session ${sessionId} not found. `,
        el("a", { href: "#", onclick: (e) => { e.preventDefault(); navigateToGrid(); } }, "← back to grid")
      )
    );
    return;
  }
  // Counts header reflects the single-session detail context.
  document.getElementById("counts").textContent =
    `${card.signal_count || 0} signal${card.signal_count === 1 ? "" : "s"} · ${card.entity_count || 0} entit${card.entity_count === 1 ? "y" : "ies"}`;
  root.appendChild(renderDetail(card, _detailsCache[sessionId]));
  // Scroll detail into view if user navigated mid-scroll on grid.
  window.scrollTo({ top: 0, behavior: "instant" });
}

async function renderMyActionItemsRoute() {
  const root = document.getElementById("cards");
  root.className = "detail";
  root.innerHTML = "";

  const back = el(
    "a",
    {
      class: "detail-back",
      href: "#",
      onclick: (e) => { e.preventDefault(); navigateToGrid(); },
    },
    "← back to grid"
  );

  const heading = el("h1", { class: "detail-title" }, "My action items");
  const sub = el(
    "p",
    { class: "card-summary" },
    "Action items where you spoke, or that name you as the assignee. ",
    "Only items from sessions you can see."
  );

  const view = el("article", { class: "detail-view me-queue" }, back, heading, sub);
  root.appendChild(view);

  let items;
  try {
    items = await loadMyActionItems();
  } catch (err) {
    view.appendChild(el("div", { class: "empty-state" }, err.message));
    document.getElementById("counts").textContent = "—";
    return;
  }

  document.getElementById("counts").textContent =
    `${items.length} action item${items.length === 1 ? "" : "s"}`;

  if (!items.length) {
    view.appendChild(
      el(
        "div",
        { class: "empty-state" },
        "Nothing on your queue. Either you're not implicated in any ",
        "open action_item, or no visible session has one for you."
      )
    );
    return;
  }

  // One row per item, in date-desc order from the server. Clicking the
  // row navigates to the source session's detail page.
  const list = el("ul", { class: "me-queue-list" });
  for (const item of items) {
    const sig = item.signal;
    const said_by = sig.said_by || [];
    const about = sig.about_person || [];
    list.appendChild(
      el(
        "li",
        {
          class: "me-queue-item",
          tabindex: "0",
          role: "link",
          onclick: () => navigateToDetail(item.session_id),
          onkeydown: (e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              navigateToDetail(item.session_id);
            }
          },
        },
        el("div", { class: "me-queue-text" }, sig.text),
        el(
          "div",
          { class: "me-queue-meta" },
          el("span", {}, item.session_date || ""),
          el("span", {}, item.session_id.replace(/-/g, " · ")),
          said_by.length ? el("span", { class: "signal-saidby" }, `by ${said_by.join(" · ")}`) : null,
          about.length ? el("span", { class: "signal-about" }, `→ about: ${about.join(", ")}`) : null,
        )
      )
    );
  }
  view.appendChild(list);
  window.scrollTo({ top: 0, behavior: "instant" });
}

async function routeToCurrentHash() {
  const route = parseRoute();
  if (route.name === "detail") {
    await renderDetailRoute(route.session_id);
  } else if (route.name === "me_action_items") {
    await renderMyActionItemsRoute();
  } else {
    await renderGrid();
  }
}

// ── F3: identity picker ────────────────────────────────────────────────

async function renderIdentityPicker() {
  // Modal-style overlay; built fresh each time so a "switch identity"
  // click after first pick shows current state without stale data.
  const existing = document.getElementById("identity-overlay");
  if (existing) existing.remove();

  const overlay = el("div", { id: "identity-overlay", class: "identity-overlay" });
  const panel = el("div", { class: "identity-panel" });
  panel.appendChild(el("h2", { class: "identity-title" }, "Who are you?"));
  panel.appendChild(
    el(
      "p",
      { class: "identity-sub" },
      "Pick yourself from the cohort roster. This is the demo identity ",
      "the dashboard will use — no password, no verification. You can ",
      "switch any time from the masthead.",
    )
  );

  const selectWrap = el("div", { class: "identity-select-wrap" });
  const select = el("select", { class: "identity-select", id: "identity-select" },
    el("option", { value: "" }, "— select identity —"));
  selectWrap.appendChild(select);
  panel.appendChild(selectWrap);

  const actions = el("div", { class: "identity-actions" });
  const confirm = el(
    "button",
    {
      class: "identity-confirm",
      type: "button",
      onclick: () => {
        const v = select.value;
        if (!v) return;
        setViewer(v);
        overlay.remove();
        renderMasthead();
        // Re-fetch with new viewer; state caches were populated under
        // the prior identity, so drop them.
        _cardsCache = null;
        _detailsCache = {};
        routeToCurrentHash();
      },
    },
    "Continue"
  );
  const anon = el(
    "button",
    {
      class: "identity-anon",
      type: "button",
      onclick: () => {
        setViewer(null);
        overlay.remove();
        renderMasthead();
        _cardsCache = null;
        _detailsCache = {};
        routeToCurrentHash();
      },
    },
    "Stay anonymous"
  );
  actions.appendChild(confirm);
  actions.appendChild(anon);
  panel.appendChild(actions);

  overlay.appendChild(panel);
  document.body.appendChild(overlay);

  // Hydrate the dropdown lazily so the picker pops in instantly even
  // if the roster fetch is slow.
  try {
    const roster = await loadRoster();
    const current = getViewer();
    for (const entry of roster) {
      const opt = el(
        "option",
        { value: entry.record_id },
        `${entry.label} (${entry.record_id})${entry.source === "speaker" ? " · speaker-only" : ""}`
      );
      if (current && current === entry.record_id) opt.setAttribute("selected", "selected");
      select.appendChild(opt);
    }
  } catch (err) {
    panel.appendChild(el("div", { class: "identity-error" }, `roster unavailable: ${err.message}`));
  }
}

function renderMasthead() {
  const right = document.querySelector(".mast-right");
  if (!right) return;
  // Remove any previously-rendered identity / queue chips; counts span stays.
  for (const node of Array.from(right.querySelectorAll(".identity-chip, .queue-chip"))) {
    node.remove();
  }
  const v = getViewer();
  // F5: queue link, only when a non-anonymous identity is set.
  if (v) {
    const queue = el(
      "a",
      {
        class: "queue-chip",
        href: "#",
        title: "open my action items",
        onclick: (e) => { e.preventDefault(); navigateToMyActionItems(); },
      },
      "my queue"
    );
    right.appendChild(queue);
  }
  const chip = el(
    "span",
    {
      class: "identity-chip",
      title: v ? "switch identity" : "pick identity",
      onclick: () => renderIdentityPicker(),
    },
    v ? `viewing as: ${v}` : "anonymous · pick identity"
  );
  right.appendChild(chip);
}

// First-visit picker: if no identity has been chosen AND no explicit
// anonymous choice was made (we use the presence/absence of the key
// as proxy — absent = first visit). The picker can also be re-opened
// via the masthead chip.
function maybeShowFirstVisitPicker() {
  // Treat "key missing" as first visit; "key present but empty" as
  // explicitly anonymous (don't nag). Anonymous is a valid identity.
  const raw = (() => { try { return localStorage.getItem(VIEWER_STORAGE_KEY); } catch { return null; } })();
  if (raw === null) renderIdentityPicker();
}

window.addEventListener("hashchange", routeToCurrentHash);
renderMasthead();
maybeShowFirstVisitPicker();
routeToCurrentHash();
