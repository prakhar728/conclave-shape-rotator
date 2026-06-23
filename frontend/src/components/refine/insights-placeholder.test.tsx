import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { InsightsPlaceholder } from "./insights-placeholder";

describe("InsightsPlaceholder", () => {
  it("explains 'no LLM configured' when skipped", () => {
    render(<InsightsPlaceholder status="skipped" />);
    expect(screen.getByTestId("insights-placeholder")).toHaveTextContent(/no LLM is configured/i);
  });

  it("explains an LLM failure", () => {
    render(<InsightsPlaceholder status="failed" />);
    expect(screen.getByTestId("insights-placeholder")).toHaveTextContent(/unreachable/i);
  });

  it("shows a processing message while pending", () => {
    render(<InsightsPlaceholder status="pending" />);
    expect(screen.getByTestId("insights-placeholder")).toHaveTextContent(/still being generated/i);
  });

  it("falls back to 'found nothing' when the LLM ran (ok / unknown)", () => {
    render(<InsightsPlaceholder status="ok" />);
    expect(screen.getByTestId("insights-placeholder")).toHaveTextContent(/no action items/i);
  });
});
