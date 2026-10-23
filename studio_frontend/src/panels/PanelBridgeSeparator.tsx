// studio_frontend/src/panels/PanelBridgeSeparator.tsx
//
// 跨越"被最小化 Panel"的分隔线。
//
// Group 的 Panel 顺序必须保持稳定（卸载/重挂会丢聊天草稿、Canvas 视角），
// 所以中间 Panel 最小化后，库自带的 Separator 两端会各贴着一个隐藏 Panel，
// 无法在"左可见 ↔ 右可见"之间拖动。这里渲染一条**不注册进库**的分隔线：
// 它不参与 Separator 的邻接映射，自己按可见左/右 Panel 的像素尺寸做
// setLayout，鼠标和键盘都能把两侧剩余空间对分。
//
// 它始终是 Group 的直系子元素，但库只统计 Panel 和它自己注册的 Separator，
// 因此额外一条 6px 手柄不会改变百分比布局的总量。
import {
  useRef,
  useState,
  type PointerEvent as ReactPointerEvent,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from "react";
import type {
  GroupImperativeHandle,
  Layout,
  PanelImperativeHandle,
} from "react-resizable-panels";
import type { StudioPanelId } from "./panelLayout";

interface PanelBridgeSeparatorProps {
  orientation: "horizontal" | "vertical";
  label: string;
  groupRef: RefObject<GroupImperativeHandle | null>;
  panelRefs: Partial<Record<StudioPanelId, RefObject<PanelImperativeHandle | null>>>;
  leftId: StudioPanelId;
  rightId: StudioPanelId;
  /** 两侧 Panel 的最小像素尺寸。 */
  minLeft: number;
  minRight: number;
  /** 用户交互结束后把最终布局交给控制器持久化。 */
  onCommit: (layout: Layout) => void;
}

interface DragStart {
  pointerId: number;
  coordinate: number;
  span: number;
  left: number;
  right: number;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

export default function PanelBridgeSeparator({
  orientation,
  label,
  groupRef,
  panelRefs,
  leftId,
  rightId,
  minLeft,
  minRight,
  onCommit,
}: PanelBridgeSeparatorProps) {
  const dragRef = useRef<DragStart | null>(null);
  const [, setRevision] = useState(0);
  const horizontal = orientation === "horizontal";

  const measure = () => {
    const handle = groupRef.current;
    const layout = handle?.getLayout();
    if (!handle || !layout) return null;
    if (typeof layout[leftId] !== "number" || typeof layout[rightId] !== "number") {
      return null;
    }
    for (const id of [leftId, rightId]) {
      const size = panelRefs[id]?.current?.getSize();
      if (size && size.inPixels > 0 && size.asPercentage > 0.05) {
        return { layout, span: size.inPixels / (size.asPercentage / 100) };
      }
    }
    return null;
  };

  const geometry = (layout: Layout, span: number) => {
    const left = layout[leftId] ?? 0;
    const right = layout[rightId] ?? 0;
    const minLeftPct = span > 0 ? (minLeft / span) * 100 : 0;
    const minRightPct = span > 0 ? (minRight / span) * 100 : 0;
    const pair = left + right;
    const lower = Math.min(minLeftPct, pair);
    const upper = Math.max(lower, pair - minRightPct);
    return { left, right, pair, lower, upper };
  };

  const apply = (nextLeft: number, nextRight: number) => {
    const handle = groupRef.current;
    if (!handle) return undefined;
    const current = handle.getLayout();
    if (!current || Object.keys(current).length === 0) return undefined;
    const next: Layout = { ...current, [leftId]: nextLeft, [rightId]: nextRight };
    handle.setLayout(next);
    // 让 aria-valuenow/min/max 跟上当前布局（键盘用户读得到实时值）。
    setRevision((value) => value + 1);
    return next;
  };

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    const measured = measure();
    if (!measured) return;
    const { left, right } = geometry(measured.layout, measured.span);
    if (left <= 0 || right <= 0) return;
    dragRef.current = {
      pointerId: event.pointerId,
      coordinate: horizontal ? event.clientX : event.clientY,
      span: measured.span,
      left,
      right,
    };
    // 库在 document 的捕获阶段会把任意 Panel 边缘（包括中间被最小化的
    // Panel 的 0 宽边缘）当成拖拽起点，随后用它自己的初始布局覆盖我们的
    // 结果。桥接 Separator 不在库的注册表里，无法阻止它开场；这里主动
    // 发一个 pointerup 结束库的拖拽状态，把这条边界交还给我们。
    if (typeof document !== "undefined" && typeof PointerEvent === "function") {
      document.dispatchEvent(
        new PointerEvent("pointerup", {
          bubbles: true,
          pointerId: event.pointerId,
          pointerType: event.pointerType,
        }),
      );
    }
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  };

  const finishDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = dragRef.current;
    if (!start || start.pointerId !== event.pointerId) return;
    dragRef.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    const measured = measure();
    if (measured) onCommit(measured.layout);
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = dragRef.current;
    if (!start || start.pointerId !== event.pointerId) return;
    if (event.buttons === 0) {
      finishDrag(event);
      return;
    }
    const measured = measure();
    if (!measured) return;
    const coordinate = horizontal ? event.clientX : event.clientY;
    const delta = ((coordinate - start.coordinate) / start.span) * 100;
    const { pair, lower, upper } = geometry(measured.layout, start.span);
    const nextLeft = clamp(start.left + delta, lower, upper);
    if (Math.abs(nextLeft - (measured.layout[leftId] ?? 0)) < 0.01) return;
    apply(nextLeft, pair - nextLeft);
  };

  const nudge = (direction: "back" | "forward" | "min" | "max") => {
    const measured = measure();
    if (!measured) return;
    const { left, pair, lower, upper } = geometry(measured.layout, measured.span);
    const target =
      direction === "min"
        ? lower
        : direction === "max"
          ? upper
          : clamp(left + (direction === "back" ? -5 : 5), lower, upper);
    if (Math.abs(target - left) < 0.01) return;
    const next = apply(target, pair - target);
    if (next) onCommit(next);
  };

  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    switch (event.key) {
      case "ArrowLeft":
        if (horizontal) {
          event.preventDefault();
          nudge("back");
        }
        break;
      case "ArrowRight":
        if (horizontal) {
          event.preventDefault();
          nudge("forward");
        }
        break;
      case "ArrowUp":
        if (!horizontal) {
          event.preventDefault();
          nudge("back");
        }
        break;
      case "ArrowDown":
        if (!horizontal) {
          event.preventDefault();
          nudge("forward");
        }
        break;
      case "Home":
        event.preventDefault();
        nudge("min");
        break;
      case "End":
        event.preventDefault();
        nudge("max");
        break;
      default:
        break;
    }
  };

  const current = groupRef.current?.getLayout();
  const measuredNow = measure();
  const now =
    current && typeof current[leftId] === "number" ? Math.round(current[leftId]!) : undefined;
  const spanNow = measuredNow?.span ?? 0;
  const minNow =
    now === undefined || spanNow <= 0 ? undefined : Math.round((minLeft / spanNow) * 100);
  const maxNow =
    now === undefined || spanNow <= 0
      ? undefined
      : Math.round(
          (current?.[leftId] ?? 0) +
            (current?.[rightId] ?? 0) -
            (minRight / spanNow) * 100,
        );

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-label={label}
      aria-orientation={horizontal ? "vertical" : "horizontal"}
      aria-valuemin={minNow}
      aria-valuemax={maxNow}
      aria-valuenow={now}
      data-testid={`panel-bridge-${leftId}-${rightId}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finishDrag}
      onPointerCancel={finishDrag}
      onKeyDown={onKeyDown}
      className={`group flex shrink-0 touch-none select-none items-center justify-center bg-gray-100 hover:bg-blue-100 focus:outline-none focus-visible:bg-blue-200 ${
        horizontal ? "w-[6px] cursor-col-resize" : "h-[6px] w-full cursor-row-resize"
      }`}
    >
      <span
        aria-hidden="true"
        className={
          horizontal
            ? "pointer-events-none h-8 w-px bg-gray-300 group-hover:bg-blue-500"
            : "pointer-events-none h-px w-8 bg-gray-300 group-hover:bg-blue-500"
        }
      />
    </div>
  );
}
