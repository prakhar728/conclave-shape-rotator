// Conclave cohort-context dashboard — Phase 1 (`IMPLEMENTATION_PLAN.md` §G13).
//
// Fetches the read API, renders one card per session, mounts a shape-ui
// glyph per card keyed on session_id. Per the §G13 critical note we use
// the per-card `mountShape(canvas, opts)` path, not the shared overlay
// — keeps each card self-contained and lets the renderer scale to
// however many sessions the cohort produces.

import { mountShape } from "/dashboard/shape-ui/shape-canvas.js";

const SESSIONS_URL = "/transcripts/sessions";

async function loadSessions() {
  const r = await fetch(SESSIONS_URL, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(`GET ${SESSIONS_URL} → ${r.status}`);
  return r.json();
}

async function loadDetail(sessionId) {
  const r = await fetch(`${SESSIONS_URL}/${encodeURIComponent(sessionId)}`, {
    headers: { Accept: "application/json" },
  });
  if (!r.ok) throw new Error(`GET ${SESSIONS_URL}/${sessionId} → ${r.status}`);
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

function renderSignal(s) {
  // v1 renames: `speakers` → `said_by`; new `about_person` and `source_quote`.
  const said_by = s.said_by || s.speakers || [];
  const about = s.about_person || [];
  return el(
    "li",
    { class: "signal" },
    el("span", { class: `signal-kind ${s.kind}` }, s.kind.replace("_", " ")),
    el(
      "div",
      {},
      el("div", { class: "signal-text" }, s.text),
      s.source_quote
        ? el("blockquote", { class: "signal-quote", title: "verbatim source span" }, `“${s.source_quote}”`)
        : null,
      said_by.length || about.length
        ? el(
            "span",
            { class: "signal-attribution" },
            said_by.length ? el("span", { class: "signal-saidby" }, said_by.join(" · ")) : null,
            about.length ? el("span", { class: "signal-about" }, ` → about: ${about.join(", ")}`) : null
          )
        : null
    )
  );
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

function renderCard(card, detail) {
  const glyph = el("div", { class: "card-glyph" }, el("canvas"));
  const summary = card.summary
    ? el("p", { class: "card-summary" }, card.summary)
    : el("p", { class: "card-summary empty" }, "(not yet enriched)");

  const meta = [
    card.date,
    `source: ${card.source}`,
    card.chunk_count != null ? `${card.chunk_count} chunk${card.chunk_count === 1 ? "" : "s"}` : null,
    card.model_id ? `model: ${card.model_id}` : null,
    card.participants_count ? `${card.participants_count} attendees` : null,
  ].filter(Boolean);

  const node = el(
    "article",
    { class: "card", "data-session-id": card.session_id },
    el(
      "div",
      { class: "card-head" },
      el(
        "div",
        {},
        el("h2", { class: "card-title" }, card.session_id.replace(/-/g, " · ")),
        el("div", { class: "card-meta" }, meta.map((m) => el("span", {}, m)))
      ),
      glyph
    ),
    renderSpeakerChips(card.resolved_speakers),
    renderTopics(card.topics),
    summary,
    detail && detail.signals && detail.signals.length
      ? el("ul", { class: "signals" }, detail.signals.map(renderSignal))
      : null,
    renderEntities(detail && detail.entities)
  );

  // Per-card glyph mount. Seed = session_id → same session, same shape.
  requestAnimationFrame(() => {
    try {
      mountShape(glyph.querySelector("canvas"), { seed: card.seed, palette: "auto" });
    } catch (err) {
      // The glyph is decoration — if shape-ui fails (very rare), the card
      // is still useful. Log instead of poisoning the whole grid.
      console.warn("shape mount failed for", card.session_id, err);
    }
  });

  return node;
}

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

async function render() {
  const root = document.getElementById("cards");
  root.innerHTML = "";
  let cards;
  try {
    cards = await loadSessions();
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

  // Hydrate signals/entities per-card from the detail endpoint. Cheap
  // (all local) and keeps the list endpoint's payload small.
  const details = await Promise.all(
    cards.map((c) => loadDetail(c.session_id).catch(() => null))
  );
  cards.forEach((c, i) => root.appendChild(renderCard(c, details[i])));
}

render();
