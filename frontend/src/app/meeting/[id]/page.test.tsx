import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── next/navigation ──────────────────────────────────────────────────────────
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

// ── useRefineDraft — control draft state directly in tests ───────────────────
// This avoids needing to resolve the page's use(params) Promise in jsdom,
// and lets each test drive the draft/preparing state explicitly.
const mockUseRefineDraft = vi.fn();
vi.mock("@/components/refine/use-refine-draft", () => ({
  useRefineDraft: (...args: unknown[]) => mockUseRefineDraft(...args),
}));

// ── refine components ─────────────────────────────────────────────────────────
vi.mock("@/components/refine/refine-editor", () => ({
  RefineEditor: () => <div data-testid="refine-editor" />,
}));
vi.mock("@/components/refine/refine-actions", () => ({
  RefineActions: () => <div data-testid="refine-actions" />,
}));

// ── Other heavy components ────────────────────────────────────────────────────
vi.mock("@/components/app-shell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));
vi.mock("@/components/transcript-panel", () => ({
  TranscriptPanel: () => <div data-testid="transcript-panel" />,
}));
vi.mock("@/components/owner-controls", () => ({
  OwnerControls: () => null,
}));
vi.mock("@/components/retention-control", () => ({
  RetentionControl: () => null,
}));
vi.mock("@/components/refine/insights-placeholder", () => ({
  InsightsPlaceholder: () => null,
}));

// ── Resolve use(params) synchronously ─────────────────────────────────────────
// The page calls `const { id } = use(params)` where params is a Promise.
// React.use() suspends in React 19's concurrent runtime, but jsdom does not
// support that runtime. We intercept the `use` export from "react" so that
// when the page calls it with an already-resolved Promise the value is returned
// synchronously — letting the component body run without needing Suspense.
vi.mock("react", async (importOriginal) => {
  const actual = await importOriginal<typeof React>();
  // Store resolved values keyed by promise so the sync mock is stable.
  const cache = new WeakMap<Promise<unknown>, unknown>();
  return {
    ...actual,
    use: <T,>(value: T | Promise<T>): T => {
      if (value && typeof (value as Promise<T>).then === "function") {
        const p = value as Promise<T>;
        if (!cache.has(p)) {
          // Register a .then handler synchronously; for an already-resolved
          // Promise the microtask fires before the next render cycle starts.
          p.then((v) => cache.set(p, v));
          // First call: promise is pending from this scope's perspective.
          // Throw to trigger Suspense (React will retry after microtask).
          throw p;
        }
        return cache.get(p) as T;
      }
      return actual.use(value as never);
    },
  };
});

// ── helpers ───────────────────────────────────────────────────────────────────
import MeetingPage from "./page";
import { ApiError, auth, meetings, refine } from "@/lib/api";

const ME = { user: { id: "u1", email: "a@b.com", name: "Alice" }, workspaces: [] };

function baseMeeting(overrides: Record<string, unknown> = {}) {
  return {
    session_id: "s1",
    date: "2026-06-01",
    source: "otter",
    summary: "Meeting summary",
    visibility: "owner-only",
    owner: "u1",
    resolved_speakers: {},
    topics: [],
    participants: null,
    signals: [],
    signals_by_kind: { action_items: [], open_questions: [], insights: [] },
    entities: [],
    enrichment_status: "ok",
    can_view_transcript: true,
    ...overrides,
  };
}

function baseDraft() {
  return {
    session_id: "s1",
    status: "draft",
    approved_at: null,
    insights_stale: false,
    segments: [],
    annotations: [],
  };
}

function renderPage(id = "s1") {
  const params = Promise.resolve({ id });
  return render(
    <React.Suspense fallback={null}>
      <MeetingPage params={params} />
    </React.Suspense>
  );
}

describe("MeetingPage — editor vs transcript panel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    pushMock.mockReset();
    mockUseRefineDraft.mockReset();
  });

  it("renders RefineEditor when owner + draft ready", async () => {
    vi.spyOn(auth, "me").mockResolvedValue(ME as never);
    vi.spyOn(meetings, "get").mockResolvedValue(
      baseMeeting({ is_owner: true, workspace_id: "ws1" }) as never
    );
    vi.spyOn(refine, "getDraft").mockResolvedValue(baseDraft() as never);
    mockUseRefineDraft.mockReturnValue({
      draft: baseDraft(),
      setDraft: vi.fn(),
      preparing: false,
    });

    renderPage();

    // Editor + transcript live under the "Transcript" sub-tab.
    fireEvent.click(await screen.findByRole("button", { name: "transcript" }));
    await waitFor(() => expect(screen.getByTestId("refine-editor")).toBeInTheDocument());
    expect(screen.queryByTestId("transcript-panel")).toBeNull();
  });

  it("renders TranscriptPanel when owner but draft is still preparing (404)", async () => {
    vi.spyOn(auth, "me").mockResolvedValue(ME as never);
    vi.spyOn(meetings, "get").mockResolvedValue(
      baseMeeting({ is_owner: true }) as never
    );
    vi.spyOn(refine, "getDraft").mockRejectedValue(new ApiError(404, "not found", "not found"));
    mockUseRefineDraft.mockReturnValue({
      draft: null,
      setDraft: vi.fn(),
      preparing: true,
    });

    renderPage();

    // Transcript lives under the "Transcript" sub-tab.
    fireEvent.click(await screen.findByRole("button", { name: "transcript" }));
    await waitFor(() => expect(screen.getByTestId("transcript-panel")).toBeInTheDocument());
    expect(screen.queryByTestId("refine-editor")).toBeNull();
  });

  it("renders TranscriptPanel for non-owner viewer", async () => {
    vi.spyOn(auth, "me").mockResolvedValue(ME as never);
    vi.spyOn(meetings, "get").mockResolvedValue(
      baseMeeting({ is_owner: false }) as never
    );
    vi.spyOn(refine, "getDraft").mockResolvedValue(baseDraft() as never);
    mockUseRefineDraft.mockReturnValue({
      draft: baseDraft(),
      setDraft: vi.fn(),
      preparing: false,
    });

    renderPage();

    // Transcript lives under the "Transcript" sub-tab.
    fireEvent.click(await screen.findByRole("button", { name: "transcript" }));
    await waitFor(() => expect(screen.getByTestId("transcript-panel")).toBeInTheDocument());
    expect(screen.queryByTestId("refine-editor")).toBeNull();
  });
});

describe("MeetingPage — agenda-grounded provenance signal", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    pushMock.mockReset();
    mockUseRefineDraft.mockReset();
    mockUseRefineDraft.mockReturnValue({
      draft: baseDraft(),
      setDraft: vi.fn(),
      preparing: false,
    });
    vi.spyOn(auth, "me").mockResolvedValue(ME as never);
    vi.spyOn(refine, "getDraft").mockResolvedValue(baseDraft() as never);
  });

  it("shows the agenda-grounded badge when meeting_intent_version is set", async () => {
    vi.spyOn(meetings, "get").mockResolvedValue(
      baseMeeting({ is_owner: false, meeting_intent_version: "a1b2c3d4" }) as never
    );
    renderPage();
    const badge = await screen.findByTestId("agenda-grounded");
    expect(badge).toHaveAttribute("title", "meeting_intent_version: a1b2c3d4");
  });

  it("hides the badge when meeting_intent_version is null (no grounding)", async () => {
    vi.spyOn(meetings, "get").mockResolvedValue(
      baseMeeting({ is_owner: false, meeting_intent_version: null }) as never
    );
    renderPage();
    await waitFor(() => expect(screen.getByText(/Meeting summary/)).toBeInTheDocument());
    expect(screen.queryByTestId("agenda-grounded")).toBeNull();
  });
});

describe("MeetingPage — Task #13 heal-on-open badge", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    pushMock.mockReset();
    mockUseRefineDraft.mockReset();
    mockUseRefineDraft.mockReturnValue({
      draft: baseDraft(),
      setDraft: vi.fn(),
      preparing: false,
    });
    vi.spyOn(auth, "me").mockResolvedValue(ME as never);
    vi.spyOn(refine, "getDraft").mockResolvedValue(baseDraft() as never);
  });

  it("shows the 'updating insights' badge when insights_regenerating is true", async () => {
    vi.spyOn(meetings, "get").mockResolvedValue(
      baseMeeting({ is_owner: false, insights_regenerating: true }) as never
    );
    renderPage();
    await waitFor(() => expect(screen.getByTestId("insights-updating")).toBeInTheDocument());
  });

  it("hides the badge when insights_regenerating is absent/false", async () => {
    vi.spyOn(meetings, "get").mockResolvedValue(
      baseMeeting({ is_owner: false }) as never
    );
    renderPage();
    await waitFor(() => expect(screen.getByText(/Meeting summary/)).toBeInTheDocument());
    expect(screen.queryByTestId("insights-updating")).toBeNull();
  });

  it("clears the badge once insights_regenerating flips false — even when the draft 404s (no v2)", async () => {
    // The lingering-badge fix: the poll must clear on the meeting's authoritative
    // `insights_regenerating`, not only the draft's `insights_stale`. Here getDraft
    // 404s (no v2), so the OLD draft-only poll would ride its ~3min timeout.
    const getMock = vi
      .spyOn(meetings, "get")
      .mockResolvedValueOnce(baseMeeting({ is_owner: false, insights_regenerating: true }) as never)
      .mockResolvedValue(baseMeeting({ is_owner: false, insights_regenerating: false }) as never);
    vi.spyOn(refine, "getDraft").mockRejectedValue(new ApiError(404, "no v2", "no v2"));

    renderPage();
    // Badge shows on the initial (regenerating) load.
    await waitFor(() => expect(screen.getByTestId("insights-updating")).toBeInTheDocument());

    // The 4s poll re-fetches the meeting (now regenerating=false) and clears the badge.
    await waitFor(
      () => expect(screen.queryByTestId("insights-updating")).toBeNull(),
      { timeout: 8000 }
    );
    expect(getMock.mock.calls.length).toBeGreaterThan(1); // initial load + ≥1 poll tick
  }, 12000);
});
