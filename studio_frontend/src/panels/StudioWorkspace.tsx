// studio_frontend/src/panels/StudioWorkspace.tsx
//
// 项目工作区的 Panel 布局。App 只负责项目生命周期（列表/打开/返回），
// 这里的 Group 结构、共享控制器、Dock 都集中在 Panel 系统里。
import { Fragment, useEffect, useMemo, type ReactNode, type RefObject } from "react";
import {
  Group,
  Panel,
  useGroupRef,
  usePanelRef,
  type PanelImperativeHandle,
} from "react-resizable-panels";
import { useStudioStore } from "../store";
import ChatPanel from "../components/ChatPanel";
import Canvas from "../components/Canvas";
import ControlBar from "../components/ControlBar";
import GameView from "../components/GameView";
import Inspector from "../components/Inspector";
import BottomPanel from "../components/BottomPanel";
import StatusBar from "../components/StatusBar";
import PanelBridgeSeparator from "./PanelBridgeSeparator";
import PanelDock from "./PanelDock";
import PanelFrame from "./PanelFrame";
import PanelSeparator from "./PanelSeparator";
import {
  PANEL_VERTICAL_SEPARATOR_SIZE,
  STUDIO_PANEL_SPECS,
  groupPanelIds,
  panelMinSpan,
  panelResizeBehavior,
  type StudioPanelId,
} from "./panelLayout";
import { useStudioPanelLayout } from "./useStudioPanelLayout";

interface StudioWorkspaceProps {
  projectId: string;
  playing: boolean;
  onBack: () => void;
}

export default function StudioWorkspace({
  projectId,
  playing,
  onBack,
}: StudioWorkspaceProps) {
  const project = useStudioStore((s) => s.project);

  const mainGroupRef = useGroupRef();
  const workspaceGroupRef = useGroupRef();

  const workspaceMainRef = usePanelRef();
  const chatRef = usePanelRef();
  const gameRef = usePanelRef();
  const canvasRef = usePanelRef();
  const inspectorRef = usePanelRef();
  const logsRef = usePanelRef();

  const panelRefs = useMemo<
    Partial<Record<StudioPanelId, RefObject<PanelImperativeHandle | null>>>
  >(
    () => ({
      "workspace-main": workspaceMainRef,
      chat: chatRef,
      game: gameRef,
      canvas: canvasRef,
      inspector: inspectorRef,
      logs: logsRef,
    }),
    [workspaceMainRef, chatRef, gameRef, canvasRef, inspectorRef, logsRef],
  );
  const groupRefs = useMemo(
    () => ({ main: mainGroupRef, workspace: workspaceGroupRef }),
    [mainGroupRef, workspaceGroupRef],
  );

  const mainIds: StudioPanelId[] = playing
    ? ["chat", "game", "canvas", "inspector"]
    : ["chat", "canvas", "inspector"];
  const available: StudioPanelId[] = ["workspace-main", ...mainIds, "logs"];
  const workspaceIds = groupPanelIds("workspace", available);

  const layout = useStudioPanelLayout({
    scope: "project",
    groupRefs,
    panelRefs,
    available,
  });

  // 保留 GameView 原来的 Esc 退出全屏行为；现在全屏 = 该 Panel 最大化，
  // 对所有 Panel 生效，而不是回 GameView 自己再维护一套 overlay。
  const maximized = layout.maximized;
  const exitMaximize = layout.exitMaximize;
  useEffect(() => {
    if (!maximized) return;
    if (typeof window.addEventListener !== "function") return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") exitMaximize();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [maximized, exitMaximize]);

  const isHidden = layout.isHidden;
  const focusFallbackFor = (id: StudioPanelId) => {
    if (layout.isMinimized(id)) return `dock-restore-${id}`;
    if (maximized && maximized !== id) return `panel-maximize-${maximized}`;
    return undefined;
  };

  // 库的折叠能力始终保留（程序化最小化/最大化要写 0），但可见 Panel
  // 被用户拖/键到阈值以下时，onLayoutChange 会立刻按 minSize 夹回来。
  // 不可见的 Panel 同时禁用：它在 DOM 里仍占着相邻位置，库的面板边缘
  // 命中区会把这些隐藏 Panel 当作 Resize 目标；禁用后这些命中区变成
  // no-op，bridge 才能独占两个可见 Panel 之间的拖拽。
  const renderPanel = (id: StudioPanelId, content: ReactNode) => {
    const spec = STUDIO_PANEL_SPECS[id];
    const hidden = isHidden(id);
    return (
      <Panel
        id={id}
        panelRef={panelRefs[id]}
        groupResizeBehavior={panelResizeBehavior(
          id === "canvas" ? "preserve-relative-size" : "preserve-pixel-size",
          { hidden, maximized: maximized === id },
        )}
        defaultSize={spec.minWidth}
        minSize={spec.minWidth}
        collapsible
        collapsedSize={0}
        disabled={hidden}
      >
        <PanelFrame
          id={id}
          title={spec.title}
          minimized={layout.isMinimized(id)}
          hidden={hidden}
          maximized={maximized === id}
          contentMinWidth={spec.contentMinWidth}
          contentMinHeight={spec.contentMinHeight}
          scroll={id === "canvas" ? "hidden" : "auto"}
          focusFallbackId={focusFallbackFor(id)}
          onMinimize={() => layout.minimize(id)}
          onToggleMaximize={() => layout.toggleMaximize(id)}
        >
          {content}
        </PanelFrame>
      </Panel>
    );
  };

  const panelContent = (id: StudioPanelId): ReactNode => {
    switch (id) {
      case "chat":
        return <ChatPanel projectId={projectId} />;
      case "game":
        return (
          <GameView
            projectId={projectId}
            expanded={maximized === "game"}
            onToggleExpanded={() => layout.toggleMaximize("game")}
          />
        );
      case "canvas":
        return <Canvas projectId={projectId} />;
      case "inspector":
        return <Inspector projectId={projectId} />;
      default:
        return null;
    }
  };

  // 只看得见的 Panel 才需要最小宽度/高度。最小化或最大化时，被隐藏的
  // Panel 不能继续占据完整的 min span，否则短视口会溢出、窄屏会白白多出
  // 一条滚动距离。
  const visibleMainIds = mainIds.filter((id) => !isHidden(id));
  const visibleWorkspaceIds = workspaceIds.filter((id) => !isHidden(id));
  const mainIsMaximized =
    maximized !== null && STUDIO_PANEL_SPECS[maximized].group === "main";
  const mainMinWidth = mainIsMaximized
    ? 0
    : layout.groupMinSpan("main", visibleMainIds.length > 0 ? visibleMainIds : mainIds);
  const workspaceMinSpan = panelMinSpan(
    visibleWorkspaceIds.length > 0 ? visibleWorkspaceIds : workspaceIds,
    "vertical",
  );

  return (
    <div className="flex h-full w-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-gray-200 bg-white px-4 py-2">
        <button
          onClick={onBack}
          disabled={playing}
          title={playing ? "运行中无法切换项目" : "返回项目列表"}
          className="text-sm text-gray-600 hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-40"
        >
          ← 返回项目列表
        </button>
        {project && (
          <span className="text-sm font-medium text-gray-700">{project.name}</span>
        )}
      </div>
      <ControlBar projectId={projectId} />
      <PanelDock
        panels={layout.minimized.map((id) => STUDIO_PANEL_SPECS[id])}
        onRestore={layout.restore}
      />
      {/* 短视口：整个垂直工作区可以纵向滚动。Group 的高度由可见 Panel 的
          最小高度决定（grid 的 minmax 行），Dock 和状态栏始终留在视口内，
          Logs 标题栏与按钮滚动可达。 */}
      <div
        className="grid min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
        data-testid="workspace-vertical-scroll"
        style={{ gridTemplateRows: `minmax(${workspaceMinSpan}px, 1fr)` }}
      >
        <Group
          id="studio-workspace"
          groupRef={workspaceGroupRef}
          orientation="vertical"
          className="min-h-0"
          style={{ minHeight: workspaceMinSpan }}
          defaultLayout={layout.defaultLayout("workspace", workspaceIds, "vertical", undefined, "workspace-spacer")}
          onLayoutChange={(next) => layout.onLayoutChange("workspace", next)}
          onLayoutChanged={(next, meta) => layout.onLayoutChanged("workspace", next, meta)}
          resizeTargetMinimumSize={{ fine: 12, coarse: 24 }}
        >
          <Panel
            id="workspace-main"
            groupResizeBehavior={panelResizeBehavior("preserve-relative-size", {
              hidden: isHidden("workspace-main"),
              maximized: maximized === "workspace-main",
            })}
            defaultSize={STUDIO_PANEL_SPECS["workspace-main"].minHeight}
            minSize={STUDIO_PANEL_SPECS["workspace-main"].minHeight}
            collapsible
            collapsedSize={0}
            disabled={isHidden("workspace-main")}
            panelRef={panelRefs["workspace-main"]}
          >
            <div
              className="flex h-full min-h-0 min-w-0 w-full overflow-x-auto overflow-y-hidden"
              data-testid="workspace-horizontal-scroll"
            >
              <Group
                id="studio-main"
                groupRef={mainGroupRef}
                orientation="horizontal"
                className="h-full w-full shrink-0"
                style={{ minWidth: mainMinWidth }}
                defaultLayout={layout.defaultLayout("main", mainIds, "horizontal", undefined, "main-spacer")}
                onLayoutChange={(next) => layout.onLayoutChange("main", next)}
                onLayoutChanged={(next, meta) => layout.onLayoutChanged("main", next, meta)}
                resizeTargetMinimumSize={{ fine: 12, coarse: 24 }}
              >
                {/* 可见邻接关系：中间 Panel 被最小化后，左右两个可见 Panel
                    之间没有库注册的 Separator（它们各自挨着一个隐藏 Panel）。
                    这时插入一条自己处理拖拽/键盘的 bridge，保证剩余可见
                    Panel 仍然可 Resize。 */}
                {mainIds.map((id) => {
                  const index = visibleMainIds.indexOf(id);
                  const previous = index > 0 ? visibleMainIds[index - 1] : null;
                  let separator: ReactNode = null;
                  if (previous) {
                    const adjacent = mainIds.indexOf(previous) === mainIds.indexOf(id) - 1;
                    separator = adjacent ? (
                      <PanelSeparator
                        key={`separator-${previous}-${id}`}
                        orientation="horizontal"
                        label={`调整 ${STUDIO_PANEL_SPECS[previous].title} 与 ${STUDIO_PANEL_SPECS[id].title} 宽度`}
                      />
                    ) : (
                      <PanelBridgeSeparator
                        key={`bridge-${previous}-${id}`}
                        orientation="horizontal"
                        label={`调整 ${STUDIO_PANEL_SPECS[previous].title} 与 ${STUDIO_PANEL_SPECS[id].title} 宽度`}
                        groupRef={mainGroupRef}
                        panelRefs={panelRefs}
                        leftId={previous}
                        rightId={id}
                        minLeft={STUDIO_PANEL_SPECS[previous].minWidth}
                        minRight={STUDIO_PANEL_SPECS[id].minWidth}
                        onCommit={(next) =>
                          layout.onLayoutChanged("main", next, { isUserInteraction: true })
                        }
                      />
                    );
                  }
                  return (
                    <Fragment key={id}>
                      {separator}
                      {renderPanel(id, panelContent(id))}
                    </Fragment>
                  );
                })}
                <Panel
                  id="main-spacer"
                  groupResizeBehavior="preserve-pixel-size"
                  defaultSize={0}
                  minSize={0}
                  collapsible
                  collapsedSize={0}
                  disabled
                  aria-hidden="true"
                  data-testid="panel-spacer-main"
                  className="pointer-events-none"
                >
                  <div className="pointer-events-none h-full w-full" />
                </Panel>
              </Group>
            </div>
          </Panel>
          <PanelSeparator
            orientation="vertical"
            label="调整 Execution Logs 高度"
            hidden={isHidden("workspace-main") || isHidden("logs")}
            thickness={PANEL_VERTICAL_SEPARATOR_SIZE}
            // 命中区向下盖住标题栏 22px；右侧 80px 留给最小化/最大化按钮，
            // 避免拖拽手柄抢占按钮点击。
            overlay={{ height: 32, rightInset: 80 }}
            handleId="separator-logs"
          />
          <Panel
            id="logs"
            groupResizeBehavior={panelResizeBehavior("preserve-pixel-size", {
              hidden: isHidden("logs"),
              maximized: maximized === "logs",
            })}
            defaultSize={STUDIO_PANEL_SPECS.logs.minHeight}
            minSize={STUDIO_PANEL_SPECS.logs.minHeight}
            collapsible
            collapsedSize={0}
            disabled={isHidden("logs")}
            panelRef={panelRefs.logs}
          >
            <PanelFrame
              id="logs"
              title={STUDIO_PANEL_SPECS.logs.title}
              minimized={layout.isMinimized("logs")}
              hidden={isHidden("logs")}
              maximized={maximized === "logs"}
              contentMinWidth={STUDIO_PANEL_SPECS.logs.contentMinWidth}
              contentMinHeight={STUDIO_PANEL_SPECS.logs.contentMinHeight}
              focusFallbackId={focusFallbackFor("logs")}
              onMinimize={() => layout.minimize("logs")}
              onToggleMaximize={() => layout.toggleMaximize("logs")}
            >
              <BottomPanel />
            </PanelFrame>
          </Panel>
          <Panel
            id="workspace-spacer"
            groupResizeBehavior="preserve-pixel-size"
            defaultSize={0}
            minSize={0}
            collapsible
            collapsedSize={0}
            disabled
            aria-hidden="true"
            data-testid="panel-spacer-workspace"
            className="pointer-events-none"
          >
            <div className="pointer-events-none h-full w-full" />
          </Panel>
        </Group>
      </div>
      <StatusBar />
    </div>
  );
}
