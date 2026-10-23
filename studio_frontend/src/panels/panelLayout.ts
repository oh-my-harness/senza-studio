// studio_frontend/src/panels/panelLayout.ts
//
// Panel 契约 + 布局持久化的纯函数部分。
//
// 所有工作区 Panel 共用同一份描述：最小外壳尺寸、内容最小布局尺寸、
// 是否可停靠。控制器只消费这份表，不再让每个 Panel 各写一套 resize /
// minimize 逻辑。
//
// 持久化只落 localStorage（带版本号的 key），不进 pipeline.yaml、也不进
// 故事存档——布局是浏览器的偏好，不是项目内容。
import type { Layout } from "react-resizable-panels";

export const PANEL_LAYOUT_VERSION = 1;

/** 水平分隔线占用的像素。与 PanelSeparator 的宽度保持一致。 */
export const PANEL_SEPARATOR_SIZE = 6;

/**
 * 纵向分隔线占用的像素。底部 Panel 的分隔线是 overlay 手柄：元素更高
 * （覆盖标题栏命中区），但实际占位只有 10px，Group 的最小高度必须按
 * 这个实际占位计算，否则短视口会把 Panel 压到 minHeight 以下。
 */
export const PANEL_VERTICAL_SEPARATOR_SIZE = 10;

function separatorSize(orientation: "horizontal" | "vertical"): number {
  return orientation === "horizontal"
    ? PANEL_SEPARATOR_SIZE
    : PANEL_VERTICAL_SEPARATOR_SIZE;
}

export type StudioPanelId =
  | "workspace-main"
  | "chat"
  | "game"
  | "canvas"
  | "inspector"
  | "logs"
  | "agent-sidebar"
  | "agent-chat";

export type PanelGroupId = "main" | "workspace" | "agent";

export type PanelScope = "project" | "agent-team";

export interface PanelSpec {
  id: StudioPanelId;
  title: string;
  group: PanelGroupId;
  /** 外壳最小宽度。缩到这个值以下标题/按钮/分隔线就无法操作。 */
  minWidth: number;
  /** 外壳最小高度。 */
  minHeight: number;
  /**
   * 内容维持正常排列所需的最小宽度。Panel 比它窄时**不压缩内容**，
   * 由 PanelFrame 提供横向滚动。
   */
  contentMinWidth: number;
  /** 内容维持正常排列所需的最小高度（超出时纵向滚动）。 */
  contentMinHeight: number;
  /** 出现在 Named Dock 里的 Panel 名称；结构容器不显示。 */
  dockable: boolean;
}

export const STUDIO_PANEL_SPECS: Record<StudioPanelId, PanelSpec> = {
  // 结构容器：承载横向工作区（不是用户可见 Panel，不参与 Dock）。
  "workspace-main": {
    id: "workspace-main",
    title: "Workspace",
    group: "workspace",
    minWidth: 0,
    minHeight: 240,
    contentMinWidth: 0,
    contentMinHeight: 0,
    dockable: false,
  },
  chat: {
    id: "chat",
    title: "Agent Chat",
    group: "main",
    minWidth: 260,
    minHeight: 200,
    contentMinWidth: 340,
    contentMinHeight: 260,
    dockable: true,
  },
  game: {
    id: "game",
    title: "Play",
    group: "main",
    minWidth: 300,
    minHeight: 280,
    contentMinWidth: 320,
    contentMinHeight: 360,
    dockable: true,
  },
  canvas: {
    id: "canvas",
    title: "Workflow Canvas",
    group: "main",
    minWidth: 360,
    minHeight: 200,
    // Canvas 自己管 pan/zoom，不能再套一层内容滚动。
    contentMinWidth: 0,
    contentMinHeight: 0,
    dockable: true,
  },
  inspector: {
    id: "inspector",
    title: "Inspector",
    group: "main",
    minWidth: 260,
    minHeight: 200,
    // 表单字段正常排列需要 ~460px；缩窄时横向滚动而不是挤压控件。
    contentMinWidth: 460,
    contentMinHeight: 260,
    dockable: true,
  },
  logs: {
    id: "logs",
    title: "Execution Logs",
    group: "workspace",
    minWidth: 0,
    minHeight: 140,
    // 日志行由 BottomPanel 自己的 overflow-x-auto 处理；外层不再套一层
    // 横向滚动，避免双重滚动条。
    contentMinWidth: 0,
    contentMinHeight: 96,
    dockable: true,
  },
  "agent-sidebar": {
    id: "agent-sidebar",
    title: "Agent Team Sidebar",
    group: "agent",
    minWidth: 240,
    minHeight: 220,
    contentMinWidth: 288,
    contentMinHeight: 260,
    dockable: true,
  },
  "agent-chat": {
    id: "agent-chat",
    title: "Agent Team Chat",
    group: "agent",
    minWidth: 360,
    minHeight: 220,
    contentMinWidth: 420,
    contentMinHeight: 320,
    dockable: true,
  },
};

export type PanelResizeBehavior = "preserve-relative-size" | "preserve-pixel-size";

/**
 * 窗口 Resize 时 Panel 的尺寸策略必须守住两条不变量：
 *
 * 1. 隐藏（最小化 / 被最大化挤走）的 Panel 永远是 0。库的 Group resize
 *    算法会先给 preserve-pixel-size 的 Panel 保留像素，再把剩余百分比分给
 *    preserve-relative-size 的 Panel；如果所有 relative Panel 都是 0，它会
 *    把剩余空间**均分**给这些 0 尺寸 Panel（`Ut` 的 `l / r.length`）。
 *    最小化 Panel 因此可能重新长出 22.5% 宽，虽然它仍是 inert。
 * 2. 最大化的 Panel 永远占 100%。如果它保留原面板的 preserve-pixel-size，
 *    窗口放大时它只保留旧像素宽度，百分比被分给其他 0 尺寸 relative Panel。
 *
 * 所以这两个状态下不能沿用普通布局的像素/比例偏好，必须切到对应策略。
 * 普通可见 Panel 仍按原策略（Canvas 吸收宽度、Chat/Inspector 保持像素）。
 * 末尾占位 Panel 也固定为 pixel：当所有真实 Panel 都是 pixel 时，Group 里
 * 没有 relative Panel 可吸收窗口新增空间，库会保留原百分比、让可见 Panel
 * 按比例铺满；如果占位保持 relative，新增空间会全部落在不可见的占位上，
 * 视觉上就是一条空白。
 */
export function panelResizeBehavior(
  base: PanelResizeBehavior,
  state: { hidden: boolean; maximized: boolean },
): PanelResizeBehavior {
  if (state.hidden) return "preserve-pixel-size";
  if (state.maximized) return "preserve-relative-size";
  return base;
}

export interface PersistedPanelState {
  version: typeof PANEL_LAYOUT_VERSION;
  layouts: Partial<Record<PanelGroupId, Layout>>;
  /** 保存布局时的 Group 像素尺寸。用于在窄屏上保持面板的像素宽度
   * （工作区横向滚动），而不是把所有面板等比压到最小尺寸以下。 */
  spans: Partial<Record<PanelGroupId, number>>;
  minimized: StudioPanelId[];
}

export function emptyPanelState(): PersistedPanelState {
  return {
    version: PANEL_LAYOUT_VERSION,
    layouts: {},
    spans: {},
    minimized: [],
  };
}

export function panelStorageKey(scope: PanelScope): string {
  return `senza:studio:panel-layout:v${PANEL_LAYOUT_VERSION}:${scope}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isLayout(value: unknown): value is Layout {
  if (!isRecord(value)) return false;
  const entries = Object.entries(value);
  if (entries.length === 0) return false;
  let positive = 0;
  for (const [id, size] of entries) {
    if (!id || typeof size !== "number" || !Number.isFinite(size)) return false;
    if (size < 0 || size > 100) return false;
    if (size > 0) positive += 1;
  }
  return positive > 0;
}

function isPanelId(value: unknown): value is StudioPanelId {
  return typeof value === "string" && value in STUDIO_PANEL_SPECS;
}

/**
 * 把 localStorage 里的任意内容收敛成当前版本的可信状态。
 * 版本不符、字段缺失、尺寸越界一律丢弃——坏数据最多让布局回到默认，
 * 不能把界面锁死。
 */
export function normalizePanelState(raw: unknown): PersistedPanelState {
  if (!isRecord(raw) || raw.version !== PANEL_LAYOUT_VERSION) {
    return emptyPanelState();
  }
  const layouts: Partial<Record<PanelGroupId, Layout>> = {};
  if (isRecord(raw.layouts)) {
    for (const group of ["main", "workspace", "agent"] as PanelGroupId[]) {
      const value = raw.layouts[group];
      if (isLayout(value)) layouts[group] = { ...value };
    }
  }
  const spans: Partial<Record<PanelGroupId, number>> = {};
  if (isRecord(raw.spans)) {
    for (const group of ["main", "workspace", "agent"] as PanelGroupId[]) {
      const value = raw.spans[group];
      if (typeof value === "number" && Number.isFinite(value) && value > 0 && value <= 10000) {
        spans[group] = value;
      }
    }
  }
  const minimized: StudioPanelId[] = [];
  if (Array.isArray(raw.minimized)) {
    for (const value of raw.minimized) {
      if (isPanelId(value) && !minimized.includes(value) && STUDIO_PANEL_SPECS[value].dockable) {
        minimized.push(value);
      }
    }
  }
  return { version: PANEL_LAYOUT_VERSION, layouts, spans, minimized };
}

function resolveStorage(storage?: Storage | null): Storage | null {
  if (storage) return storage;
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function loadPanelState(
  scope: PanelScope,
  storage?: Storage | null,
): PersistedPanelState {
  const target = resolveStorage(storage);
  if (!target) return emptyPanelState();
  try {
    const raw = target.getItem(panelStorageKey(scope));
    if (!raw) return emptyPanelState();
    return normalizePanelState(JSON.parse(raw));
  } catch {
    return emptyPanelState();
  }
}

export function savePanelState(
  scope: PanelScope,
  state: PersistedPanelState,
  storage?: Storage | null,
): void {
  const target = resolveStorage(storage);
  if (!target) return;
  try {
    target.setItem(panelStorageKey(scope), JSON.stringify(state));
  } catch {
    // 存储不可用/配额满：布局只在本次会话生效，不能让 UI 报错。
  }
}

export function addMinimized(
  state: PersistedPanelState,
  id: StudioPanelId,
): PersistedPanelState {
  if (state.minimized.includes(id)) return state;
  return { ...state, minimized: [...state.minimized, id] };
}

export function removeMinimized(
  state: PersistedPanelState,
  id: StudioPanelId,
): PersistedPanelState {
  if (!state.minimized.includes(id)) return state;
  return { ...state, minimized: state.minimized.filter((value) => value !== id) };
}

/**
 * 只保留当前可见 Panel 的布局，并重新归一化到 100%。
 * Panel 集合变化（进入/结束 Play 时的 game Panel）时，旧布局里多出来或
 * 缺失的 id 不能直接喂给 Group——缺 id 会让库把尺寸算错。
 */
export function layoutForPanels(
  layout: Layout | undefined,
  panelIds: readonly StudioPanelId[],
): Layout | undefined {
  if (!layout) return undefined;
  const total = panelIds.reduce((sum, id) => sum + (layout[id] ?? 0), 0);
  if (total <= 0) return undefined;
  if (panelIds.some((id) => typeof layout[id] !== "number" || layout[id] < 0)) return undefined;
  const next: Layout = {};
  panelIds.forEach((id) => {
    next[id] = ((layout[id] ?? 0) / total) * 100;
  });
  return next;
}

/** Group 的最小总尺寸：所有外壳最小宽/高 + 分隔线。 */
export function panelMinSpan(
  panelIds: readonly StudioPanelId[],
  orientation: "horizontal" | "vertical" = "horizontal",
): number {
  if (panelIds.length === 0) return 0;
  return (
    panelIds.reduce(
      (sum, id) =>
        sum +
        (orientation === "horizontal"
          ? STUDIO_PANEL_SPECS[id].minWidth
          : STUDIO_PANEL_SPECS[id].minHeight),
      0,
    ) +
    separatorSize(orientation) * (panelIds.length - 1)
  );
}

/**
 * 把保存的百分比布局抬到"每个 Panel 至少占自己的最小尺寸"。
 *
 * referenceSpan 优先用保存布局时的真实 Group 尺寸（外层滚动容器会保证
 * Group 不小于该宽度），没有保存值时退回 panelMinSpan。没有这一步，
 * 1280px 下保存的 24% 到 390px 的 892px Group 上只剩 214px，低于最小
 * 宽度——库会把它折叠，用户一缩小窗口 Panel 就"凭空消失"。
 */
export function enforceMinimumPercentages(
  layout: Layout | undefined,
  panelIds: readonly StudioPanelId[],
  orientation: "horizontal" | "vertical" = "horizontal",
  referenceSpan?: number,
): Layout | undefined {
  if (!layout || panelIds.length === 0) return undefined;
  const span = Math.max(referenceSpan ?? 0, panelMinSpan(panelIds, orientation));
  if (span <= 0) return undefined;
  const floors = panelIds.map((id) => {
    const size =
      orientation === "horizontal"
        ? STUDIO_PANEL_SPECS[id].minWidth
        : STUDIO_PANEL_SPECS[id].minHeight;
    return (size / span) * 100;
  });
  const values = panelIds.map((id, index) => Math.max(layout[id] ?? 0, floors[index]));
  const total = values.reduce((sum, value) => sum + value, 0);
  if (total <= 0) return undefined;
  if (total > 100) {
    const excess = total - 100;
    const reducible = values.map((value, index) => value - floors[index]);
    const reducibleTotal = reducible.reduce((sum, value) => sum + value, 0);
    if (reducibleTotal > 0) {
      values.forEach((value, index) => {
        values[index] = value - excess * (reducible[index] / reducibleTotal);
      });
    }
  } else if (total < 100) {
    const extra = 100 - total;
    values.forEach((value, index) => {
      values[index] = value + extra * (value / total);
    });
  }
  return Object.fromEntries(panelIds.map((id, index) => [id, values[index]]));
}

export function groupPanelIds(
  group: PanelGroupId,
  available: readonly StudioPanelId[],
): StudioPanelId[] {
  return available.filter((id) => STUDIO_PANEL_SPECS[id].group === group);
}

/**
 * Panel 此刻是否真的不可见。
 *
 * 不能简单写成 `id !== maximized`：最大化嵌套在主工作区里的 Panel（Chat、
 * Canvas……）时，`workspace-main` 是仍然可见的结构容器，被收起的是
 * Execution Logs；反过来最大化 Logs 时整个横向工作区（包括 workspace-main
 * 和它内部的 Panel）都被收起。
 *
 * 这个判断同时驱动三件事：库的 collapsible（用户拖动绝不能折叠）、
 * PanelFrame 的 inert/aria-hidden，以及分隔线的显隐。
 */
export function isPanelHidden(
  id: StudioPanelId,
  minimized: readonly StudioPanelId[],
  maximized: StudioPanelId | null,
): boolean {
  if (minimized.includes(id)) return true;
  if (!maximized) return false;
  if (id === maximized) return false;
  const targetGroup = STUDIO_PANEL_SPECS[maximized].group;
  const group = STUDIO_PANEL_SPECS[id].group;
  if (group === targetGroup) return true;
  if (targetGroup === "main") {
    return group === "workspace" && id !== "workspace-main";
  }
  if (targetGroup === "workspace") {
    return group === "workspace" || group === "main";
  }
  return true;
}


/** 首次打开时的直觉比例（会被最小尺寸下限抬高）。 */
const PREFERRED_WEIGHTS: Partial<Record<StudioPanelId, number>> = {
  chat: 22,
  game: 22,
  canvas: 46,
  inspector: 22,
  "workspace-main": 74,
  logs: 26,
  "agent-sidebar": 24,
  "agent-chat": 76,
};

export function preferredPanelLayout(
  panelIds: readonly StudioPanelId[],
  orientation: "horizontal" | "vertical" = "horizontal",
  referenceSpan?: number,
): Layout | undefined {
  if (panelIds.length === 0) return undefined;
  const weights = panelIds.map((id) => PREFERRED_WEIGHTS[id] ?? 1);
  const total = weights.reduce((sum, value) => sum + value, 0);
  const layout: Layout = {};
  panelIds.forEach((id, index) => {
    layout[id] = (weights[index] / total) * 100;
  });
  return enforceMinimumPercentages(layout, panelIds, orientation, referenceSpan);
}

/**
 * Group 末尾的透明占位 Panel。
 *
 * react-resizable-panels 不允许"最后一个 Panel"收缩到 0（会用
 * 100 - 前面之和 把它撑满）。所有真实 Panel 都最小化时，这个占位
 * Panel 承担剩余空间，保证工作区真的空出来、Dock 里的每个 Panel
 * 都能独立恢复。
 */
export function withSpacer(layout: Layout | undefined, spacerId: string): Layout | undefined {
  return layout ? { ...layout, [spacerId]: 0 } : undefined;
}
