import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("frontend test runner smoke", () => {
  it("renders a component + jest-dom matchers work", () => {
    render(<div>hello refine</div>);
    expect(screen.getByText("hello refine")).toBeInTheDocument();
  });
});
