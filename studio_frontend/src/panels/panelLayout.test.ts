// studio_frontend/src/panels/panelLayout.test.ts
import { describe, expect, it } from "vitest";
import {
  PANEL_LAYOUT_VERSION,
  addMinimized,
  emptyPanelState,
  enforceMinimumPercentages,
  layoutForPanels,
  preferredPanelLayout,
  isPanelHidden,
  loadPanelState,
  normalizePanelState,
  panelMinSpan,
  panelResizeBehavior,
  panelStorageKey,
  removeMinimized,
  savePanelState,
  withSpacer,
  type PersistedPanelState,
} from "./panelLayout";

function fakeStorage(): Storage {
  const data = new Map<string, string>();
  return {
    get length() {
      return data.size;
    },
    clear: () => data.clear(),
    getItem: (key) => data.get(key) ?? null,
    key: (index) => [...data.keys()][index] ?? null,
    removeItem: (key) => void data.delete(key),
    setItem: (key, value) => void data.set(key, value),
  };
}

describe("normalizePanelState", () => {
  it("drops unknown versions and malformed layouts instead of locking the UI", () => {
    expect(normalizePanelState({ version: 999, minimized: ["chat"] })).toEqual(emptyPanelState());
    expect(normalizePanelState(null)).toEqual(emptyPanelState());
    expect(
      normalizePanelState({
        version: PANEL_LAYOUT_VERSION,
        layouts: { main: { chat: Number.NaN } },
        minimized: ["nope", "workspace-main", "chat", "chat"],
      }),
    ).toEqual({
      version: PANEL_LAYOUT_VERSION,
      layouts: {},
      spans: {},
      minimized: ["chat"],
    });
  });

  it("keeps valid layouts but rejects out-of-range sizes", () => {
    const state = normalizePanelState({
      version: PANEL_LAYOUT_VERSION,
      layouts: { main: { chat: 25, canvas: 50, inspector: 25 }, workspace: { logs: 101 } },
      minimized: [],
    });
    expect(state.layouts.main).toEqual({ chat: 25, canvas: 50, inspector: 25 });
    expect(state.layouts.workspace).toBeUndefined();
  });
});

describe("layoutForPanels", () => {
  it("renormalizes after a conditional panel (Play) disappears", () => {
    const layout = layoutForPanels(
      { chat: 20, game: 25, canvas: 35, inspector: 20 },
      ["chat", "canvas", "inspector"],
    );
    expect(layout).toBeDefined();
    expect(Object.values(layout!).reduce((sum, value) => sum + value, 0)).toBeCloseTo(100);
    expect(layout!.chat).toBeCloseTo((20 / 75) * 100);
  });

  it("rejects layouts missing a currently visible panel", () => {
    expect(layoutForPanels({ chat: 50, canvas: 50 }, ["chat", "canvas", "inspector"])).toBeUndefined();
    expect(layoutForPanels(undefined, ["chat"])).toBeUndefined();
  });
});

describe("panel persistence", () => {
  it("round-trips minimized ids and layouts through the versioned key", () => {
    const storage = fakeStorage();
    const state: PersistedPanelState = {
      version: PANEL_LAYOUT_VERSION,
      layouts: { main: { chat: 30, canvas: 40, inspector: 30 } },
      spans: { main: 1280 },
      minimized: ["inspector", "logs"],
    };
    savePanelState("project", state, storage);
    expect(storage.getItem(panelStorageKey("project"))).toBeTruthy();
    expect(loadPanelState("project", storage)).toEqual(state);
    expect(loadPanelState("agent-team", storage)).toEqual(emptyPanelState());
  });

  it("survives unavailable storage", () => {
    const storage = fakeStorage();
    storage.getItem = () => {
      throw new Error("denied");
    };
    expect(loadPanelState("project", storage)).toEqual(emptyPanelState());
    const broken = fakeStorage();
    broken.setItem = () => {
      throw new Error("quota");
    };
    expect(() => savePanelState("project", emptyPanelState(), broken)).not.toThrow();
  });
});

describe("minimized list helpers", () => {
  it("is idempotent in both directions", () => {
    const base = emptyPanelState();
    const once = addMinimized(base, "chat");
    expect(addMinimized(once, "chat")).toBe(once);
    expect(removeMinimized(once, "chat")).toEqual(base);
    expect(removeMinimized(base, "chat")).toBe(base);
  });
});

describe("minimum percentages", () => {
  const ids = ["chat", "canvas", "inspector"] as const;

  it("lifts every panel to its shell minimum at the group's minimum span", () => {
    const layout = enforceMinimumPercentages({ chat: 1, canvas: 98, inspector: 1 }, ids)!;
    const span = panelMinSpan(ids);
    expect(layout.chat).toBeGreaterThanOrEqual((260 / span) * 100 - 1e-6);
    expect(layout.canvas).toBeGreaterThanOrEqual((360 / span) * 100 - 1e-6);
    expect(layout.inspector).toBeGreaterThanOrEqual((260 / span) * 100 - 1e-6);
    expect(Object.values(layout).reduce((sum, value) => sum + value, 0)).toBeCloseTo(100);
  });

  it("does not rewrite a saved layout that is valid at the measured width", () => {
    const saved = { chat: 37, canvas: 34, inspector: 29 };
    const layout = enforceMinimumPercentages(saved, ids, "horizontal", 1274)!;
    expect(layout).toEqual(saved);
  });

  it("prefers a wide canvas and keeps the Inspector usable", () => {
    const layout = preferredPanelLayout(ids)!;
    expect(layout.canvas).toBeGreaterThan(layout.chat);
    expect(layout.inspector).toBeGreaterThanOrEqual((260 / panelMinSpan(ids)) * 100 - 1e-6);
  });

  it("appends the trailing spacer at zero so the last panel can collapse", () => {
    expect(withSpacer({ chat: 50, canvas: 50 }, "main-spacer")).toEqual({
      chat: 50,
      canvas: 50,
      "main-spacer": 0,
    });
    expect(withSpacer(undefined, "main-spacer")).toBeUndefined();
  });
});

describe("isPanelHidden", () => {
  it("treats minimized panels as hidden", () => {
    expect(isPanelHidden("chat", ["chat"], null)).toBe(true);
    expect(isPanelHidden("chat", [], null)).toBe(false);
  });

  it("hides siblings of the maximized panel within its own group", () => {
    expect(isPanelHidden("chat", [], "inspector")).toBe(true);
    expect(isPanelHidden("inspector", [], "inspector")).toBe(false);
  });

  it("keeps workspace-main visible while a panel inside it is maximized", () => {
    expect(isPanelHidden("workspace-main", [], "chat")).toBe(false);
    expect(isPanelHidden("logs", [], "chat")).toBe(true);
  });

  it("hides the whole horizontal workspace while Execution Logs is maximized", () => {
    expect(isPanelHidden("workspace-main", [], "logs")).toBe(true);
    expect(isPanelHidden("chat", [], "logs")).toBe(true);
    expect(isPanelHidden("logs", [], "logs")).toBe(false);
  });
});

describe("resize behavior under window resize", () => {
  it("keeps hidden panels on a pixel strategy so zero stays zero", () => {
    // 库在 Group 变大时会把剩余百分比均分给所有 0 尺寸的 relative Panel；
    // 隐藏 Panel 必须走 pixel，否则最小化/被最大化挤走的 Panel 会重新长宽。
    expect(panelResizeBehavior("preserve-relative-size", { hidden: true, maximized: false })).toBe(
      "preserve-pixel-size",
    );
    expect(panelResizeBehavior("preserve-pixel-size", { hidden: true, maximized: false })).toBe(
      "preserve-pixel-size",
    );
  });

  it("keeps a maximized panel relative so 100% stays 100%", () => {
    expect(panelResizeBehavior("preserve-pixel-size", { hidden: false, maximized: true })).toBe(
      "preserve-relative-size",
    );
    expect(panelResizeBehavior("preserve-relative-size", { hidden: false, maximized: true })).toBe(
      "preserve-relative-size",
    );
  });

  it("leaves visible, non-maximized panels on their normal strategy", () => {
    expect(panelResizeBehavior("preserve-pixel-size", { hidden: false, maximized: false })).toBe(
      "preserve-pixel-size",
    );
    expect(panelResizeBehavior("preserve-relative-size", { hidden: false, maximized: false })).toBe(
      "preserve-relative-size",
    );
    // 理论上不会同时出现；隐藏优先，避免 100% 落在 inert 区域。
    expect(panelResizeBehavior("preserve-relative-size", { hidden: true, maximized: true })).toBe(
      "preserve-pixel-size",
    );
  });
});

describe("minimum spans", () => {
  it("sums shell minimums plus separators", () => {
    expect(panelMinSpan(["agent-sidebar", "agent-chat"])).toBe(240 + 360 + 6);
    expect(panelMinSpan([])).toBe(0);
  });

});
