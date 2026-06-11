import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import Modal from "./Modal";

describe("Modal (popout)", () => {
  it("renders its children inside a labelled dialog", () => {
    render(
      <Modal title="File a mapping ticket" onClose={() => {}}>
        <p>body content</p>
      </Modal>,
    );
    const dialog = screen.getByRole("dialog", { name: /file a mapping ticket/i });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByText("body content")).toBeInTheDocument();
  });

  it("closes on the × button", () => {
    const onClose = vi.fn();
    render(
      <Modal title="Popout" onClose={onClose}>
        <p>x</p>
      </Modal>,
    );
    fireEvent.click(screen.getByRole("button", { name: /close/i }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes on Escape", () => {
    const onClose = vi.fn();
    render(
      <Modal title="Popout" onClose={onClose}>
        <p>x</p>
      </Modal>,
    );
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("closes when the backdrop (not the dialog) is clicked", () => {
    const onClose = vi.fn();
    const { container } = render(
      <Modal title="Popout" onClose={onClose}>
        <p>x</p>
      </Modal>,
    );
    // Clicking inside the dialog does NOT close.
    fireEvent.mouseDown(screen.getByText("x"));
    expect(onClose).not.toHaveBeenCalled();
    // Clicking the backdrop itself closes.
    const backdrop = container.querySelector(".modal__backdrop") as HTMLElement;
    fireEvent.mouseDown(backdrop);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
