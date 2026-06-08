import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "../test/render";
import { LogsPanel } from "./LogsPanel";

type Listener = (e: MessageEvent) => void;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  listeners = new Map<string, Listener>();
  onerror: ((ev: Event) => unknown) | null = null;
  closed = false;

  constructor(url: string | URL) {
    this.url = String(url);
    FakeEventSource.instances.push(this);
  }
  addEventListener(name: string, fn: Listener) {
    this.listeners.set(name, fn);
  }
  removeEventListener(name: string) {
    this.listeners.delete(name);
  }
  close() {
    this.closed = true;
  }

  ready() {
    this.listeners.get("ready")?.(new MessageEvent("ready"));
  }
  log(payload: Record<string, unknown>) {
    this.listeners.get("log")?.(new MessageEvent("log", { data: JSON.stringify(payload) }));
  }
}

// jsdom doesn't simulate layout — override descriptors so we can drive the
// scroll container's geometry by hand.
function fakeLayout(
  el: HTMLElement,
  initial: { scrollHeight: number; clientHeight: number; scrollTop: number },
) {
  const state = { ...initial };
  Object.defineProperty(el, "scrollHeight", {
    configurable: true,
    get: () => state.scrollHeight,
  });
  Object.defineProperty(el, "clientHeight", {
    configurable: true,
    get: () => state.clientHeight,
  });
  Object.defineProperty(el, "scrollTop", {
    configurable: true,
    get: () => state.scrollTop,
    set: (v: number) => {
      state.scrollTop = v;
    },
  });
  return state;
}

function makeLog(message: string, id: number) {
  return {
    ts_ms: 1_700_000_000_000 + id,
    priority: 6,
    level: "info",
    message,
    unit: "gallery-dl-webui.service",
    ident: "gallery-dl-webui",
    pid: "1",
  };
}

function getFollowSwitch(): HTMLInputElement {
  return screen.getByRole("switch", { name: /follow latest/i }) as HTMLInputElement;
}

function getScroll(): HTMLElement {
  return screen.getByTestId("logs-scroll");
}

describe("LogsPanel follow behavior", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("starts with follow on and auto-scrolls new entries", () => {
    renderWithProviders(<LogsPanel />);
    expect(getFollowSwitch()).toBeChecked();

    const scroll = getScroll();
    const geom = fakeLayout(scroll, { scrollHeight: 1000, clientHeight: 400, scrollTop: 0 });

    const es = FakeEventSource.instances[0];
    expect(es).toBeDefined();
    act(() => {
      es.ready();
      es.log(makeLog("hello", 1));
    });

    // Auto-scrolled to bottom.
    expect(geom.scrollTop).toBe(1000);
  });

  it("disengages follow when the user scrolls up", () => {
    renderWithProviders(<LogsPanel />);
    const scroll = getScroll();
    const geom = fakeLayout(scroll, { scrollHeight: 1000, clientHeight: 400, scrollTop: 600 });
    const es = FakeEventSource.instances[0];
    act(() => {
      es.ready();
      es.log(makeLog("first", 1));
    });

    // Pretend the user scrolled to the middle of the buffer.
    geom.scrollTop = 200;
    fireEvent.scroll(scroll);
    expect(getFollowSwitch()).not.toBeChecked();

    // A new entry now arrives — we should NOT have been yanked to the bottom.
    act(() => {
      es.log(makeLog("second", 2));
    });
    expect(geom.scrollTop).toBe(200);
  });

  it("re-engages follow when the user scrolls back to the bottom", () => {
    renderWithProviders(<LogsPanel />);
    const scroll = getScroll();
    const geom = fakeLayout(scroll, { scrollHeight: 1000, clientHeight: 400, scrollTop: 600 });
    const es = FakeEventSource.instances[0];
    act(() => {
      es.ready();
      es.log(makeLog("first", 1));
    });

    // Scroll up → follow off.
    geom.scrollTop = 100;
    fireEvent.scroll(scroll);
    expect(getFollowSwitch()).not.toBeChecked();

    // Scroll back to the bottom (within threshold) → follow on again.
    geom.scrollTop = 600;
    fireEvent.scroll(scroll);
    expect(getFollowSwitch()).toBeChecked();

    // And new entries snap to the bottom again.
    act(() => {
      es.log(makeLog("second", 2));
    });
    expect(geom.scrollTop).toBe(1000);
  });

  it("manually toggling the switch on jumps to the bottom", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LogsPanel />);
    const scroll = getScroll();
    const geom = fakeLayout(scroll, { scrollHeight: 1000, clientHeight: 400, scrollTop: 600 });
    const es = FakeEventSource.instances[0];
    act(() => {
      es.ready();
      es.log(makeLog("first", 1));
    });

    // Scroll away from the bottom — follow toggles off automatically.
    geom.scrollTop = 50;
    fireEvent.scroll(scroll);
    expect(getFollowSwitch()).not.toBeChecked();

    // Tick the switch back on — should snap to the bottom even though the
    // user is still visually at the top.
    await user.click(getFollowSwitch());
    expect(getFollowSwitch()).toBeChecked();
    expect(geom.scrollTop).toBe(1000);
  });
});

describe("LogsPanel filter sizing", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("sizes the filter field via a CSS class, not inline styles, so the phone rule can win", () => {
    renderWithProviders(<LogsPanel />);

    const searchInput = screen.getByLabelText("Filter");
    const root = searchInput.closest(".mantine-TextInput-root") as HTMLElement;
    expect(root).not.toBeNull();

    // An inline min-width beats the @media (--bp-phone) stacking rule; sizing
    // must come from a stylesheet class instead.
    expect(root.style.minWidth).toBe("");
    expect(root).toHaveClass("logs-filter-search");
  });
});
