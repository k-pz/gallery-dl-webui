import { Tooltip } from "@mantine/core";
import { useEffect, useRef, useState } from "react";
import { IconCheck, IconCopy } from "./Icons";

/**
 * Copy text to the clipboard, working outside secure contexts too — the app
 * is often served over plain http on a LAN, where navigator.clipboard is
 * undefined and the deprecated execCommand path is the only one available.
 */
async function copyText(value: string): Promise<boolean> {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return true;
    } catch {
      // fall through to the legacy path (e.g. permission denied)
    }
  }
  const ta = document.createElement("textarea");
  ta.value = value;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch {
    ok = false;
  }
  ta.remove();
  return ok;
}

/**
 * Small icon button that copies `value` and flashes a check for feedback.
 * `label` names what is being copied for the tooltip and screen readers
 * (e.g. "Copy URL", "Copy error message").
 */
export function CopyIconButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const timerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    },
    [],
  );

  const onClick = async () => {
    const ok = await copyText(value);
    if (!ok) return;
    setCopied(true);
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => setCopied(false), 1500);
  };

  return (
    <Tooltip label={copied ? "Copied" : label} withArrow>
      <button
        type="button"
        className="icon-btn"
        data-size="sm"
        data-tone={copied ? "success" : undefined}
        aria-label={copied ? "Copied" : label}
        onClick={onClick}
      >
        {copied ? <IconCheck size={14} /> : <IconCopy size={14} />}
      </button>
    </Tooltip>
  );
}
