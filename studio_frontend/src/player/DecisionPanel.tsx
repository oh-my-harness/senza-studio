// studio_frontend/src/player/DecisionPanel.tsx —— 等人工决定时的那一块。
//
// 两种布局共用：表单布局里它出现在时间线末尾，看板布局里它是一条横幅顶在
// 面板网格上面。"要不要停下来问人"是流程的性质，不是某一种排版的特性。
import Markdown from "../components/Markdown";
import { FieldTable } from "./Cards";
import type { AgentStep, RunCard } from "./types";

export default function DecisionPanel({
  stepId,
  step,
  card,
  onDecide,
}: {
  stepId: string;
  step: AgentStep | undefined;
  card: RunCard | undefined;
  onDecide: (stepId: string, decision: string) => void;
}) {
  const choices = step?.choices ?? [];
  // approval_form：把 checker 已经产出的结构化字段摆成表格，放在按钮上面。
  // 审批的人要看的是事实（分类结果、订单号、金额），不是一段散文。
  const formFields = step?.display === "approval_form" ? (step.fields ?? []) : [];

  return (
    <div className="rounded-xl border border-[var(--warn-border)] bg-[var(--warn-bg)] p-[var(--pad-card)]">
      <div className="mb-2 text-sm font-medium text-[var(--warn-text)]">需要你的决定</div>
      {formFields.length > 0 && card && (
        <div className="mb-3 rounded-lg bg-[var(--surface)] px-3 py-2 text-[var(--text)]">
          <FieldTable card={card} fields={formFields} />
        </div>
      )}
      {card?.text && (
        <div className="mb-3 text-sm text-[var(--warn-text)]">
          <Markdown text={card.text} />
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {choices.length === 0 ? (
          <span className="text-xs text-[var(--warn-text)]">
            这一步没有配置可选项，无法继续。
          </span>
        ) : (
          choices.map((choice) => (
            <button
              key={choice.value}
              onClick={() => onDecide(stepId, choice.value)}
              className="rounded-lg bg-[var(--accent)] px-4 py-1.5 text-sm font-medium text-[var(--accent-fg)] hover:opacity-90"
            >
              {choice.label}
            </button>
          ))
        )}
      </div>
    </div>
  );
}
