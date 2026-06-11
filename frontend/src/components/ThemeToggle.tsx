import { Tooltip, useMantineColorScheme } from "@mantine/core";
import { ICON_SIZE, IconMonitor, IconMoon, IconSun } from "./Icons";

type Scheme = "auto" | "light" | "dark";

const NEXT: Record<Scheme, Scheme> = { auto: "light", light: "dark", dark: "auto" };
const LABEL: Record<Scheme, string> = { auto: "system", light: "light", dark: "dark" };

/**
 * One-button color-scheme cycler for the header: system → light → dark.
 * The same setting lives in Config as a SegmentedControl; this is the
 * quick path. Mantine persists the choice to localStorage either way.
 */
export function ThemeToggle() {
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const scheme: Scheme = colorScheme === "light" || colorScheme === "dark" ? colorScheme : "auto";
  const label = `Theme: ${LABEL[scheme]} — switch to ${LABEL[NEXT[scheme]]}`;

  return (
    <Tooltip label={label} withArrow>
      <button
        type="button"
        className="icon-btn"
        aria-label={label}
        onClick={() => setColorScheme(NEXT[scheme])}
      >
        {scheme === "light" ? (
          <IconSun size={ICON_SIZE.md} />
        ) : scheme === "dark" ? (
          <IconMoon size={ICON_SIZE.md} />
        ) : (
          <IconMonitor size={ICON_SIZE.md} />
        )}
      </button>
    </Tooltip>
  );
}
