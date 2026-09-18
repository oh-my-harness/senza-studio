// studio_frontend/src/player/Cards.tsx —— 时间线/面板上的卡片，按 ui.display 分派。
//
// 颜色一律走 CSS 变量（见 theme.ts）：明暗两套色板和作者填的 accent 都在那边
// 决定，卡片本身不认识任何具体颜色，所以换主题、加 layout 都不用碰这里。
import Markdown from "../components/Markdown";
import type { AgentStep, RunCard } from "./types";

function formatValue(v: unknown): string {
  if (v === undefined || v === null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

export function Spinner() {
  return (
    <span className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-[var(--border)] border-t-[var(--text-muted)]" />
  );
}

export function CardShell({
  title,
  status,
  tone = "normal",
  children,
  className = "",
}: {
  title: string;
  status: RunCard["status"];
  tone?: "normal" | "result";
  children: React.ReactNode;
  className?: string;
}) {
  const skin =
    status === "error"
      ? "border-[var(--danger-border)] bg-[var(--danger-bg)] text-[var(--danger-text)]"
      : tone === "result"
        ? "border-[var(--ok-border)] bg-[var(--ok-bg)] text-[var(--text)]"
        : "border-[var(--border)] bg-[var(--surface)] text-[var(--text)]";
  return (
    <div
      className={`rounded-xl border p-[var(--pad-card)] text-sm shadow-sm ${skin} ${className}`}
    >
      <div className="mb-1.5 flex items-center gap-2 text-xs text-[var(--text-muted)]">
        {status === "running" && <Spinner />}
        <span>{title}</span>
      </div>
      {children}
    </div>
  );
}

/** 字段表。table 卡片和 approval_form 的审批要点共用——两者都是"把已经产出的
 *  结构化字段摆出来给人看"，只是摆的位置不同。 */
export function FieldTable({ card, fields }: { card: RunCard; fields: string[] }) {
  return (
    <table className="w-full text-xs">
      <tbody>
        {fields.map((name) => (
          <tr key={name} className="border-t border-[var(--border)] first:border-t-0">
            <td className="whitespace-nowrap py-1.5 pr-4 align-top text-[var(--text-muted)]">
              {name}
            </td>
            <td className="break-words py-1.5">{formatValue(card.fields?.[name])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function FieldChart({ card, fields }: { card: RunCard; fields: string[] }) {
  const values = fields.map((f) => card.fields?.[f]).filter(isFiniteNumber);
  const max = Math.max(1, ...values.map(Math.abs));
  return (
    <div className="space-y-2">
      {fields.map((name) => {
        const value = card.fields?.[name];
        if (!isFiniteNumber(value)) {
          return (
            <div key={name} className="text-xs text-[var(--text-muted)]">
              {name}: {formatValue(value)}
            </div>
          );
        }
        return (
          <div key={name}>
            <div className="mb-0.5 flex justify-between text-xs text-[var(--text-muted)]">
              <span>{name}</span>
              <span className="font-medium">{value}</span>
            </div>
            <div className="h-2 overflow-hidden rounded bg-[var(--surface-2)]">
              <div
                className="h-full bg-[var(--accent)]"
                style={{ width: `${Math.min(100, (Math.abs(value) / max) * 100)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** 卡片正文——按 display 选渲染方式。表单布局的时间线和看板布局的面板用的是
 *  同一个正文，只有外框不同。 */
export function CardBody({ card, step }: { card: RunCard; step: AgentStep | undefined }) {
  const display = step?.display ?? "chat";
  const fields = step?.fields ?? [];
  const useFields = (display === "table" || display === "chart") && fields.length > 0;
  if (display === "table" && useFields) return <FieldTable card={card} fields={fields} />;
  if (display === "chart" && useFields) return <FieldChart card={card} fields={fields} />;
  if (card.text) return <Markdown text={card.text} />;
  return <span className="text-xs text-[var(--text-faint)]">…</span>;
}

export default function StepCard({
  card,
  step,
}: {
  card: RunCard;
  step: AgentStep | undefined;
}) {
  const display = step?.display ?? "chat";
  const title = step?.title ?? card.stepName;

  // status：一行进度，不占版面。作者用它标"正在做某件事，但结果不值得展开"。
  if (display === "status") {
    return (
      <div className="flex items-center gap-2 px-1 py-1 text-xs text-[var(--text-muted)]">
        {card.status === "running" ? (
          <Spinner />
        ) : (
          <span className="h-3 w-3 shrink-0 text-center leading-3 text-[var(--text-faint)]">
            ✓
          </span>
        )}
        {/* shrink-0 + min-w-0：不加的话 flex 会先压缩标题（"Classify message"
            被折成两行），而该被截断的是后面那段长文本 */}
        <span className="shrink-0 font-medium text-[var(--text)]">{title}</span>
        <span className="min-w-0 flex-1 truncate">{card.text}</span>
      </div>
    );
  }

  return (
    <CardShell
      // 终点 step 是这次运行的**结果**，标题就直接说"结果"——它的 step 名
      // （flow_complete 之类）是给作者看的流程标记，不是给最终用户看的。
      title={step?.terminal ? "结果" : title}
      status={card.status}
      tone={step?.terminal ? "result" : "normal"}
    >
      <CardBody card={card} step={step} />
    </CardShell>
  );
}
