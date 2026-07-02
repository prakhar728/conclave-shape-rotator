/**
 * A proper in-app confirmation dialog — replaces the ugly native `window.confirm`
 * ("localhost:3001 says…"). Themed, backdrop-dismissable, Escape-to-cancel.
 *
 * Usage mirrors `window.confirm` (await a boolean):
 *   const { confirm, dialog } = useConfirm();
 *   if (!(await confirm({ title: "Delete this meeting?", body: "This can't be undone.",
 *                         confirmLabel: "Delete", destructive: true }))) return;
 *   …do the thing…
 *   return (<>…{dialog}…</>);
 */
"use client";

import { useCallback, useEffect, useState } from "react";

export type ConfirmOptions = {
  title: string;
  body?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
};

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmOptions & {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
      if (e.key === "Enter") onConfirm();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel, onConfirm]);

  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      data-testid="confirm-dialog"
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
    >
      <div
        className="absolute inset-0 bg-foreground/40 backdrop-blur-sm"
        onClick={onCancel}
        aria-hidden
      />
      <div className="relative w-full max-w-sm rounded-xl border border-border bg-card p-6 shadow-xl">
        <h2 className="text-base font-bold tracking-tight text-foreground">{title}</h2>
        {body ? <p className="mt-2 text-sm text-muted-foreground">{body}</p> : null}
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            data-testid="confirm-cancel"
            onClick={onCancel}
            className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-muted-foreground transition hover:bg-secondary hover:text-foreground"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            autoFocus
            data-testid="confirm-ok"
            onClick={onConfirm}
            className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition ${
              destructive
                ? "bg-destructive text-white hover:opacity-90"
                : "bg-foreground text-background hover:opacity-90"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Hook that yields a `confirm(opts) => Promise<boolean>` + the dialog element to render. */
export function useConfirm() {
  const [state, setState] = useState<
    { opts: ConfirmOptions; resolve: (v: boolean) => void } | null
  >(null);

  const confirm = useCallback(
    (opts: ConfirmOptions) =>
      new Promise<boolean>((resolve) => setState({ opts, resolve })),
    [],
  );

  const settle = useCallback(
    (v: boolean) => {
      setState((s) => {
        s?.resolve(v);
        return null;
      });
    },
    [],
  );

  const dialog = (
    <ConfirmDialog
      open={state !== null}
      title={state?.opts.title ?? ""}
      body={state?.opts.body}
      confirmLabel={state?.opts.confirmLabel}
      cancelLabel={state?.opts.cancelLabel}
      destructive={state?.opts.destructive}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  );

  return { confirm, dialog };
}
