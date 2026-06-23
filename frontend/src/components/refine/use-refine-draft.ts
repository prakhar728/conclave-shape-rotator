"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ApiError, auth, refine, type MeResponse, type V2Draft } from "@/lib/api";

const POLL_MS = 2000;
const MAX_ATTEMPTS = 15; // ~30s

/**
 * Loads the v2 draft for the refine editor. The draft is built in a background job
 * after upload, so `getDraft` can 404 for a moment — we treat that as "preparing" and
 * poll until it appears (instead of dead-ending). 403 / persistent 404 surface as
 * real errors. Returns `setDraft` so the editor can update the draft in place.
 */
export function useRefineDraft(id: string) {
  const router = useRouter();
  const [me, setMe] = useState<MeResponse | null>(null);
  const [draft, setDraft] = useState<V2Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      try {
        const d = await refine.getDraft(id);
        if (cancelled) return;
        setDraft(d);
        setPreparing(false);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError) {
          if (err.status === 403) {
            setError("You don't have access to this transcript.");
            return;
          }
          if (err.status === 404) {
            // The draft isn't ready yet (still being prepared) — keep polling.
            attempts += 1;
            if (attempts >= MAX_ATTEMPTS) {
              setPreparing(false);
              setError("This transcript is still being prepared — refresh in a moment.");
              return;
            }
            setPreparing(true);
            timer = setTimeout(poll, POLL_MS);
            return;
          }
        }
        setError(err instanceof Error ? err.message : "Failed to load the draft");
      }
    };

    (async () => {
      try {
        const meResp = await auth.me();
        if (cancelled) return;
        setMe(meResp);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 401) {
          router.push("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load");
        return;
      }
      poll();
    })();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id, router]);

  return { me, draft, setDraft, error, preparing };
}
