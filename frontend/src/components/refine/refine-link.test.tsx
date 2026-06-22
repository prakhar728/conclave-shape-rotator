import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RefineLink } from "./refine-link";

describe("RefineLink", () => {
  it("links to the refine route for the session", () => {
    render(<RefineLink sessionId="abc123" />);
    const link = screen.getByTestId("refine-link");
    expect(link).toHaveAttribute("href", "/meeting/abc123/refine");
    expect(link).toHaveTextContent(/review.*refine transcript/i);
  });
});
