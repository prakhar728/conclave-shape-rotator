import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useConfirm } from "./confirm-dialog";

function Harness({ onResult }: { onResult: (v: boolean) => void }) {
  const { confirm, dialog } = useConfirm();
  return (
    <div>
      <button
        data-testid="ask"
        onClick={async () =>
          onResult(await confirm({ title: "Delete this?", confirmLabel: "Delete", destructive: true }))
        }
      >
        ask
      </button>
      {dialog}
    </div>
  );
}

describe("useConfirm / ConfirmDialog", () => {
  it("resolves true when confirmed", async () => {
    let result: boolean | null = null;
    render(<Harness onResult={(v) => (result = v)} />);
    fireEvent.click(screen.getByTestId("ask"));
    expect(await screen.findByTestId("confirm-dialog")).toHaveTextContent("Delete this?");
    fireEvent.click(screen.getByTestId("confirm-ok"));
    await waitFor(() => expect(result).toBe(true));
    expect(screen.queryByTestId("confirm-dialog")).toBeNull();
  });

  it("resolves false when cancelled", async () => {
    let result: boolean | null = null;
    render(<Harness onResult={(v) => (result = v)} />);
    fireEvent.click(screen.getByTestId("ask"));
    fireEvent.click(await screen.findByTestId("confirm-cancel"));
    await waitFor(() => expect(result).toBe(false));
  });

  it("resolves false on Escape", async () => {
    let result: boolean | null = null;
    render(<Harness onResult={(v) => (result = v)} />);
    fireEvent.click(screen.getByTestId("ask"));
    await screen.findByTestId("confirm-dialog");
    fireEvent.keyDown(window, { key: "Escape" });
    await waitFor(() => expect(result).toBe(false));
  });

  it("renders nothing until asked", () => {
    render(<Harness onResult={() => {}} />);
    expect(screen.queryByTestId("confirm-dialog")).toBeNull();
  });
});
