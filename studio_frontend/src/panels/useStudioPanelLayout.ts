// studio_frontend/src/panels/useStudioPanelLayout.ts
//
// 共享的 Panel Layout Controller。
//
// 设计要点：
//
// 1. **Resize 和 Minimize 是两个操作。** 库的 `collapsible` 会让用户把
//    Panel 拖过 `minSize / 2` 时直接折叠成 0（鼠标和键盘都会）。折叠能力
//    必须保留（程序化最小化/最大化要写 0），所以 onLayoutChange 会在库
//    同步发出布局、浏览器重绘之前，把任何**可见** Panel 按 minimum
//    width/height 夹回来。`workspace-main` 这类结构容器同样不会被用户
//    拖没，只有控制器最大化 Logs 时才允许程序化收起。
//
// 2. **布局只由一个"意图"驱动。** 状态变化（最小化、恢复、最大化、
//    Play 进入/退出）会让控制器重新调度一份规范布局。每个 Group 只保留
//    最新一次调度，旧任务（包括其嵌套 RAF）在下一个版本号出现时立即作废，
//    因此 Maximize 不会被上一帧遗留的布局回调覆盖。
//
// 3. **组件保持挂载。** 最小化只是把尺寸写成 0 + inert，聊天草稿、ReactFlow
//    视角、Play 会话都不会被重置。
//
// 4. 只有用户拖动/键盘 Resize（meta.isUserInteraction）才把新尺寸写进
//    localStorage；最小化前会先把"当前实际尺寸"落成标称布局，确保隐藏
//    Panel 恢复时还能回到原来的大小，程序化布局不会覆盖用户保存的尺寸。
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type RefObject,
} from "react";
import type {
  GroupImperativeHandle,
  Layout,
  LayoutChangedMeta,
  PanelImperativeHandle,
} from "react-resizable-panels";
import {
  STUDIO_PANEL_SPECS,
  addMinimized,
  enforceMinimumPercentages,
  groupPanelIds,
  isPanelHidden,
  layoutForPanels,
  loadPanelState,
  panelMinSpan,
  preferredPanelLayout,
  removeMinimized,
  savePanelState,
  withSpacer,
  type PanelGroupId,
  type PanelScope,
  type PersistedPanelState,
  type StudioPanelId,
} from "./panelLayout";

const SPACER_IDS: Record<PanelGroupId, string> = {
  main: "main-spacer",
  workspace: "workspace-spacer",
  agent: "agent-spacer",
};

const GROUP_ORIENTATION: Record<PanelGroupId, "horizontal" | "vertical"> = {
  main: "horizontal",
  workspace: "vertical",
  agent: "horizontal",
};

const GROUPS: readonly PanelGroupId[] = ["main", "workspace", "agent"];

const LAYOUT_EPSILON = 0.01;

type GroupRef = RefObject<GroupImperativeHandle | null>;
type PanelRef = RefObject<PanelImperativeHandle | null>;

export interface StudioPanelLayoutOptions {
  scope: PanelScope;
  groupRefs: Partial<Record<PanelGroupId, GroupRef>>;
  panelRefs: Partial<Record<StudioPanelId, PanelRef>>;
  /** 当前实际挂载的 Panel（game 只在 Play 时存在）。包含结构容器。 */
  available: readonly StudioPanelId[];
}

export interface StudioPanelLayoutController {
  minimized: StudioPanelId[];
  maximized: StudioPanelId | null;
  isMinimized: (id: StudioPanelId) => boolean;
  /** 该 Panel 此刻是否不可见（被最小化，或被另一个 Panel 的最大化挤走）。 */
  isHidden: (id: StudioPanelId) => boolean;
  defaultLayout: (
    group: PanelGroupId,
    panelIds: readonly StudioPanelId[],
    orientation?: "horizontal" | "vertical",
    referenceSpan?: number,
    spacerId?: string,
  ) => Layout | undefined;
  /** 布局容器的最小像素尺寸：保存布局时的宽度，用于窄屏横向滚动。 */
  groupMinSpan: (
    group: PanelGroupId,
    panelIds: readonly StudioPanelId[],
    orientation?: "horizontal" | "vertical",
  ) => number;
  /**
   * 每次布局变化（拖动过程中每帧）都会调用。可见 Panel 被用户拖到
   * 折叠阈值以下时，这里立刻按最小尺寸把它夹回来——库的 `collapsible`
   * 仍处于打开状态，所以程序化最小化/最大化不受影响，但 Resize 永远不会
   * "顺手"把 Panel 丢进 Dock。
   */
  onLayoutChange: (group: PanelGroupId, layout: Layout) => void;
  onLayoutChanged: (
    group: PanelGroupId,
    layout: Layout,
    meta: LayoutChangedMeta,
  ) => void;
  minimize: (id: StudioPanelId) => void;
  restore: (id: StudioPanelId) => void;
  toggleMaximize: (id: StudioPanelId) => void;
  exitMaximize: () => void;
}

function layoutsMatch(a: Layout, b: Layout): boolean {
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  for (const key of bKeys) {
    if (typeof a[key] !== "number") return false;
    if (Math.abs(a[key] - b[key]) > LAYOUT_EPSILON) return false;
  }
  return true;
}

/**
 * 两个布局描述的是不是同一批 Panel。Play 进入/退出时新 Panel 的注册与
 * 控制器写布局可能落在同一批 effect 里：库还没把 game 计入 Group 时
 * setLayout 会直接抛 "Invalid N panel layout"。遇到这种过渡态就跳过，
 * 由下一帧的调度重试。
 */
function samePanelSet(a: Layout, b: Layout): boolean {
  const aKeys = Object.keys(a);
  const bKeys = Object.keys(b);
  if (aKeys.length !== bKeys.length) return false;
  return bKeys.every((key) => key in a);
}

/** 把布局按当前总和归一化到 100%；0 尺寸保持为 0。 */
function normalizeLayout(layout: Layout): Layout {
  const total = Object.values(layout).reduce((sum, value) => sum + value, 0);
  if (total <= 0) return { ...layout };
  const next: Layout = {};
  for (const [id, value] of Object.entries(layout)) {
    next[id] = (value / total) * 100;
  }
  return next;
}

/**
 * 最小化的 Panel 在布局里是 0，但**保存**时不能把它写成 0——否则恢复时
 * 就只剩最小尺寸。把隐藏 Panel 上次的标称尺寸填回去，再把可见 Panel 的
 * 比例缩放到剩余空间，保存的始终是一份完整、总和 100% 的"正常布局"。
 */
function mergeHiddenPanels(
  ids: readonly StudioPanelId[],
  layout: Layout,
  previous: Layout | undefined,
): Layout {
  const next: Layout = {};
  const visible: StudioPanelId[] = [];
  let fixedTotal = 0;
  let visibleTotal = 0;
  for (const id of ids) {
    const value = layout[id] ?? 0;
    if (value <= 0.05) {
      const prior = previous?.[id];
      const keep = typeof prior === "number" && prior > 0.05 ? prior : 0;
      next[id] = keep;
      fixedTotal += keep;
    } else {
      visible.push(id);
      visibleTotal += value;
    }
  }
  const available = Math.max(0, 100 - fixedTotal);
  for (const id of visible) {
    next[id] =
      visibleTotal > 0
        ? ((layout[id] ?? 0) / visibleTotal) * available
        : available / visible.length;
  }
  return next;
}

/**
 * 按当前 Panel 集合过滤布局。与 `layoutForPanels` 不同，允许快照里缺少
 * 新挂载的 Panel（例如最大化期间开始 Play 多出 game）：缺失项按 0 处理，
 * 之后由最小尺寸下限抬回可操作尺寸。
 */
function filterLayout(layout: Layout, ids: readonly StudioPanelId[]): Layout | undefined {
  const total = ids.reduce((sum, id) => sum + (layout[id] ?? 0), 0);
  if (total <= 0) return undefined;
  const next: Layout = {};
  for (const id of ids) next[id] = ((layout[id] ?? 0) / total) * 100;
  return next;
}

/** 给 Group 的布局补上末尾占位 Panel（保持 DOM 顺序）。 */
function withSpacerLayout(
  layout: Layout,
  spacerId: string,
  minimized: readonly StudioPanelId[],
): Layout {
  const next: Layout = { ...layout };
  for (const id of minimized) {
    if (id in next) next[id] = 0;
  }
  const total = Object.values(next).reduce((sum, value) => sum + value, 0);
  next[spacerId] = total > 0 ? 0 : 100;
  return next;
}

function maximizedGroupLayout(
  ids: readonly StudioPanelId[],
  target: StudioPanelId,
  spacerId: string,
): Layout {
  const layout: Layout = {};
  for (const id of ids) layout[id] = id === target ? 100 : 0;
  layout[spacerId] = 0;
  return layout;
}

export function useStudioPanelLayout(
  options: StudioPanelLayoutOptions,
): StudioPanelLayoutController {
  const { scope, groupRefs, panelRefs, available } = options;
  const [initial] = useState<PersistedPanelState>(() => loadPanelState(scope));
  const [minimized, setMinimized] = useState<StudioPanelId[]>(initial.minimized);
  const [maximized, setMaximized] = useState<StudioPanelId | null>(null);
  const [spans, setSpans] = useState<Partial<Record<PanelGroupId, number>>>(initial.spans);

  const layoutsRef = useRef<Partial<Record<PanelGroupId, Layout>>>(initial.layouts);
  const stateRef = useRef<PersistedPanelState>(initial);
  const minimizedRef = useRef<StudioPanelId[]>(initial.minimized);
  const maximizedRef = useRef<StudioPanelId | null>(null);
  const snapshotRef = useRef<Partial<Record<PanelGroupId, Layout>> | null>(null);
  const availableRef = useRef<readonly StudioPanelId[]>(available);
  const spansRef = useRef<Partial<Record<PanelGroupId, number>>>(initial.spans);
  const versionRef = useRef(0);
  const applyingRef = useRef(false);
  const pendingRef = useRef<Partial<Record<PanelGroupId, () => void>>>({});
  const availableKey = available.join(",");
  const minimizedKey = minimized.join(",");

  availableRef.current = available;

  const commit = useCallback(
    (next: PersistedPanelState) => {
      stateRef.current = next;
      savePanelState(scope, next);
    },
    [scope],
  );

  const setMinimizedState = useCallback(
    (next: StudioPanelId[]) => {
      minimizedRef.current = next;
      setMinimized(next);
      commit({ ...stateRef.current, minimized: next });
    },
    [commit],
  );

  const setMaximizedState = useCallback((next: StudioPanelId | null) => {
    maximizedRef.current = next;
    setMaximized(next);
  }, []);

  const measureSpan = useCallback(
    (group: PanelGroupId): number | undefined => {
      for (const id of availableRef.current) {
        if (STUDIO_PANEL_SPECS[id].group !== group) continue;
        const size = panelRefs[id]?.current?.getSize();
        if (!size || size.inPixels <= 0 || size.asPercentage <= 0.05) continue;
        return size.inPixels / (size.asPercentage / 100);
      }
      return undefined;
    },
    [panelRefs],
  );

  /**
   * 用户交互后的规范化存储：可见 Panel 用新尺寸，隐藏 Panel 保留上次的
   * 标称尺寸。这样"最小化 → 拖动剩余 Panel → 恢复"不会把中间 Panel
   * 永久压成最小尺寸，最大化前的快照也不会丢掉被隐藏的尺寸。
   */
  const buildStoredLayout = useCallback(
    (group: PanelGroupId, layout: Layout): Layout | undefined => {
      const ids = groupPanelIds(group, availableRef.current);
      if (ids.length === 0) return undefined;
      const filtered = filterLayout(layout, ids);
      if (!filtered) return undefined;
      return mergeHiddenPanels(ids, filtered, layoutsRef.current[group]);
    },
    [],
  );

  /**
   * 退出最大化：把快照并回"正常布局"。被最大化临时收成 0 的 Panel 用快照
   * 里的原始比例恢复；快照里本来就是 0（最小化）的 Panel 保留标称尺寸。
   */
  const restoreSnapshotIntoLayouts = useCallback(() => {
    const snapshot = snapshotRef.current;
    snapshotRef.current = null;
    if (!snapshot) return;
    for (const group of GROUPS) {
      const layout = snapshot[group];
      if (!layout) continue;
      const merged = buildStoredLayout(group, layout);
      if (merged) {
        layoutsRef.current = { ...layoutsRef.current, [group]: merged };
      }

    }
  }, [buildStoredLayout]);

  const spanFrameCancelRef = useRef<Partial<Record<PanelGroupId, () => void>>>({});

  /**
   * 测量 Group 的真实像素跨度必须等这一帧的 flex 布局落地。
   * 键盘 Resize 会在 keydown 里同步触发 onLayoutChanged——那时 DOM 还是
   * 上一份布局，直接量 Panel 会得到"新百分比 + 旧像素"的假跨度，把
   * `groupMinSpan` 撑成离谱的宽度（曾经把 1280 的组量成 3064）。
   */
  const scheduleSpanMeasure = useCallback(
    (group: PanelGroupId) => {
      spanFrameCancelRef.current[group]?.();
      const schedule =
        typeof requestAnimationFrame === "function"
          ? requestAnimationFrame
          : (callback: () => void) => setTimeout(callback, 0) as unknown as number;
      const cancelSchedule =
        typeof cancelAnimationFrame === "function"
          ? cancelAnimationFrame
          : (handle: number) => clearTimeout(handle);
      const handle = schedule(() => {
        delete spanFrameCancelRef.current[group];
        if (maximizedRef.current) return;
        const measured = measureSpan(group);
        if (!measured || !Number.isFinite(measured) || measured <= 0) return;
        const rounded = Math.round(measured);
        if (Math.abs((spansRef.current[group] ?? 0) - rounded) < 2) return;
        const nextSpans = { ...spansRef.current, [group]: rounded };
        spansRef.current = nextSpans;
        setSpans(nextSpans);
        commit({ ...stateRef.current, spans: nextSpans });
      });
      spanFrameCancelRef.current[group] = () => cancelSchedule(handle);
    },
    [commit, measureSpan],
  );

  /**
   * 拖动/键盘 Resize 把可见 Panel 压到折叠阈值以下时，库会把它写成交互
   * 折叠（0）。这里在库同步发出布局变化、浏览器还没重绘之前，用最小尺寸
   * 夹回去：Resize 只能缩到 minimum width/height，Minimize 只由按钮触发。
   */
  const onLayoutChange = useCallback(
    (group: PanelGroupId, layout: Layout) => {
      if (applyingRef.current || maximizedRef.current) return;
      const ids = groupPanelIds(group, availableRef.current);
      if (ids.length === 0) return;
      const minimizedIds = minimizedRef.current;
      const visibleIds = ids.filter((id) => !minimizedIds.includes(id));
      const collapsed = visibleIds.some((id) => (layout[id] ?? 0) <= 0.05);
      if (!collapsed) return;
      const orientation = GROUP_ORIENTATION[group];
      const span = Math.max(spansRef.current[group] ?? 0, measureSpan(group) ?? 0);
      const visibleLayout: Layout = {};
      for (const id of visibleIds) visibleLayout[id] = layout[id] ?? 0;
      const clamped = enforceMinimumPercentages(
        visibleLayout,
        visibleIds,
        orientation,
        span > 0 ? span : undefined,
      );
      if (!clamped) return;
      const next: Layout = { ...clamped };
      for (const id of ids) {
        if (!visibleIds.includes(id)) next[id] = 0;
      }
      const handle = groupRefs[group]?.current;
      if (!handle) return;
      const nextLayout = normalizeLayout(
        withSpacerLayout(next, SPACER_IDS[group], minimizedIds),
      );
      const live = handle.getLayout();
      if (!live || !samePanelSet(live, nextLayout)) return;
      applyingRef.current = true;
      try {
        handle.setLayout(nextLayout);
      } finally {
        applyingRef.current = false;
      }
    },
    [groupRefs, measureSpan],
  );

  const onLayoutChanged = useCallback(
    (group: PanelGroupId, layout: Layout, meta: LayoutChangedMeta) => {
      // 最大化期间的收起/恢复不是用户意图，不能覆盖保存的尺寸。

      if (!meta.isUserInteraction || maximizedRef.current) return;
      const saved = buildStoredLayout(group, layout);
      if (!saved) return;
      const nextLayouts = { ...layoutsRef.current, [group]: saved };
      layoutsRef.current = nextLayouts;
      commit({ ...stateRef.current, layouts: nextLayouts });
      scheduleSpanMeasure(group);
    },
    [buildStoredLayout, commit, scheduleSpanMeasure],
  );

  /**
   * 当前意图下的规范布局。`null` 表示这个 Group 不需要改动（例如最大化
   * 主工作区 Panel 时，主 Group 之外的结构 Group 保持原样）。
   */
  const computeDesiredLayout = useCallback(
    (group: PanelGroupId): Layout | undefined => {
      const ids = groupPanelIds(group, availableRef.current);
      if (ids.length === 0) return undefined;
      const spacerId = SPACER_IDS[group];
      const target = maximizedRef.current;
      if (target) {
        if (ids.includes(target)) {
          return maximizedGroupLayout(ids, target, spacerId);
        }
        if (STUDIO_PANEL_SPECS[target].group === "main" && group === "workspace") {
          // 主工作区最大化时 Logs 收起，横向容器吃掉全部高度。
          return maximizedGroupLayout(ids, "workspace-main", spacerId);
        }
        // 最大化 Logs 时横向 Group 被父容器隐藏，但保留自己的布局；
        // 最大化 Agent Panel 时其他 Group 根本不挂载。
        return undefined;
      }

      const orientation = GROUP_ORIENTATION[group];
      // 垂直 Group 没有行内 minWidth 那种"保存跨度"来源，必须用当前实测
      // 高度算最小百分比；否则 140px 的 Logs 会被当成 386px 组里的 36%。
      const floorSpan = Math.max(
        spansRef.current[group] ?? 0,
        measureSpan(group) ?? 0,
      );
      const stored = layoutForPanels(layoutsRef.current[group], ids);
      const base = stored
        ? enforceMinimumPercentages(stored, ids, orientation, floorSpan)
        : preferredPanelLayout(ids, orientation, floorSpan);
      if (!base) return undefined;
      return normalizeLayout(
        withSpacerLayout(base, spacerId, minimizedRef.current),
      );
    },
    [measureSpan],
  );

  const scheduleApply = useCallback(
    (group: PanelGroupId, version: number) => {
      pendingRef.current[group]?.();
      let cancelled = false;
      let frame: number | null = null;
      let attempts = 0;
      let applied = false;
      let stableChecks = 0;

      const schedule =
        typeof requestAnimationFrame === "function"
          ? requestAnimationFrame
          : (callback: () => void) => setTimeout(callback, 0) as unknown as number;
      const cancelSchedule =
        typeof cancelAnimationFrame === "function"
          ? cancelAnimationFrame
          : (handle: number) => clearTimeout(handle);

      const finish = () => {
        cancelled = true;
        if (frame !== null) cancelSchedule(frame);
        frame = null;
        if (pendingRef.current[group] === cancel) delete pendingRef.current[group];
      };

      const run = () => {
        frame = null;
        // 版本/取消检查放在每个（嵌套）RAF 里：Maximize 之后旧回调必须
        // 彻底失效，而不是"再写一次旧布局"。
        if (cancelled || version !== versionRef.current) return;
        const handle = groupRefs[group]?.current;
        const current = handle?.getLayout();
        if (!handle || !current || Object.keys(current).length === 0) {
          // defaultLayoutDeferred 阶段 getLayout 是空对象，等到库完成
          // 第一次测量再写布局。
          if (attempts++ < 120) frame = schedule(run);
          else finish();
          return;
        }
        const desired = computeDesiredLayout(group);
        if (!desired) {
          finish();
          return;
        }
        if (!samePanelSet(current, desired)) {
          // 新 Panel（Play 的 game）还没被库登记进 Group；等下一帧再写，
          // 否则 setLayout 会因为 Panel 数量不一致抛异常。
          if (attempts++ < 180) frame = schedule(run);
          else finish();
          return;
        }
        if (!layoutsMatch(current, desired)) {
          handle.setLayout(desired);
          applied = true;
          stableChecks = 0;
        } else if (applied) {
          stableChecks += 1;
        } else {
          // 测量的默认布局恰好等于目标时也至少要显式写一次：库在第一次
          // resize observer 回调里可能用 defaultSize 覆盖 defaultLayout。
          handle.setLayout(desired);
          applied = true;
        }
        if (stableChecks >= 2) {
          finish();
          return;
        }
        if (attempts++ < 180) frame = schedule(run);
        else finish();
      };

      const cancel = () => {
        cancelled = true;
        if (frame !== null) cancelSchedule(frame);
        frame = null;
      };
      pendingRef.current[group] = cancel;
      run();
    },
    [computeDesiredLayout, groupRefs],
  );

  const requestApplyAll = useCallback(() => {
    versionRef.current += 1;
    const version = versionRef.current;
    for (const group of GROUPS) {
      if (!groupRefs[group]) continue;
      scheduleApply(group, version);
    }
  }, [groupRefs, scheduleApply]);

  // 所有影响布局意图的状态变化都在这里汇合：挂载、Panel 集合变化
  // （Play）、最小化集合、最大化目标。
  useEffect(() => {
    requestApplyAll();
  }, [availableKey, minimizedKey, maximized, requestApplyAll]);

  // 最大化目标被卸载（停止 Play）时必须恢复其他 Panel，否则工作区全是 0。
  useEffect(() => {
    const target = maximizedRef.current;
    if (!target || availableRef.current.includes(target)) return;
    const snapshot = snapshotRef.current;
    snapshotRef.current = null;
    if (snapshot) {
      for (const group of GROUPS) {
        if (!snapshot[group]) continue;
        const merged = buildStoredLayout(group, snapshot[group] as Layout);
        if (merged) {
          layoutsRef.current = { ...layoutsRef.current, [group]: merged };
        }
      }
    }
    setMaximizedState(null);
  }, [availableKey, buildStoredLayout, setMaximizedState]);

  useEffect(
    () => () => {
      for (const cancel of Object.values(pendingRef.current)) cancel?.();
      pendingRef.current = {};
      for (const cancel of Object.values(spanFrameCancelRef.current)) cancel?.();
      spanFrameCancelRef.current = {};
    },
    [],
  );

  const isMinimized = useCallback(
    (id: StudioPanelId) => minimized.includes(id),
    [minimized],
  );

  const isHidden = useCallback(
    (id: StudioPanelId) => isPanelHidden(id, minimized, maximized),
    [minimized, maximized],
  );

  const defaultLayout = useCallback(
    (
      group: PanelGroupId,
      panelIds: readonly StudioPanelId[],
      orientation: "horizontal" | "vertical" = "horizontal",
      referenceSpan?: number,
      spacerId?: string,
    ) => {
      const stored = layoutForPanels(layoutsRef.current[group], panelIds);
      const base = stored
        ? enforceMinimumPercentages(stored, panelIds, orientation, referenceSpan)
        : preferredPanelLayout(panelIds, orientation, referenceSpan);
      if (!base) return undefined;
      return withSpacerLayout(base, spacerId ?? "__spacer", minimizedRef.current);
    },
    [],
  );

  /**
   * 最小化不会写布局，所以首次最小化前要先把"当前实际尺寸"落成标称布局；
   * 否则该 Panel 在 localStorage 里没有历史尺寸，恢复时只能退回最小宽度。
   */
  const seedLayoutsFromLive = useCallback(() => {
    let changed = false;
    for (const group of GROUPS) {
      const live = groupRefs[group]?.current?.getLayout();
      if (!live || Object.keys(live).length === 0) continue;
      const merged = buildStoredLayout(group, live);
      if (!merged) continue;
      layoutsRef.current = { ...layoutsRef.current, [group]: merged };
      changed = true;
    }
    if (changed) commit({ ...stateRef.current, layouts: layoutsRef.current });
  }, [buildStoredLayout, commit, groupRefs]);

  const minimize = useCallback(
    (id: StudioPanelId) => {
      if (!STUDIO_PANEL_SPECS[id].dockable) return;
      if (!maximizedRef.current) seedLayoutsFromLive();
      if (maximizedRef.current) {
        // 先退出最大化（快照合并进 layoutsRef），再把目标放进 Dock；
        // 两步在同一次 render 里完成，结果就是"其余 Panel 恢复，目标归零"。
        restoreSnapshotIntoLayouts();
        setMaximizedState(null);
      }
      setMinimizedState(addMinimized(stateRef.current, id).minimized);
    },
    [restoreSnapshotIntoLayouts, seedLayoutsFromLive, setMaximizedState, setMinimizedState],
  );

  const restore = useCallback(
    (id: StudioPanelId) => {
      if (maximizedRef.current) {
        restoreSnapshotIntoLayouts();
        setMaximizedState(null);
      }
      setMinimizedState(removeMinimized(stateRef.current, id).minimized);
    },
    [restoreSnapshotIntoLayouts, setMaximizedState, setMinimizedState],
  );

  const toggleMaximize = useCallback(
    (id: StudioPanelId) => {
      if (maximizedRef.current === id) {
        restoreSnapshotIntoLayouts();
        setMaximizedState(null);
        return;
      }
      if (!maximizedRef.current) {
        // 只在进入最大化时取快照；切换目标（A → B）继续用同一份快照，
        // 否则会把已最大化的 100/0 布局当成"原始尺寸"存下来。
        const snapshot: Partial<Record<PanelGroupId, Layout>> = {};
        for (const group of GROUPS) {
          const layout = groupRefs[group]?.current?.getLayout();
          if (layout && Object.keys(layout).length > 0) {
            snapshot[group] = { ...layout };
          }
        }
        snapshotRef.current = snapshot;
      }
      if (minimizedRef.current.includes(id)) {
        setMinimizedState(removeMinimized(stateRef.current, id).minimized);
      }
      setMaximizedState(id);
    },
    [groupRefs, restoreSnapshotIntoLayouts, setMaximizedState, setMinimizedState],
  );

  const exitMaximize = useCallback(() => {
    if (!maximizedRef.current) return;
    restoreSnapshotIntoLayouts();
    setMaximizedState(null);
  }, [restoreSnapshotIntoLayouts, setMaximizedState]);

  const groupMinSpan = useCallback(
    (
      group: PanelGroupId,
      panelIds: readonly StudioPanelId[],
      orientation: "horizontal" | "vertical" = "horizontal",
    ) => {
      const base = panelMinSpan(panelIds, orientation);
      if (orientation === "vertical") return base;
      return Math.max(base, spans[group] ?? 0);
    },
    [spans],
  );

  const minimizedPanels = useMemo(
    () =>
      minimized.filter(
        (id) => STUDIO_PANEL_SPECS[id].dockable && available.includes(id),
      ),
    [available, minimized],
  );

  return {
    minimized: minimizedPanels,
    maximized,
    isMinimized,
    isHidden,
    defaultLayout,
    groupMinSpan,
    onLayoutChange,
    onLayoutChanged,
    minimize,
    restore,
    toggleMaximize,
    exitMaximize,
  };
}
