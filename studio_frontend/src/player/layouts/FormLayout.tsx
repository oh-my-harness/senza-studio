// studio_frontend/src/player/layouts/FormLayout.tsx
//
// 一问一答型 agent 的形态：填表 → 一条时间线跟着流程往下长 → 结果。
// 这是默认形态，也是绝大多数 agent 的形态。
import { useEffect, useMemo, useRef, useState } from "react";
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

  // 玩家该看的"最终结果"是**已提交**的输出（validate_and_commit 的
  // player_face），不是终点 step 的流程标记文案。terminal 卡片的正文取
  // 它之前最后一张有实质内容的非 terminal 卡片；取不到才回退到 terminal
  // 自己的 message。流式文本只是过程展示，不进入这里。
  const committedResult = (() => {
    for (let i = visible.length - 1; i >= 0; i--) {
      const card = visible[i];
      if (steps[card.stepId]?.terminal) continue;
      if (card.text && card.text.trim()) return card.text;
    }
    return null;
  })();

  // 同一战役的继续：done 之后把"下一步行动"输入框直接递给玩家——
  // campaign_id / input_type / story_bible 沿用上一次提交的值，不重填。
  // input_type 强制留空走 auto 推断（继续绝不当作 new_campaign）。
  const [lastInputs, setLastInputs] = useState<Record<string, string> | null>(null);
  const handleStart = (vals: Record<string, string>) => {
    setLastInputs(vals);
    onStart(vals);
  };
  const continueInfo = lastInputs
    ? {
        ...info,
        inputs: info.inputs
          .filter((f) => !f.optional || f.name === "dice_result")
          .map((f) =>
            f.name === "player_input"
              ? { ...f, label: "下一步行动", placeholder: "你接下来做什么？（掷骰结果可直接填数字）" }
              : f,
          ),
      }
    : null;
  const pendingRequest = useMemo(() => {
    for (let i = visible.length - 1; i >= 0; i--) {
      const v = visible[i].fields?.pending_request;
      if (typeof v === "string" && v.trim()) return v.trim();
    }
    return "";
  }, [visible]);

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
            {visible.map((card, i) => {
              const step = steps[card.stepId];
              // 终点卡片的正文 = 已提交的叙事（来自前置 step 的权威输出）；
              // 拿不到时才显示终点自己的流程说明。
              const isTerminal = step?.terminal === true;
              const renderCard =
                isTerminal && committedResult ? { ...card, text: committedResult } : card;
              return <StepCard key={`${card.stepId}-${i}`} card={renderCard} step={step} />;
            })}
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

          {phase === "done" && continueInfo && (
            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
              <div className="mb-2 text-sm font-medium text-[var(--text)]">继续故事</div>
              <p className="mb-2 text-xs text-[var(--text-muted)]">
                战役 <span className="font-medium text-[var(--text)]">
                  {lastInputs?.campaign_id?.trim() || "default"}
                </span>{" "}
                已保存 — 输入你的下一个行动即可继续，无需重填其它信息。
              </p>
              <StartForm
                info={continueInfo}
                disabled={!connected}
                onStart={(next) => {
                  // 继续同一战役：campaign_id / story_bible 原样沿用，
                  // input_type 留空走 auto（继续绝不当作 new_campaign），
                  // dice_result 只在 GM 明确索要骰值时才填。
                  onReset();
                  onStart({
                    ...lastInputs,
                    ...next,
                    input_type: "",
                  });
                }}
              />
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
