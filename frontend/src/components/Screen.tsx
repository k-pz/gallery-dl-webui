import { type ReactNode, type Ref, useRef } from "react";
import { useModalFocusTrap } from "../hooks/useModalFocusTrap";
import type { ScreenLayout } from "../hooks/useScreenLayout";
import { ICON_SIZE, IconChevronDown } from "./Icons";

/**
 * One tab as a single screen sized to the viewport below the header. Its
 * panes sit side by side and each scrolls on its own; `name` selects the
 * column template in CSS (`.screen[data-screen=…]`). On phones (`stack`)
 * the panes flow with the page instead.
 */
export function Screen({
  name,
  layout,
  children,
}: {
  name: string;
  layout: ScreenLayout;
  children: ReactNode;
}) {
  return (
    <div className="screen" data-screen={name} data-layout={layout}>
      {children}
    </div>
  );
}

/** A bordered pane with an optional heading row and footer; the body scrolls. */
export function Pane({
  label,
  kicker,
  title,
  actions,
  footer,
  className,
  bodyRef,
  children,
}: {
  /** Accessible name of the region. */
  label: string;
  kicker?: string;
  title?: ReactNode;
  actions?: ReactNode;
  /** Pinned below the scrolling body (e.g. a save bar). */
  footer?: ReactNode;
  className?: string;
  bodyRef?: Ref<HTMLDivElement>;
  children: ReactNode;
}) {
  const hasHead = kicker !== undefined || title !== undefined || actions !== undefined;
  return (
    <section className={className ? `pane ${className}` : "pane"} aria-label={label}>
      {hasHead && (
        <div className="pane-head">
          <div className="pane-head-text">
            {kicker && <span className="app-section-kicker">{kicker}</span>}
            {title && <h2 className="pane-title">{title}</h2>}
          </div>
          {actions && <div className="pane-head-actions">{actions}</div>}
        </div>
      )}
      <div className="pane-scroll" ref={bodyRef}>
        {children}
      </div>
      {footer && <div className="pane-foot">{footer}</div>}
    </section>
  );
}

/**
 * Phones: a picked item opens as a full-screen layer over the list, like a
 * pushed screen. Focus stays inside; Escape and the back button return.
 */
export function StackedView({
  title,
  backLabel,
  onBack,
  children,
}: {
  title: string;
  backLabel: string;
  onBack: () => void;
  children: ReactNode;
}) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  useModalFocusTrap({ active: true, rootRef, onClose: onBack, lockScroll: true });
  return (
    <div
      ref={rootRef}
      className="pane pane-stacked"
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div className="pane-back">
        <button type="button" className="pane-back-btn" onClick={onBack} aria-label={backLabel}>
          <IconChevronDown size={ICON_SIZE.lg} className="pane-back-icon" />
        </button>
        <span className="pane-back-title">{title}</span>
      </div>
      <div className="pane-stacked-body">{children}</div>
    </div>
  );
}
