// studio_frontend/src/panels/useStudioPanelLayout.test.jsx
//
// 控制器逻辑回归：布局意图、最小化/恢复、最大化快照、以及"旧 RAF 回调
// 不能覆盖最新状态"的竞态。真实 Panel Group 的鼠标/键盘行为在 Chromium
// 浏览器测试里验证；这里用可观测的 fake handle 把调度顺序钉死。
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PANEL_LAYOUT_VERSION, panelStorageKey } from "./panelLayout";
import { useStudioPanelLayout } from "./useStudioPanelLayout";

function panelHandle() {
  return {
    collapse: vi.fn(),
    expand: vi.fn(),
    isCollapsed: () => false,
    getSize: () => ({ asPercentage: 0, inPixels: 0 }),
    resize: vi.fn(),
  };
}

function groupHandle(layout) {
  let current = { ...layout };
  const setLayout = vi.fn((next) => {
    current = { ...next };
    return next;
  });
  return {
    getLayout: () => ({ ...current }),
    setLayout,
    layout: () => ({ ...current }),
    /** 模拟库的 ResizeObserver/注册完成：Group 此刻才知道新 Panel。 */
    setPanels: (ids) => {
      for (const id of ids) {
        if (!(id in current)) current[id] = 0;
      }
      for (const id of Object.keys(current)) {
        if (!ids.includes(id)) delete current[id];
      }
    },
  };
}

let storage;

function stubEnvironment() {
  storage = new Map();
  vi.stubGlobal("window", {
    localStorage: {
      get length() {
        return storage.size;
      },
      clear: () => storage.clear(),
      getItem: (key) => storage.get(key) ?? null,
      key: (index) => [...storage.keys()][index] ?? null,
      removeItem: (key) => void storage.delete(key),
      setItem: (key, value) => void storage.set(key, value),
    },
  });
  vi.stubGlobal("requestAnimationFrame", (callback) => setTimeout(callback, 0));
  vi.stubGlobal("cancelAnimationFrame", (handle) => clearTimeout(handle));
}

function Harness({ fixture, available }) {
  fixture.controller = useStudioPanelLayout({
    scope: "project",
    groupRefs: {
      main: { current: fixture.mainGroup },
      workspace: { current: fixture.workspaceGroup },
    },
    panelRefs: {
      chat: { current: fixture.handles.chat },
      game: { current: fixture.handles.game },
      canvas: { current: fixture.handles.canvas },
      inspector: { current: fixture.handles.inspector },
      logs: { current: fixture.handles.logs },
      "workspace-main": { current: fixture.handles["workspace-main"] },
    },
    available,
  });
  return null;
}

const normalMain = { chat: 24.44, canvas: 51.11, inspector: 24.44, "main-spacer": 0 };
const normalWorkspace = { "workspace-main": 74, logs: 26, "workspace-spacer": 0 };

function mount(available, storedLayouts) {
  if (storedLayouts) {
    storage.set(
      panelStorageKey("project"),
      JSON.stringify({
        version: PANEL_LAYOUT_VERSION,
        layouts: storedLayouts,
        spans: { main: 1280, workspace: 800 },
        minimized: [],
      }),
    );
  }
  const fixture = {
    handles: {
      "workspace-main": panelHandle(),
      chat: panelHandle(),
      game: panelHandle(),
      canvas: panelHandle(),
      inspector: panelHandle(),
      logs: panelHandle(),
    },
    mainGroup: groupHandle(normalMain),
    workspaceGroup: groupHandle(normalWorkspace),
  };
  let tree;
  act(() => {
    tree = create(<Harness fixture={fixture} available={available} />);
  });
  return { tree, fixture };
}

async function settle(rounds = 8) {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 2));
    });
  }
}

function expectLayoutClose(layout, expected) {
  for (const [key, value] of Object.entries(expected)) {
    expect(layout[key]).toBeCloseTo(value, 1);
  }
}

function lastLayout(group) {
  const calls = group.setLayout.mock.calls;
  return calls.length > 0 ? calls[calls.length - 1][0] : undefined;
}

beforeEach(() => {
  stubEnvironment();
});

const all = ["workspace-main", "chat", "canvas", "inspector", "logs"];
const stored = {
  main: { chat: 24.44, canvas: 51.11, inspector: 24.44 },
  workspace: { "workspace-main": 74, logs: 26 },
};

describe("useStudioPanelLayout", () => {
  it("minimizes by zeroing the layout (never by collapsing a visible panel) and restores the stored size", async () => {
    const { fixture } = mount(all, stored);
    await settle();
    expectLayoutClose(lastLayout(fixture.mainGroup), normalMain);

    act(() => fixture.controller.minimize("chat"));
    await settle();
    expect(fixture.controller.minimized).toEqual(["chat"]);
    expect(fixture.handles.chat.collapse).not.toHaveBeenCalled();
    const minimizedLayout = lastLayout(fixture.mainGroup);
    expect(minimizedLayout.chat).toBe(0);
    expect(minimizedLayout.canvas).toBeGreaterThan(0);
    expect(minimizedLayout.inspector).toBeGreaterThan(0);
    const saved = JSON.parse(storage.get(panelStorageKey("project")));
    expect(saved.minimized).toEqual(["chat"]);

    act(() => fixture.controller.restore("chat"));
    await settle();
    expect(fixture.controller.minimized).toEqual([]);
    const restored = lastLayout(fixture.mainGroup);
    expect(restored.chat).toBeGreaterThan(20);
    expect(restored.canvas).toBeGreaterThan(restored.chat);
    expect(fixture.handles.chat.expand).not.toHaveBeenCalled();
  });

  it("keeps three panels recoverable at once and keeps their nominal sizes while hidden", async () => {
    const { fixture } = mount(all, stored);
    await settle();
    act(() => {
      fixture.controller.minimize("chat");
      fixture.controller.minimize("canvas");
      fixture.controller.minimize("inspector");
    });
    await settle();
    expect(fixture.controller.minimized).toEqual(["chat", "canvas", "inspector"]);
    expect(lastLayout(fixture.mainGroup)["main-spacer"]).toBe(100);

    act(() => fixture.controller.restore("canvas"));
    await settle();
    expect(fixture.controller.minimized).toEqual(["chat", "inspector"]);
    const afterCanvas = lastLayout(fixture.mainGroup);
    expect(afterCanvas.canvas).toBeGreaterThan(0);
    expect(afterCanvas.chat).toBe(0);
    expect(afterCanvas.inspector).toBe(0);

    act(() => fixture.controller.restore("chat"));
    act(() => fixture.controller.restore("inspector"));
    await settle();
    expect(fixture.controller.minimized).toEqual([]);
    expectLayoutClose(lastLayout(fixture.mainGroup), normalMain);
  });

  it("maximizes by snapshotting and restores the exact pre-maximize layout", async () => {
    const { fixture } = mount(all, stored);
    await settle();
    act(() => fixture.controller.toggleMaximize("inspector"));
    await settle();

    expect(fixture.controller.maximized).toBe("inspector");
    expect(lastLayout(fixture.mainGroup)).toEqual(
      expect.objectContaining({ inspector: 100, chat: 0, canvas: 0 }),
    );
    expect(lastLayout(fixture.workspaceGroup)).toEqual(
      expect.objectContaining({ "workspace-main": 100, logs: 0 }),
    );
    expect(fixture.controller.minimized).toEqual([]);

    act(() => fixture.controller.exitMaximize());
    await settle();
    expect(fixture.controller.maximized).toBeNull();
    expectLayoutClose(lastLayout(fixture.mainGroup), normalMain);
    expectLayoutClose(lastLayout(fixture.workspaceGroup), normalWorkspace);
  });

  it("cancels stale layout callbacks so a late RAF cannot undo maximize", async () => {
    const { fixture } = mount(all, stored);
    // 不等首次布局落盘就最大化：旧的规范布局任务仍挂在 setTimeout 队列里。
    act(() => fixture.controller.toggleMaximize("inspector"));
    await settle();

    expect(fixture.controller.maximized).toBe("inspector");
    // 如果旧回调还在写，会看到 24.44/51.11/24.44 之类的正常布局。
    expect(lastLayout(fixture.mainGroup)).toEqual({
      chat: 0,
      canvas: 0,
      inspector: 100,
      "main-spacer": 0,
    });
    expect(fixture.mainGroup.layout()).toEqual(
      expect.objectContaining({ inspector: 100, chat: 0, canvas: 0 }),
    );
  });

  it("never writes a layout for panels the Group has not registered yet", async () => {
    const withoutGame = ["workspace-main", "chat", "canvas", "inspector", "logs"];
    const { fixture, tree } = mount(withoutGame, stored);
    await settle();

    const liveLayout = fixture.mainGroup.getLayout;
    const setLayout = fixture.mainGroup.setLayout;
    let visible = liveLayout();
    let laggingReads = 3;
    let lastRead = { ...visible };
    const mismatchedWrites = [];
    const writes = [];
    fixture.mainGroup.getLayout = () => {
      if (laggingReads === 0 && !("game" in visible)) {
        visible = { ...visible, game: 0 };
      }
      if (laggingReads > 0) laggingReads -= 1;
      lastRead = { ...visible };
      return { ...visible };
    };
    fixture.mainGroup.setLayout = (next) => {
      // 库没有 game 时会直接抛 Invalid N panel layout；控制器必须先跳过。
      if (Object.keys(next).length !== Object.keys(lastRead).length) {
        mismatchedWrites.push(next);
      }
      writes.push(next);
      visible = { ...next };
      return setLayout(next);
    };

    act(() => {
      tree.update(<Harness fixture={fixture} available={[...withoutGame, "game"]} />);
    });
    await settle();

    expect(mismatchedWrites).toEqual([]);
    expect(writes.length).toBeGreaterThan(0);
    expect(writes[writes.length - 1]).toEqual(
      expect.objectContaining({ game: expect.any(Number) }),
    );
  });

  it("re-applies the maximize layout when Play enters or leaves, and exits when its target unmounts", async () => {
    const withoutGame = ["workspace-main", "chat", "canvas", "inspector", "logs"];
    const { fixture, tree } = mount(all, stored);
    await settle();
    act(() => fixture.controller.toggleMaximize("inspector"));
    await settle();

    // 最大化期间进入 Play：game 挂载，但必须保持 0 尺寸。
    act(() => {
      tree.update(<Harness fixture={fixture} available={[...withoutGame, "game"]} />);
    });
    fixture.mainGroup.setPanels(["chat", "canvas", "inspector", "game", "main-spacer"]);
    await settle();
    expect(fixture.controller.maximized).toBe("inspector");
    expect(lastLayout(fixture.mainGroup)).toEqual({
      chat: 0,
      canvas: 0,
      inspector: 100,
      game: 0,
      "main-spacer": 0,
    });
    expect(lastLayout(fixture.mainGroup).game).toBe(0);

    // 退出最大化后 game 仍然可见（Play 未结束）。
    act(() => fixture.controller.exitMaximize());
    await settle();
    expect(lastLayout(fixture.mainGroup).game).toBeGreaterThan(0);

    // 最大化 Play 期间停止 Play：目标卸载，必须自动退出最大化。
    act(() => fixture.controller.toggleMaximize("game"));
    await settle();
    expect(fixture.controller.maximized).toBe("game");
    act(() => {
      tree.update(<Harness fixture={fixture} available={withoutGame} />);
    });
    fixture.mainGroup.setPanels(["chat", "canvas", "inspector", "main-spacer"]);
    await settle();
    expect(fixture.controller.maximized).toBeNull();
    expect(lastLayout(fixture.mainGroup).inspector).toBeGreaterThan(0);
  });

  it("maximized Execution Logs hides the horizontal workspace without touching its layout", async () => {
    const { fixture } = mount(all, stored);
    await settle();
    act(() => fixture.controller.toggleMaximize("logs"));
    await settle();
    expect(lastLayout(fixture.workspaceGroup)).toEqual(
      expect.objectContaining({ logs: 100, "workspace-main": 0 }),
    );
    // 横向 Group 的布局保持原样，恢复时不需要重建。
    expectLayoutClose(lastLayout(fixture.mainGroup), normalMain);
    expect(fixture.controller.isHidden("workspace-main")).toBe(true);
    expect(fixture.controller.isHidden("chat")).toBe(true);
  });

  it("maximizing a main panel keeps the structural container visible", async () => {
    const { fixture } = mount(all, stored);
    await settle();
    act(() => fixture.controller.toggleMaximize("chat"));
    await settle();
    expect(fixture.controller.isHidden("workspace-main")).toBe(false);
    expect(fixture.controller.isHidden("logs")).toBe(true);
    expect(fixture.controller.isHidden("chat")).toBe(false);
  });

  it("restores a minimized panel when it is maximized, and clears it from the dock", async () => {
    const { fixture } = mount(all, stored);
    await settle();
    act(() => fixture.controller.minimize("canvas"));
    await settle();
    act(() => fixture.controller.toggleMaximize("canvas"));
    await settle();
    expect(fixture.controller.maximized).toBe("canvas");
    expect(fixture.controller.minimized).toEqual([]);
    expectLayoutClose(lastLayout(fixture.mainGroup), { canvas: 100, chat: 0, inspector: 0 });
  });

  it("applies a persisted minimized panel on mount", async () => {
    storage.set(
      panelStorageKey("project"),
      JSON.stringify({
        version: PANEL_LAYOUT_VERSION,
        layouts: stored,
        minimized: ["inspector"],
      }),
    );
    const { fixture } = mount(all);
    await settle();
    expect(fixture.controller.minimized).toEqual(["inspector"]);
    expect(fixture.handles.inspector.collapse).not.toHaveBeenCalled();
    expect(lastLayout(fixture.mainGroup).inspector).toBe(0);
  });

  it("clamps a visible panel back to its minimum when the library tries to collapse it", async () => {
    const { fixture } = mount(all, stored);
    await settle();
    act(() =>
      fixture.controller.onLayoutChange("main", {
        chat: 0,
        canvas: 60,
        inspector: 40,
        "main-spacer": 0,
      }),
    );
    expect(fixture.controller.minimized).toEqual([]);
    const clamped = lastLayout(fixture.mainGroup);
    expect(clamped.chat).toBeGreaterThan(0);
    expect(clamped.chat + clamped.canvas + clamped.inspector).toBeCloseTo(100, 1);

    act(() =>
      fixture.controller.onLayoutChange("workspace", {
        "workspace-main": 0,
        logs: 100,
        "workspace-spacer": 0,
      }),
    );
    const vertical = lastLayout(fixture.workspaceGroup);
    expect(vertical["workspace-main"]).toBeGreaterThan(0);
    expect(vertical["workspace-main"] + vertical.logs).toBeCloseTo(100, 1);
    expect(fixture.controller.minimized).toEqual([]);
  });

  it("seeds nominal sizes from the live layout before the first minimize", async () => {
    const { fixture } = mount(all);
    await settle();
    act(() => fixture.controller.minimize("canvas"));
    await settle();
    act(() =>
      fixture.controller.onLayoutChanged(
        "main",
        { chat: 45, canvas: 0, inspector: 55, "main-spacer": 0 },
        { isUserInteraction: true },
      ),
    );
    const saved = JSON.parse(storage.get(panelStorageKey("project")));
    expect(saved.layouts.main.canvas).toBeGreaterThan(0);
    expect(saved.layouts.main.chat).toBeGreaterThan(0);
    expect(saved.layouts.main.inspector).toBeGreaterThan(0);
  });

  it("persists only user-driven sizes and keeps hidden panels' nominal sizes", async () => {
    const { fixture } = mount(all, stored);
    await settle();
    act(() => fixture.controller.minimize("canvas"));
    await settle();
    // 中间 Panel 最小化后，用户在 Chat/Inspector 之间拖动。
    act(() =>
      fixture.controller.onLayoutChanged(
        "main",
        { chat: 40, canvas: 0, inspector: 60, "main-spacer": 0 },
        { isUserInteraction: true },
      ),
    );
    const saved = JSON.parse(storage.get(panelStorageKey("project")));
    expect(saved.layouts.main.canvas).toBeCloseTo(51.11, 1);
    expect(saved.layouts.main.chat).toBeGreaterThan(15);
    expect(saved.layouts.main.inspector).toBeGreaterThan(15);

    act(() => fixture.controller.restore("canvas"));
    await settle();
    expect(lastLayout(fixture.mainGroup).canvas).toBeGreaterThan(30);
  });
});
