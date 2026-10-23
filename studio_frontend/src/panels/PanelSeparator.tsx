// studio_frontend/src/panels/PanelSeparator.tsx
//
// 统一的可抓取分隔线：可见宽度 6px（不是 1px 发丝线），中间有一条
// 视觉把手；不可见时 display:none 并 disabled，避免留下一条能拖却拖不动
// 的缝（相邻 Panel 已最小化/被最大化挤走）。
//
// 底部 Panel 的纵向分隔线支持 overlay 模式：分隔线元素本身比实际占位
// 厚度高，多出来的部分用负 margin 盖在下一个 Panel 的标题栏上。这样
// "拖 Panel 顶部边界"包含用户真正会去抓的标题栏区域，而不只是分隔线
// 上方那条 6px 细线。右侧按钮区通过 rightInset 排除，避免抢占最小化/
// 最大化按钮的点击。
import { Separator } from "react-resizable-panels";

interface PanelSeparatorProps {
  orientation: "horizontal" | "vertical";
  label: string;
  hidden?: boolean;
  /** 实际占位厚度（px）。默认 6。 */
  thickness?: number;
  /**
   * 纵向分隔线额外向下覆盖的命中区（px）。元素总高度 = height，
   * 实际占位仍是 thickness，差额用负 margin 盖到下一个 Panel 顶部。
   * rightInset 是从右侧留出的按钮区宽度。
   */
  overlay?: { height: number; rightInset: number };
  /** 分隔线的 DOM id（同时作为 data-testid）。 */
  handleId?: string;
}

export default function PanelSeparator({
  orientation,
  label,
  hidden = false,
  thickness = 6,
  overlay,
  handleId,
}: PanelSeparatorProps) {
  const horizontal = orientation === "horizontal";

  if (!horizontal && overlay) {
    const { height, rightInset } = overlay;
    return (
      <Separator
        id={handleId}
        aria-label={label}
        disabled={hidden}
        className={
          hidden
            ? "hidden"
            : "group relative z-10 flex shrink-0 select-none cursor-row-resize focus:outline-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500"
        }
        style={{
          height,
          // 负 margin 把多出来的命中区盖到下一个 Panel 的标题栏上，
          // Group 实际分配的仍然是 thickness px。
          marginBottom: -(height - thickness),
          // 右侧按钮区不参与拖拽；可视条由子元素补满。
          width: `calc(100% - ${rightInset}px)`,
        }}
      >
        <span
          aria-hidden="true"
          className="pointer-events-none absolute left-0 top-0 block bg-gray-100 group-hover:bg-blue-100 group-focus-visible:bg-blue-200"
          style={{
            height: thickness,
            // 可视条跨过右侧按钮区，保持完整的一条分隔线。
            width: `calc(100% + ${rightInset}px)`,
          }}
        />
        <span
          aria-hidden="true"
          className="pointer-events-none absolute left-1/2 h-px w-8 -translate-x-1/2 bg-gray-300 group-hover:bg-blue-500"
          style={{ top: thickness / 2 }}
        />
      </Separator>
    );
  }

  return (
    <Separator
      id={handleId}
      aria-label={label}
      disabled={hidden}
      className={
        hidden
          ? "hidden"
          : `group flex shrink-0 select-none items-center justify-center bg-gray-100 hover:bg-blue-100 focus:outline-none focus-visible:bg-blue-200 ${
              horizontal ? "w-[6px] cursor-col-resize" : "h-[6px] w-full cursor-row-resize"
            }`
      }
      style={horizontal ? undefined : { height: thickness }}
    >
      <span
        aria-hidden="true"
        className={
          horizontal
            ? "pointer-events-none h-8 w-px bg-gray-300 group-hover:bg-blue-500"
            : "pointer-events-none h-px w-8 bg-gray-300 group-hover:bg-blue-500"
        }
      />
    </Separator>
  );
}
