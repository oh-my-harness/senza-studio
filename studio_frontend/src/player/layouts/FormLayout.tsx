// studio_frontend/src/player/layouts/FormLayout.tsx
//
// 一问一答型 agent 的形态：填表 → 一条时间线跟着流程往下长 → 结果。
// 这是默认形态，也是绝大多数 agent 的形态。
import { useEffect, useMemo, useRef } from "react";
import StepCard from "../Cards";
import DecisionPanel from "../DecisionPanel";
import PlayerShell from "../PlayerShell";
import StartForm from "../StartForm";
import type { LayoutProps } from "./types";

export default function FormLayout({
  info,
  phase,
  cards,
  pendingStep,
  error,
  finishedState,
  connected,
  onStart,
  onDecide,
  onCancel,
  onReset,
  compact = false,
}: LayoutProps) {
  const steps = info.steps;

  // display: "none" 的 step 直接不出现——作者在 spec 里就是这么标的：内部
  // 管道，不讲给最终用户听。
  //
  // 等决定的那个 step 也不单独出卡片，它的正文并进下面的决定区：分成两块的话
  // 同一件事出现两次（一张转圈的卡片 + 一块按钮），中间还隔着边框，读起来像
  // 是还有别的事在跑。
  const visible = useMemo(
    () =>
      cards.filter(
        (c) => (steps[c.stepId]?.display ?? "chat") !== "none" && c.stepId !== pendingStep
      ),
    [cards, steps, pendingStep]
  );

  const pendingCard = pendingStep
    ? [...cards].reverse().find((c) => c.stepId === pendingStep)
    : undefined;

  // 新卡片出现、或者轮到用户做决定时滚到底。只看数量不看正文——跟着每个
  // token 滚会把正在读的内容一直往上顶走。
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [visible.length, pendingStep, phase]);

  return (
    <PlayerShell info={info} connected={connected} compact={compact}>
      {phase === "idle" && !info.error && (
        <StartForm info={info} disabled={!connected} onStart={onStart} />
      )}

      {phase !== "idle" && (
        <>
          <div className="space-y-3">
            {visible.map((card, i) => (
              <StepCard key={`${card.stepId}-${i}`} card={card} step={steps[card.stepId]} />
            ))}
          </div>

          {pendingStep && (
            <DecisionPanel
              stepId={pendingStep}
              step={steps[pendingStep]}
              card={pendingCard}
              onDecide={onDecide}
            />
          )}

          {error && (
            <div className="rounded-lg border border-[var(--danger-border)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-text)]">
              {error}
            </div>
          )}

          <div ref={bottomRef} className="flex items-center gap-3 pt-2">
            {phase === "running" && !pendingStep && (
              <button
                onClick={onCancel}
                className="rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-1.5 text-sm text-[var(--text-muted)] hover:opacity-80"
              >
                取消
              </button>
            )}
            {phase === "done" && (
              <>
                <button
                  onClick={onReset}
                  className="rounded-lg bg-[var(--accent)] px-4 py-1.5 text-sm font-medium text-[var(--accent-fg)] hover:opacity-90"
                >
                  再来一次
                </button>
                {finishedState && finishedState !== "succeeded" && (
                  <span className="text-xs text-[var(--text-muted)]">
                    结束状态：{finishedState}
                  </span>
                )}
              </>
            )}
          </div>
        </>
      )}
    </PlayerShell>
  );
}
