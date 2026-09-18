// studio_frontend/src/player/Cards.tsx —— 时间线上的卡片，按 ui.display 分派。
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
    <span className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600" />
  );
}

function CardShell({
  title,
  card,
  tone = "normal",
  children,
}: {
  title: string;
  card: RunCard;
  tone?: "normal" | "result";
  children: React.ReactNode;
}) {
  const skin =
    card.status === "error"
      ? "border-red-200 bg-red-50 text-red-800"
      : tone === "result"
        ? "border-emerald-200 bg-emerald-50 text-gray-800"
        : "border-gray-200 bg-white text-gray-800";
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm shadow-sm ${skin}`}>
      <div className="mb-1.5 flex items-center gap-2 text-xs text-gray-500">
        {card.status === "running" && <Spinner />}
        <span>{tone === "result" ? "结果" : title}</span>
      </div>
      {children}
    </div>
  );
}

/** 字段表。table 卡片和 approval_form 的审批要点共用——两者都是"把已经产出的
 *  结构化字段摆出来给人看"，只是摆的位置不同。 */
export function FieldTable({
  card,
  fields,
}: {
  card: RunCard;
  fields: string[];
}) {
  return (
    <table className="w-full text-xs">
      <tbody>
        {fields.map((name) => (
          <tr key={name} className="border-t border-gray-200 first:border-t-0">
            <td className="whitespace-nowrap py-1.5 pr-4 align-top text-gray-500">
              {name}
            </td>
            <td className="break-words py-1.5">{formatValue(card.fields?.[name])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ChartBody({ card, fields }: { card: RunCard; fields: string[] }) {
  const values = fields.map((f) => card.fields?.[f]).filter(isFiniteNumber);
  const max = Math.max(1, ...values.map(Math.abs));
  return (
    <div className="space-y-2">
      {fields.map((name) => {
        const value = card.fields?.[name];
        if (!isFiniteNumber(value)) {
          return (
            <div key={name} className="text-xs text-gray-600">
              {name}: {formatValue(value)}
            </div>
          );
        }
        return (
          <div key={name}>
            <div className="mb-0.5 flex justify-between text-xs text-gray-600">
              <span>{name}</span>
              <span className="font-medium">{value}</span>
            </div>
            <div className="h-2 overflow-hidden rounded bg-gray-200">
              <div
                className="h-full bg-blue-500"
                style={{ width: `${Math.min(100, (Math.abs(value) / max) * 100)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function StepCard({
  card,
  step,
}: {
  card: RunCard;
  step: AgentStep | undefined;
}) {
  const display = step?.display ?? "chat";
  const fields = step?.fields ?? [];
  const title = step?.title ?? card.stepName;

  // status：一行进度，不占版面。作者用它标"正在做某件事，但结果不值得展开"。
  if (display === "status") {
    return (
      <div className="flex items-center gap-2 px-1 py-1 text-xs text-gray-500">
        {card.status === "running" ? (
          <Spinner />
        ) : (
          <span className="h-3 w-3 shrink-0 text-center leading-3 text-gray-300">✓</span>
        )}
        {/* shrink-0 + min-w-0：不加的话 flex 会先压缩标题（"Classify message"
            被折成两行），而该被截断的是后面那段长文本 */}
        <span className="shrink-0 font-medium text-gray-600">{title}</span>
        <span className="min-w-0 flex-1 truncate">{card.text}</span>
      </div>
    );
  }

  const useFields = (display === "table" || display === "chart") && fields.length > 0;
  return (
    <CardShell title={title} card={card} tone={step?.terminal ? "result" : "normal"}>
      {display === "table" && useFields ? (
        <FieldTable card={card} fields={fields} />
      ) : display === "chart" && useFields ? (
        <ChartBody card={card} fields={fields} />
      ) : card.text ? (
        <Markdown text={card.text} />
      ) : (
        <span className="text-xs text-gray-400">…</span>
      )}
    </CardShell>
  );
}
