// studio_frontend/src/components/BottomPanel.activity.test.tsx
// ExecActivityRow 渲染回归测试:活动行经过时长不得重复时间单位后缀。
//
// 已确认回归:formatElapsed() 返回值自带单位后缀("37s"/"2m 37s"/"1h 2m"),
// ExecActivityRow 又追加了一个 "s",渲染出 "37ss"/"2m 37ss"/"1h 2ms"。
// 本仓库没有 jsdom/@testing-library,用 react-dom/server 的
// renderToStaticMarkup 做真实渲染断言(SSR 足以锁定 DOM 文本)。
import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ExecActivityRow } from "./BottomPanel";
import type { ExecActivity, ExecActivityPhase } from "../types";

type Phase = ExecActivityPhase;

// 把"现在"钉在 since + offset,让 formatElapsed 的输入确定。
function renderActivity(phase: Phase, sinceOffsetMs: number): string {
  const activity: ExecActivity = {
    scope: "step1",
    phase,
    since: 1_000_000,
    message: null,
  };
  const realNow = Date.now;
  Date.now = () => 1_000_000 + sinceOffsetMs;
  try {
    return renderToStaticMarkup(
      <ExecActivityRow scope="step1" activity={activity} />
    );
  } finally {
    Date.now = realNow;
  }
}

describe("ExecActivityRow elapsed rendering — no double suffix", () => {
  it("37s elapsed renders exactly once, not 37ss", () => {
    const html = renderActivity("waiting_model", 37_000);
    expect(html).toContain(">37s<");
    expect(html).not.toContain("37ss");
  });

  it("2m 37s elapsed renders exactly once, not 2m 37ss", () => {
    const html = renderActivity("waiting_model", 157_000);
    expect(html).toContain("2m 37s");
    expect(html).not.toContain("2m 37ss");
  });

  it("1h 2m elapsed renders exactly once, not 1h 2ms", () => {
    const html = renderActivity("model_generating", 3_723_000);
    expect(html).toContain("1h 2m");
    expect(html).not.toContain("1h 2ms");
  });
});
