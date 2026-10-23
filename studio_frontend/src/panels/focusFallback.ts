// studio_frontend/src/panels/focusFallback.ts
//
// 隐藏 Panel 的焦点回退。
//
// 最大化/最小化会在同一个 commit 里同时隐藏旧 Panel、显示新 Panel。
// React 的 passive effect 按 DOM 顺序执行，所以"隐藏 Chat、显示 Canvas"
// 时，Chat 的 effect 可能先跑，而 Canvas 的 `inert` 还没被移除；此时对
// Canvas 里的按钮调用 focus() 会被浏览器忽略，焦点就留在了隐藏区域。
//
// 因此这里先同步试一次（常见路径：目标本来可见），失败则先把焦点从隐藏
// 区域移走，再在 microtask（所有同批 effect 已执行完）和后续 RAF 里重试，
// 每次都重新确认目标没有 inert 祖先、仍在文档里且有布局盒。
const RETRY_FRAMES = 2;

interface FocusCandidate {
  focus(options?: FocusOptions): void;
  closest(selector: string): Element | null;
  isConnected: boolean;
  getClientRects?(): { readonly length: number };
}

/** 目标此刻是否真的可以接收焦点：未卸载、未被 inert 包住、有可见布局盒。 */
export function canReceiveFocus(target: FocusCandidate | null): target is FocusCandidate {
  if (!target) return false;
  if (!target.isConnected) return false;
  if (target.closest("[inert]") !== null) return false;
  if (typeof target.getClientRects === "function" && target.getClientRects().length === 0) {
    return false;
  }
  return true;
}

/**
 * 把焦点移到 `id` 对应的控件。返回取消函数：组件卸载或焦点目标变化时
 * 必须调用，避免迟到的一次 focus 抢走用户后来的焦点。
 *
 * `onUnavailable` 在目标当前不可聚焦时调用一次——调用方用它把焦点从即将
 * inert 的区域主动 blur 掉，保证等待期间焦点也不会停在隐藏内容里。
 */
export function focusFallbackTarget(
  doc: Document,
  id: string,
  onUnavailable?: () => void,
): () => void {
  let cancelled = false;
  let frame: number | null = null;

  const attempt = (remainingFrames: number) => {
    if (cancelled) return;
    const target = doc.getElementById(id) as FocusCandidate | null;
    if (canReceiveFocus(target)) {
      target.focus({ preventScroll: true });
      return;
    }
    if (remainingFrames <= 0) return;
    const view = doc.defaultView;
    if (view && typeof view.requestAnimationFrame === "function") {
      frame = view.requestAnimationFrame(() => {
        frame = null;
        attempt(remainingFrames - 1);
      });
    }
  };

  const immediate = doc.getElementById(id) as FocusCandidate | null;
  if (canReceiveFocus(immediate)) {
    immediate.focus({ preventScroll: true });
  } else {
    onUnavailable?.();
    // effect 批次结束后兄弟 Panel 的 inert 已更新；microtask 在这次 commit
    // 的所有 passive effect 之后运行，正好是第一次可靠的重试点。
    void Promise.resolve().then(() => attempt(RETRY_FRAMES));
  }

  return () => {
    cancelled = true;
    if (frame !== null) {
      doc.defaultView?.cancelAnimationFrame?.(frame);
      frame = null;
    }
  };
}
