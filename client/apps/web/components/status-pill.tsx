import { cn } from "@workspace/ui/lib/utils"

type Status = "accepting" | "closed" | "analyzing" | "complete"

export function StatusPill({ status }: { status: string }) {
  const s = status as Status

  const config: Record<Status, { label: string; className: string }> = {
    accepting: {
      label: "Accepting Submissions",
      className: "bg-success/10 text-success",
    },
    closed: {
      label: "Closed",
      className: "bg-[#ff9f0a]/10 text-[#ff9f0a]",
    },
    analyzing: {
      label: "Analyzing",
      className: "bg-[#ff9f0a]/10 text-[#ff9f0a] animate-pulse",
    },
    complete: {
      label: "Complete",
      className: "bg-primary/10 text-primary",
    },
  }

  const c = config[s] ?? config.accepting

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium",
        c.className,
      )}
    >
      {(s === "accepting" || s === "analyzing") && (
        <span
          className={cn(
            "size-1.5 rounded-full",
            s === "accepting" ? "bg-success" : "bg-[#ff9f0a]",
            s === "accepting" && "animate-pulse",
          )}
        />
      )}
      {c.label}
    </span>
  )
}
