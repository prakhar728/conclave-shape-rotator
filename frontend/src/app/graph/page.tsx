/**
 * /graph — force-directed knowledge graph (Phase 3.5d C30–C33).
 *
 * Full-screen react-force-graph-2d over GET /graph. Node colors by
 * kind; node size by weight. Hover highlights neighbors; click
 * navigates (meeting → /meeting/[id], entity → /entity/[name]);
 * drag/zoom/pan built in. Filter panel: as-of date, entity-type
 * checkboxes, min-mentions. Search box reuses the C23 endpoint
 * (top_k=200) and glows matching meeting nodes. Dismissible legend.
 * Mobile gets a fallback message — force layouts on a phone help
 * nobody.
 */
"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { PageError, PageLoading } from "@/components/page-state";
import { ApiError, apiFetch, auth, search, type MeResponse } from "@/lib/api";

const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
});

type GraphNode = {
  id: string;
  kind: "meeting" | "entity" | "speaker";
  label: string;
  entity_type?: string;
  weight?: number;
  date?: string | null;
};
type GraphEdge = { source: string; target: string; weight: number };

/** Node as react-force-graph hands it back: our fields + sim coords. */
type SimNode = GraphNode & { x: number; y: number };
type SimLink = GraphEdge;

/**
 * Node palette lives in globals.css as --signal-* vars (UI-NOW.md §1) so
 * the canvas shares the theme's color language. Canvas needs concrete
 * strings at draw time, so we read the vars once after mount —
 * getComputedStyle doesn't exist during SSR/prerender.
 */
type GraphColors = {
  meeting: string;
  entity: string;
  speaker: string;
  /** search-hit glow (mint) */
  mint: string;
  /** dimmed nodes, labels, links */
  muted: string;
};

function readGraphColors(): GraphColors {
  const css = getComputedStyle(document.documentElement);
  const v = (name: string) => css.getPropertyValue(name).trim();
  return {
    meeting: v("--signal-meeting"),
    entity: v("--signal-entity"),
    speaker: v("--signal-speaker"),
    mint: v("--accent-mint"),
    muted: v("--muted-foreground"),
  };
}

const NODE_KINDS = ["meeting", "entity", "speaker"] as const;
const ENTITY_TYPES = ["person", "project", "topic", "company", "tool"];

export default function GraphPage() {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [data, setData] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  // filters (C32)
  const [asOf, setAsOf] = useState("");
  const [enabledTypes, setEnabledTypes] = useState<Set<string>>(
    new Set(ENTITY_TYPES),
  );
  const [minMentions, setMinMentions] = useState(1);

  // search highlight (C33)
  const [graphQuery, setGraphQuery] = useState("");
  const [highlighted, setHighlighted] = useState<Set<string>>(new Set());

  // hover highlight (C31)
  const [hoverNode, setHoverNode] = useState<string | null>(null);
  const neighborsRef = useRef<Map<string, Set<string>>>(new Map());

  const [legendOpen, setLegendOpen] = useState(true);

  // Theme palette for the canvas — read lazily on the client (see
  // readGraphColors); null during SSR/prerender where there's no DOM.
  const [colors] = useState<GraphColors | null>(() =>
    typeof window === "undefined" ? null : readGraphColors(),
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
        if (!meResp.workspace) {
          setData({ nodes: [], edges: [] });
          return;
        }
        const params = new URLSearchParams();
        if (asOf) params.set("as_of", asOf);
        if (enabledTypes.size < ENTITY_TYPES.length)
          params.set("types", Array.from(enabledTypes).join(","));
        if (minMentions > 1) params.set("min_mentions", String(minMentions));
        const q = params.toString();
        const resp = await apiFetch<{ nodes: GraphNode[]; edges: GraphEdge[] }>(
          `/api/workspaces/${meResp.workspace.id}/graph${q ? `?${q}` : ""}`,
        );
        if (cancelled) return;
        const neighbors = new Map<string, Set<string>>();
        for (const e of resp.edges) {
          if (!neighbors.has(e.source)) neighbors.set(e.source, new Set());
          if (!neighbors.has(e.target)) neighbors.set(e.target, new Set());
          neighbors.get(e.source)!.add(e.target);
          neighbors.get(e.target)!.add(e.source);
        }
        neighborsRef.current = neighbors;
        setData(resp);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load graph");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, asOf, enabledTypes, minMentions]);

  async function runGraphSearch() {
    if (!me?.workspace || !graphQuery.trim()) {
      setHighlighted(new Set());
      return;
    }
    try {
      const resp = await search.query(me.workspace.id, graphQuery.trim(), 200);
      setHighlighted(
        new Set(resp.results.map((r) => `meeting:${r.session_id}`)),
      );
    } catch {
      setHighlighted(new Set());
    }
  }

  const graphData = useMemo(() => {
    if (!data) return { nodes: [], links: [] };
    return {
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.edges.map((e) => ({ ...e })),
    };
  }, [data]);

  const paintNode = useCallback(
    (nodeObj: object, ctx: CanvasRenderingContext2D, scale: number) => {
      if (!colors) return;
      const node = nodeObj as SimNode;
      const r = Math.min(3 + Math.sqrt(node.weight ?? 1), 10);
      const isHighlit = highlighted.has(node.id);
      const isNeighbor =
        hoverNode &&
        (node.id === hoverNode ||
          neighborsRef.current.get(hoverNode)?.has(node.id));
      const dimmed = (hoverNode && !isNeighbor) as boolean;

      if (isHighlit) {
        // Search-hit glow — mint (UI-NOW.md §3). "40" = 25% alpha hex suffix.
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 3, 0, 2 * Math.PI);
        ctx.fillStyle = `${colors.mint}40`;
        ctx.fill();
      }
      ctx.beginPath();
      ctx.arc(node.x, node.y, r, 0, 2 * Math.PI);
      ctx.fillStyle = dimmed
        ? `${colors.muted}40`
        : colors[node.kind as (typeof NODE_KINDS)[number]] ?? colors.muted;
      ctx.fill();

      if (scale > 1.2 && !dimmed) {
        ctx.font = `${10 / scale}px sans-serif`;
        ctx.fillStyle = colors.muted;
        ctx.fillText(node.label ?? "", node.x + r + 2, node.y + 3);
      }
    },
    [highlighted, hoverNode, colors],
  );

  const handleClick = useCallback(
    (nodeObj: object) => {
      const node = nodeObj as SimNode;
      if (node.kind === "meeting") {
        router.push(`/meeting/${String(node.id).replace("meeting:", "")}`);
      } else if (node.kind === "entity") {
        router.push(`/entity/${encodeURIComponent(node.label)}`);
      }
    },
    [router],
  );

  if (error) return <PageError message={error} />;
  if (!me) return <PageLoading />;

  return (
    <AppShell user={me.user} workspace={me.workspace}>
      {/* mobile fallback (C33 / 3.5d.10) */}
      <div className="flex flex-1 items-center justify-center px-6 md:hidden">
        <p className="text-center text-sm text-muted-foreground">
          The graph view needs a larger screen.
        </p>
      </div>

      <div className="relative hidden flex-1 md:block">
        {/* filter panel (C32) */}
        <div className="absolute left-4 top-4 z-10 w-60 rounded-md border border-border bg-background/95 p-3 text-xs shadow">
          <p className="mb-2 font-medium">Filters</p>
          <label className="mb-2 block">
            <span className="text-muted-foreground">As of date</span>
            <input
              type="date"
              value={asOf}
              onChange={(e) => setAsOf(e.target.value)}
              className="mt-1 h-7 w-full rounded border border-border bg-background px-1"
            />
          </label>
          <p className="mb-1 text-muted-foreground">Entity types</p>
          <div className="mb-2 flex flex-wrap gap-1">
            {ENTITY_TYPES.map((t) => (
              <button
                key={t}
                onClick={() => {
                  const next = new Set(enabledTypes);
                  if (next.has(t)) next.delete(t);
                  else next.add(t);
                  setEnabledTypes(next);
                }}
                className={`rounded-full border px-2 py-0.5 capitalize ${
                  enabledTypes.has(t)
                    ? "border-primary/60 text-primary"
                    : "border-border text-muted-foreground"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          <label className="block">
            <span className="text-muted-foreground">
              Min mentions: {minMentions}
            </span>
            <input
              type="range"
              min={1}
              max={10}
              value={minMentions}
              onChange={(e) => setMinMentions(Number(e.target.value))}
              className="mt-1 w-full"
            />
          </label>
          <div className="mt-3 border-t border-border pt-2">
            <input
              value={graphQuery}
              onChange={(e) => setGraphQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runGraphSearch()}
              placeholder="Highlight by search…"
              className="h-7 w-full rounded border border-border bg-background px-1"
            />
          </div>
        </div>

        {/* legend (C33 / 3.5d.9) */}
        {legendOpen ? (
          <div className="absolute bottom-4 right-4 z-10 rounded-md border border-border bg-background/95 p-3 text-xs shadow">
            <div className="mb-1 flex items-center justify-between gap-6">
              <p className="font-medium">Legend</p>
              <button
                onClick={() => setLegendOpen(false)}
                className="text-muted-foreground hover:text-foreground"
              >
                ✕
              </button>
            </div>
            {NODE_KINDS.map((kind) => (
              <p key={kind} className="flex items-center gap-2 capitalize">
                <span
                  className={`inline-block h-2.5 w-2.5 rounded-full ${
                    kind === "meeting"
                      ? "bg-signal-meeting"
                      : kind === "entity"
                        ? "bg-signal-entity"
                        : "bg-signal-speaker"
                  }`}
                />
                {kind}
              </p>
            ))}
            <p className="mt-1 text-muted-foreground">
              Node size = mentions · edge = appears in
            </p>
          </div>
        ) : null}

        {data === null ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">Loading graph…</p>
          </div>
        ) : data.nodes.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-sm text-muted-foreground">
              Nothing to draw yet — the knowledge pipeline hasn&apos;t
              processed your meetings.
            </p>
          </div>
        ) : colors === null ? null : (
          <ForceGraph2D
            graphData={graphData}
            nodeCanvasObject={paintNode}
            nodePointerAreaPaint={(nodeObj: object, color, ctx) => {
              const node = nodeObj as SimNode;
              ctx.beginPath();
              ctx.arc(node.x, node.y, 10, 0, 2 * Math.PI);
              ctx.fillStyle = color;
              ctx.fill();
            }}
            linkColor={() => `${colors.muted}33`}
            linkWidth={(l: object) => Math.min(0.5 + (l as SimLink).weight * 0.4, 3)}
            onNodeClick={handleClick}
            onNodeHover={(n: object | null) => setHoverNode(n ? (n as SimNode).id : null)}
            cooldownTicks={120}
          />
        )}
      </div>
    </AppShell>
  );
}
