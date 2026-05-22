/**
 * Hamburger / close trigger for the mobile nav drawer. Hidden at >=768px via
 * `.mob-menu-btn` CSS — the desktop tab bar handles navigation up there.
 */
export function MobileMenuButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className="mob-menu-btn"
      aria-label={open ? "Close menu" : "Open menu"}
      aria-expanded={open}
      onClick={onClick}
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.9}
        strokeLinecap="round"
        aria-hidden="true"
        focusable="false"
      >
        {open ? (
          <>
            <path d="M6 6 18 18" />
            <path d="M18 6 6 18" />
          </>
        ) : (
          <>
            <path d="M4 7h16" />
            <path d="M4 12h16" />
            <path d="M4 17h16" />
          </>
        )}
      </svg>
    </button>
  );
}
