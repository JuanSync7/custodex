// A lightweight accessible popout/modal overlay. Used for the mapping-ticket form
// ("Edit mapping…" / "Link to a document…") so it floats above the page instead of
// pushing the layout. Closes on Escape, a backdrop click, or the × button; focuses
// the dialog on mount and restores focus to the opener on close.
import { useEffect, useRef, type ReactNode } from "react";

export interface ModalProps {
  /** Accessible name for the dialog (and the visible title-bar label). */
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export function Modal({ title, onClose, children }: ModalProps) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
  }, [onClose]);

  return (
    <div
      className="modal__backdrop"
      // A mousedown on the backdrop itself (not a child) closes the popout.
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal__dialog panel"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={dialogRef}
        tabIndex={-1}
      >
        <div className="modal__head">
          <span className="modal__title">{title}</span>
          <button
            type="button"
            className="modal__close"
            aria-label="Close"
            onClick={onClose}
          >
            ×
          </button>
        </div>
        <div className="modal__body">{children}</div>
      </div>
    </div>
  );
}

export default Modal;
