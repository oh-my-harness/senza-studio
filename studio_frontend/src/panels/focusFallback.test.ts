// studio_frontend/src/panels/focusFallback.test.ts
//
// 焦点回退的时序回归：目标在本 Panel 隐藏的同一批 effect 里才刚解除 inert，
// 同步 focus() 必须先失败、随后由 microtask/RAF 重试成功；等待期间旧焦点
// 必须被 blur 掉，而不是停在隐藏区域。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { canReceiveFocus, focusFallbackTarget } from "./focusFallback";

interface FakeTarget {
  focus: ReturnType<typeof vi.fn>;
  closest: (selector: string) => Element | null;
  isConnected: boolean;
  getClientRects: () => { length: number };
  inert: boolean;
}

function fakeTarget(overrides: Partial<FakeTarget> = {}): FakeTarget {
  const target: FakeTarget = {
    focus: vi.fn(),
    closest: (selector: string) =>
      selector === "[inert]" && target.inert ? ({} as Element) : null,
    isConnected: true,
    getClientRects: () => ({ length: 1 }),
    inert: false,
    ...overrides,
  };
  return target;
}

function fakeDocument(targets: Record<string, FakeTarget>) {
  return {
    getElementById: (id: string) => targets[id] ?? null,
    defaultView: {
      requestAnimationFrame: (callback: () => void) => setTimeout(callback, 16),
      cancelAnimationFrame: (handle: number) => clearTimeout(handle),
    },
  } as unknown as Document;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("canReceiveFocus", () => {
  it("rejects missing, detached, inert and unlaid-out targets", () => {
    expect(canReceiveFocus(null)).toBe(false);
    expect(canReceiveFocus(fakeTarget())).toBe(true);
    expect(canReceiveFocus(fakeTarget({ isConnected: false }))).toBe(false);
    expect(canReceiveFocus(fakeTarget({ inert: true }))).toBe(false);
    expect(canReceiveFocus(fakeTarget({ getClientRects: () => ({ length: 0 }) }))).toBe(false);
  });
});

describe("focusFallbackTarget", () => {
  it("moves focus synchronously when the fallback is already visible", () => {
    const target = fakeTarget();
    const unavailable = vi.fn();
    const cancel = focusFallbackTarget(
      fakeDocument({ "panel-maximize-chat": target }),
      "panel-maximize-chat",
      unavailable,
    );
    expect(target.focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(unavailable).not.toHaveBeenCalled();
    cancel();
  });

  it("waits until the target leaves an inert subtree instead of stealing focus", async () => {
    const target = fakeTarget({ inert: true });
    const unavailable = vi.fn();
    const cancel = focusFallbackTarget(
      fakeDocument({ "panel-maximize-chat": target }),
      "panel-maximize-chat",
      unavailable,
    );
    // 目标尚未解除 inert：不能聚焦，且旧焦点要立刻离开隐藏区域。
    expect(target.focus).not.toHaveBeenCalled();
    expect(unavailable).toHaveBeenCalledTimes(1);
    // 模拟同一次 commit 里稍后执行的兄弟 Panel effect。
    target.inert = false;
    await vi.advanceTimersByTimeAsync(0);
    expect(target.focus).toHaveBeenCalledTimes(1);
    cancel();
  });

  it("retries on the next frame when the target is still inert after the effect batch", async () => {
    const target = fakeTarget({ inert: true });
    const cancel = focusFallbackTarget(
      fakeDocument({ "dock-restore-canvas": target }),
      "dock-restore-canvas",
    );
    await vi.advanceTimersByTimeAsync(0);
    expect(target.focus).not.toHaveBeenCalled();
    target.inert = false;
    await vi.advanceTimersByTimeAsync(20);
    expect(target.focus).toHaveBeenCalledTimes(1);
    cancel();
  });

  it("never leaves focus in the hidden panel when the target never appears", async () => {
    const unavailable = vi.fn();
    const cancel = focusFallbackTarget(fakeDocument({}), "missing", unavailable);
    expect(unavailable).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(100);
    cancel();
  });

  it("cancels a pending retry so a late focus cannot steal the user's focus", async () => {
    const target = fakeTarget({ inert: true });
    const cancel = focusFallbackTarget(
      fakeDocument({ "panel-maximize-chat": target }),
      "panel-maximize-chat",
    );
    cancel();
    target.inert = false;
    await vi.advanceTimersByTimeAsync(100);
    expect(target.focus).not.toHaveBeenCalled();
  });
});
