/**
 * A quiet badge showing how a meeting was captured (Task #38):
 * "In person" / "Google Meet" / "Uploaded" / "Demo" / …
 *
 * Muted by default so it reads as provenance, not a call to action. Rendered on
 * the dashboard meeting rows and the meeting-page header.
 */
import { meetingOrigin } from "@/lib/meetingOrigin";

export function OriginBadge({
  origin,
  className = "",
}: {
  origin?: string | null;
  className?: string;
}) {
  const { origin: key, label, Icon } = meetingOrigin(origin);
  return (
    <span
      data-testid="origin-badge"
      data-origin={key}
      title={`Captured: ${label}`}
      className={`inline-flex items-center gap-1 text-muted-foreground ${className}`}
    >
      <Icon className="size-3.5 shrink-0" aria-hidden />
      <span>{label}</span>
    </span>
  );
}
