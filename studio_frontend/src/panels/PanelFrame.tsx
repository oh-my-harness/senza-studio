// studio_frontend/src/panels/PanelFrame.tsx
//
// 所有工作区 Panel 共用的外壳：标题栏 + 最小化/最大化按钮 + 内容滚动区。
//
// 内容区刻意分两层：
//   overflow:auto 的外层  ← 面板被拖窄/拖矮时出现滚动条
//   min-width/min-height 的内层 ← 内部控件按"正常排列所需尺寸"布局
// 这样 Inspector 缩到 260px 时表单仍是 460px 宽（横向滚动查看），而不是
// 把输入框/按钮挤成一团。Canvas 之类自己有 pan/zoom 的 Panel 通过
// contentMin* = 0 + scroll="hidden" 关闭外层滚动，避免嵌套滚动冲突。
//
// 不可见的 Panel 只隐藏、不卸载：`inert` 让内部输入框/按钮从 Tab 顺序和
// 命中测试里彻底消失（aria-hidden 单独用挡不住 focus()），隐藏瞬间如果
// 焦点还在里面，则转移到 Dock / 最大化按钮这类可见入口。
import { useEffect, useRef, type ReactNode } from "react";
import { focusFallbackTarget } from "./focusFallback";
import type { StudioPanelId } from "./panelLayout";

interface PanelFrameProps {
  id: StudioPanelId;
  title: string;
  minimized: boolean;
  /** 实际不可见：被最小化，或被另一个 Panel 的最大化挤走。 */
  hidden?: boolean;
  maximized: boolean;
  contentMinWidth: number;
  contentMinHeight: number;
  scroll?: "auto" | "hidden";
  /** 隐藏时若焦点在 Panel 内，转移到这个 DOM id（Dock 按钮 / 最大化按钮）。 */
  focusFallbackId?: string;
  onMinimize: () => void;
  onToggleMaximize: () => void;
  children: ReactNode;
}

function MinimizeIcon() {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" aria-hidden="true">
      <path d="M3 8h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

function MaximizeIcon({ maximized }: { maximized: boolean }) {
  return (
    <svg viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" aria-hidden="true">
      {maximized ? (
        <>
          <rect x="3" y="5" width="8" height="8" rx="1" stroke="currentColor" strokeWidth="1.4" />
          <path d="M5 5V3h8v8h-2" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
        </>
      ) : (
        <rect x="3" y="3" width="10" height="10" rx="1" stroke="currentColor" strokeWidth="1.4" />
      )}
    </svg>
  );
}

export default function PanelFrame({
  id,
  title,
  minimized,
  hidden = minimized,
  maximized,
  contentMinWidth,
  contentMinHeight,
  scroll = "auto",
  focusFallbackId,
  onMinimize,
  onToggleMaximize,
  children,
}: PanelFrameProps) {
  const sectionRef = useRef<HTMLElement | null>(null);
  const cancelFocusRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    const element = sectionRef.current;
    if (!element) return;
    if (hidden) {
      const active = element.ownerDocument.activeElement;
      const ownsFocus = !!active && (active === element || element.contains(active));
      if (ownsFocus) {
        const blurActive = () => {
          const blur = (active as HTMLElement | null)?.blur;
          if (typeof blur === "function") blur.call(active);
        };
        if (focusFallbackId) {
          // 最大化目标可能与本 Panel 在同一次 commit 里解除 inert；
          // 立即失败时先 blur，helper 会在 effect 批次结束后重试。
          cancelFocusRef.current = focusFallbackTarget(
            element.ownerDocument,
            focusFallbackId,
            blurActive,
          );
        } else {
          blurActive();
        }
      }
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
    } else {
      element.removeAttribute("inert");
      element.removeAttribute("aria-hidden");
    }
    return () => {
      cancelFocusRef.current?.();
      cancelFocusRef.current = null;
    };
  }, [hidden, focusFallbackId]);

  return (
    <section
      ref={sectionRef}
      className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-white"
      data-panel-id={id}
      data-testid={`panel-${id}`}
      data-panel-minimized={minimized ? "true" : "false"}
      data-panel-hidden={hidden ? "true" : "false"}
      data-panel-maximized={maximized ? "true" : "false"}
    >
      <header className="flex h-8 shrink-0 items-center gap-1 overflow-hidden border-b border-gray-200 bg-gray-50 px-2">
        <span
          className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-wide text-gray-500"
          title={title}
          data-testid={`panel-title-${id}`}
        >
          {title}
        </span>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <button
            id={`panel-minimize-${id}`}
            type="button"
            onClick={onMinimize}
            title={`最小化 ${title}`}
            aria-label={`最小化 ${title}`}
            data-testid={`panel-minimize-${id}`}
            className="flex h-7 w-7 items-center justify-center rounded text-gray-500 hover:bg-gray-200 hover:text-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <MinimizeIcon />
          </button>
          <button
            id={`panel-maximize-${id}`}
            type="button"
            onClick={onToggleMaximize}
            title={maximized ? `恢复 ${title}` : `最大化 ${title}`}
            aria-label={maximized ? `恢复 ${title}` : `最大化 ${title}`}
            aria-pressed={maximized}
            data-testid={`panel-maximize-${id}`}
            className="flex h-7 w-7 items-center justify-center rounded text-gray-500 hover:bg-gray-200 hover:text-gray-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
          >
            <MaximizeIcon maximized={maximized} />
          </button>
        </div>
      </header>
      <div
        className={`relative min-h-0 min-w-0 flex-1 ${
          scroll === "auto" ? "overflow-auto" : "overflow-hidden"
        }`}
        data-panel-scroll={scroll}
      >
        <div
          className="flex h-full min-h-full w-full min-w-full flex-col"
          style={{
            minWidth: contentMinWidth > 0 ? contentMinWidth : undefined,
            minHeight: contentMinHeight > 0 ? contentMinHeight : undefined,
          }}
        >
          {children}
        </div>
      </div>
    </section>
  );
}
