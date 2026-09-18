// studio_frontend/src/player/layouts/DashboardLayout.tsx
//
// 数据型 agent 的形态：没有时间线，跑完的 step 直接变成一屏面板。
//
// 和表单布局的区别不是"好看一点"，是**读法不同**：一问一答要顺着读下来，
// 看板要一眼扫完。所以这里 status step 收成顶上一条进度，chat step 占满整行
// （散文需要宽度），table/chart 两列铺开。
import { useMemo } from "react";
import { CardBody, CardShell, Spinner } from "../Cards";
import DecisionPanel from "../DecisionPanel";
import PlayerShell from "../PlayerShell";
import StartForm from "../StartForm";
import type { LayoutProps } from "./types";

export default function DashboardLayout({
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

  const { panels, progress } = useMemo(() => {
    const panels = [];
    const progress = [];
    for (const card of cards) {
      const display = steps[card.stepId]?.display ?? "chat";
      if (display === "none" || card.stepId === pendingStep) continue;
      // status 是"正在做某件事"，不是结果——收进顶上那条进度，不占面板。
      if (display === "status") progress.push(card);
      else panels.push(card);
    }
    return { panels, progress };
  }, [cards, steps, pendingStep]);

  const pendingCard = pendingStep
    ? [...cards].reverse().find((c) => c.stepId === pendingStep)
    : undefined;

  const running = phase === "running";
  // 看板的"再跑一次"放页头：面板是这个页面的主体，按钮不该挤在它们中间。
  const actions =
    phase === "idle" ? null : (
      <button
        onClick={running ? onCancel : onReset}
        className={
          running
            ? "shrink-0 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-1.5 text-sm text-[var(--text-muted)] hover:opacity-80"
            : "shrink-0 rounded-lg bg-[var(--accent)] px-4 py-1.5 text-sm font-medium text-[var(--accent-fg)] hover:opacity-90"
        }
      >
        {running ? "取消" : "重新运行"}
      </button>
    );

  return (
    <PlayerShell info={info} connected={connected} compact={compact} actions={actions}>
      {phase === "idle" && !info.error && (
        <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-[var(--pad-card)]">
          <StartForm
            info={info}
            disabled={!connected}
            onStart={onStart}
            // 看板的输入是"查哪一段/哪个区域"这类参数，不是整段正文，挤成
            // 一条比堆成一列更像个查询条件栏。
            variant="inline"
            submitLabel="运行"
          />
        </div>
      )}

      {phase !== "idle" && (
        <>
          {progress.length > 0 && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-[var(--text-muted)]">
              {progress.map((card, i) => (
                <span key={`${card.stepId}-${i}`} className="flex items-center gap-1.5">
                  {card.status === "running" ? (
                    <Spinner />
                  ) : (
                    <span className="text-[var(--text-faint)]">✓</span>
                  )}
                  <span className="font-medium text-[var(--text)]">
                    {steps[card.stepId]?.title ?? card.stepName}
                  </span>
                  <span className="max-w-[24rem] truncate">{card.text}</span>
                </span>
              ))}
            </div>
          )}

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

          <div className="grid grid-cols-1 gap-[var(--gap)] md:grid-cols-2">
            {panels.map((card, i) => {
              const step = steps[card.stepId];
              const display = step?.display ?? "chat";
              // 散文和结果占满整行——两列里的一段长文本读起来很痛苦。
              const wide = display === "chat" || step?.terminal;
              return (
                <CardShell
                  key={`${card.stepId}-${i}`}
                  title={step?.terminal ? "结果" : (step?.title ?? card.stepName)}
                  status={card.status}
                  tone={step?.terminal ? "result" : "normal"}
                  className={wide ? "md:col-span-2" : ""}
                >
                  <CardBody card={card} step={step} />
                </CardShell>
              );
            })}
          </div>

          {phase === "done" && finishedState && finishedState !== "succeeded" && (
            <div className="text-xs text-[var(--text-muted)]">
              结束状态：{finishedState}
            </div>
          )}
        </>
      )}
    </PlayerShell>
  );
}
