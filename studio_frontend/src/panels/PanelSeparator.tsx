// studio_frontend/src/panels/PanelSeparator.tsx
//
// 统一的可抓取分隔线：可见宽度 6px（不是 1px 发丝线），中间有一条
// 视觉把手；不可见时 display:none 并 disabled，避免留下一条能拖却拖不动
// 的缝（相邻 Panel 已最小化/被最大化挤走）。
import { Separator } from "react-resizable-panels";

interface PanelSeparatorProps {
  orientation: "horizontal" | "vertical";
  label: string;
  hidden?: boolean;
}

export default function PanelSeparator({
  orientation,
  label,
  hidden = false,
}: PanelSeparatorProps) {
  const horizontal = orientation === "horizontal";
  return (
    <Separator
      aria-label={label}
      disabled={hidden}
      className={
        hidden
          ? "hidden"
          : `group flex shrink-0 select-none items-center justify-center bg-gray-100 hover:bg-blue-100 focus:outline-none focus-visible:bg-blue-200 ${
              horizontal ? "w-[6px] cursor-col-resize" : "h-[6px] w-full cursor-row-resize"
            }`
      }
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
