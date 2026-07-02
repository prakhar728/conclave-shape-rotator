/**
 * Transcript upload — sharp icon-button CTA + modal.
 *
 * Two paths in one surface: drag-drop / file-pick a .txt/.json (read
 * client-side via FileReader — the API takes JSON text, no multipart),
 * or paste into the textarea. 202 → navigate to /meeting/[id], which
 * already renders the processing state while enrichment runs.
 */
"use client";

import { CloudUpload, FileText, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { ApiError, workspaces } from "@/lib/api";

const MAX_BYTES = 2 * 1024 * 1024; // mirror the server cap

export function UploadTranscriptButton({
  workspaceId,
  className,
}: {
  workspaceId: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        onClick={() => setOpen(true)}
        aria-label="Upload transcript"
        title="Upload transcript"
        className={cn(
          "inline-flex size-10 items-center justify-center rounded-lg border border-border bg-card text-foreground transition-colors hover:bg-secondary",
          className,
        )}
      >
        <CloudUpload className="size-5" aria-hidden />
      </button>
      {open ? (
        <UploadModal workspaceId={workspaceId} onClose={() => setOpen(false)} />
      ) : null}
    </>
  );
}

function UploadModal({
  workspaceId,
  onClose,
}: {
  workspaceId: string;
  onClose: () => void;
}) {
  const router = useRouter();
  const [text, setText] = useState("");
  const [filename, setFilename] = useState<string | null>(null);
  const [intent, setIntent] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState<{
    sessionId: string;
    v2Status: string | null;
    approvedAt: string | null;
  } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const readFile = useCallback((f: File) => {
    setError(null);
    if (f.size > MAX_BYTES) {
      setError("That file is over the 2MB limit.");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      setText(String(reader.result ?? ""));
      setFilename(f.name);
    };
    reader.onerror = () => setError("Couldn't read that file.");
    reader.readAsText(f);
  }, []);

  async function handleSubmit() {
    if (!text.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await workspaces.uploadTranscript(workspaceId, {
        filename: filename ?? undefined,
        text,
        intent: intent.trim() || undefined,
      });
      if (resp.status === "duplicate") {
        // Already imported — surface it instead of dropping into a frozen editor.
        setDuplicate({
          sessionId: resp.session_id,
          v2Status: resp.v2_status ?? null,
          approvedAt: resp.approved_at ?? null,
        });
        setBusy(false);
        return;
      }
      router.push(`/meeting/${resp.session_id}`);
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 422
          ? "Couldn't parse that as a transcript — expected Otter-style “Speaker  0:12” text or a supported JSON export."
          : err instanceof Error
            ? err.message
            : "Upload failed",
      );
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-foreground/40 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Upload transcript"
        className="w-full max-w-lg rounded-none border border-border bg-card p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h2 className="text-xl font-bold tracking-tight">
              Upload a transcript
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              It lands in this workspace, visible only to you — processed
              inside the enclave like every meeting.
            </p>
          </div>
          <button
            onClick={onClose}
            className="flex size-8 shrink-0 items-center justify-center rounded-none bg-secondary text-muted-foreground transition hover:text-foreground"
            aria-label="Close"
          >
            <X className="size-4" />
          </button>
        </div>

        {duplicate ? (
          <div
            data-testid="duplicate-notice"
            className="mb-4 rounded-none border border-border bg-secondary/50 p-4"
          >
            <p className="text-sm font-semibold">Already imported</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {duplicate.v2Status === "approved"
                ? `This transcript was already imported and approved${
                    duplicate.approvedAt
                      ? ` on ${new Date(duplicate.approvedAt).toLocaleDateString()}`
                      : ""
                  }.`
                : "This transcript was already imported — you can keep reviewing it."}
            </p>
            <div className="mt-3 flex items-center gap-2">
              <button
                onClick={() =>
                  router.push(
                    duplicate.v2Status === "approved"
                      ? `/meeting/${duplicate.sessionId}`
                      : `/meeting/${duplicate.sessionId}/refine`,
                  )
                }
                className="rounded-none bg-primary px-4 py-1.5 text-xs font-bold text-primary-foreground"
              >
                {duplicate.v2Status === "approved" ? "View transcript →" : "Open editor →"}
              </button>
              <button
                onClick={() => setDuplicate(null)}
                className="rounded-none px-4 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
              >
                Upload a different one
              </button>
            </div>
          </div>
        ) : null}

        {/* Drop zone / file state */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const f = e.dataTransfer.files?.[0];
            if (f) readFile(f);
          }}
          onClick={() => fileInput.current?.click()}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-none border-2 border-dashed p-6 text-center transition",
            dragOver
              ? "border-primary bg-primary/5"
              : "border-input bg-secondary/50 hover:border-primary/50",
          )}
        >
          {filename ? (
            <>
              <FileText className="size-6 text-primary" aria-hidden />
              <p className="text-sm font-semibold">{filename}</p>
              <p className="text-[10px] text-muted-foreground">
                {(text.length / 1024).toFixed(0)} KB read — click to swap
              </p>
            </>
          ) : (
            <>
              <CloudUpload className="size-6 text-muted-foreground" aria-hidden />
              <p className="text-sm font-medium">
                Drop a <span className="font-mono text-xs">.txt</span> /{" "}
                <span className="font-mono text-xs">.json</span> here, or
                click to pick
              </p>
              <p className="text-[10px] text-muted-foreground">
                Otter-style text or a supported JSON export · 2MB max
              </p>
            </>
          )}
          <input
            ref={fileInput}
            type="file"
            accept=".txt,.json,text/plain,application/json"
            className="hidden"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) readFile(f);
              e.target.value = "";
            }}
          />
        </div>

        <div className="my-4 flex items-center gap-3">
          <span className="h-px flex-1 bg-border" />
          <span className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
            or paste
          </span>
          <span className="h-px flex-1 bg-border" />
        </div>

        <textarea
          value={filename ? "" : text}
          onChange={(e) => {
            setText(e.target.value);
            setFilename(null);
          }}
          placeholder={"Ada Lovelace  0:01\nWe should ship the importer by Friday.\n\nGrace Hopper  0:14\nAgreed — I'll review the parser tomorrow."}
          rows={5}
          disabled={busy}
          className="w-full rounded-none border border-input bg-background px-3 py-2 font-mono text-xs leading-relaxed placeholder:text-muted-foreground/60 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        />

        <input
          value={intent}
          onChange={(e) => setIntent(e.target.value)}
          placeholder="Focus / intent (optional) — what should the notes focus on?"
          disabled={busy}
          className="mt-3 w-full rounded-none border border-input bg-background px-3 py-2 text-xs placeholder:text-muted-foreground/60 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40"
        />

        {error ? (
          <p className="mt-3 text-xs text-destructive">{error}</p>
        ) : null}

        <div className="mt-5 flex items-center justify-end gap-3">
          <button
            onClick={onClose}
            disabled={busy}
            className="rounded-none px-4 py-2 text-xs font-medium text-muted-foreground transition hover:text-foreground"
          >
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={busy || !text.trim()}
            className="inline-flex items-center gap-2 rounded-none bg-primary px-6 py-2.5 text-xs font-bold text-primary-foreground transition-all hover:bg-primary/90 active:scale-95 disabled:pointer-events-none disabled:opacity-50"
          >
            {busy ? "Uploading…" : "Upload & process"}
          </button>
        </div>
      </div>
    </div>
  );
}
