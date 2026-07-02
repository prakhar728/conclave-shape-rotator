import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { meetingOrigin } from "@/lib/meetingOrigin";

import { OriginBadge } from "./origin-badge";

describe("meetingOrigin", () => {
  it("maps known origins to friendly labels", () => {
    expect(meetingOrigin("in_person").label).toBe("In person");
    expect(meetingOrigin("google_meet").label).toBe("Google Meet");
    expect(meetingOrigin("zoom").label).toBe("Zoom");
    expect(meetingOrigin("teams").label).toBe("Teams");
    expect(meetingOrigin("online").label).toBe("Online");
    expect(meetingOrigin("upload").label).toBe("Uploaded");
    expect(meetingOrigin("demo").label).toBe("Demo");
  });

  it("degrades unknown / missing / raw values to a neutral label (never blank)", () => {
    for (const v of [undefined, null, "", "unknown", "capture"]) {
      const d = meetingOrigin(v);
      expect(d.label).toBe("Meeting");
      expect(d.label.length).toBeGreaterThan(0);
    }
  });

  it("is case/whitespace tolerant", () => {
    expect(meetingOrigin("  IN_PERSON ").label).toBe("In person");
  });
});

describe("OriginBadge", () => {
  it("renders the label and tags the canonical origin for hooks/tests", () => {
    render(<OriginBadge origin="in_person" />);
    const badge = screen.getByTestId("origin-badge");
    expect(badge).toHaveTextContent("In person");
    expect(badge).toHaveAttribute("data-origin", "in_person");
  });

  it("renders a neutral badge (not blank, no raw 'capture') for a raw source", () => {
    render(<OriginBadge origin="capture" />);
    const badge = screen.getByTestId("origin-badge");
    expect(badge).toHaveTextContent("Meeting");
    expect(badge).not.toHaveTextContent("capture");
  });
});
