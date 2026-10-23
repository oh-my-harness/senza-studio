// studio_frontend/src/panels/PanelDock.tsx
//
// Named Dock：最小化后的 Panel 仍以可读名称停在这里。
// - 多个 Panel 可同时最小化；
// - 每个标签独立恢复；
// - 标签不缩成图标（shrink-0 + whitespace-nowrap），太多时横向滚动；
// - Dock 是工作区外的独立一行，不会被任何 Panel 遮挡。
import type { PanelSpec, StudioPanelId } from "./panelLayout";

interface PanelDockProps {
  panels: readonly PanelSpec[];
  onRestore: (id: StudioPanelId) => void;
}

export default function PanelDock({ panels, onRestore }: PanelDockProps) {
  if (panels.length === 0) return null;
  return (
    <div
      role="toolbar"
      aria-label="已最小化的面板"
      data-testid="panel-dock"
      className="flex shrink-0 items-center gap-2 border-b border-gray-200 bg-gray-50 px-2 py-1"
    >
      <span className="shrink-0 text-[10px] font-semibold uppercase tracking-wider text-gray-400">
        Minimized
      </span>
      <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
        {panels.map((panel) => (
          <button
            key={panel.id}
            id={`dock-restore-${panel.id}`}
            type="button"
            onClick={() => onRestore(panel.id)}
            title={`恢复 ${panel.title}`}
            data-testid={`dock-${panel.id}`}
            className="shrink-0 whitespace-nowrap rounded border border-gray-300 bg-white px-2 py-0.5 text-xs text-gray-700 hover:border-blue-400 hover:text-blue-700 focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500"
          >
            {panel.title}
          </button>
        ))}
      </div>
    </div>
  );
}
