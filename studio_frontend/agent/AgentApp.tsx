// studio_frontend/agent/AgentApp.tsx —— 导出 Agent 的完整界面。
//
// 这里只有三样东西：填输入、看进展、做决定。没有 DAG、没有 Inspector、
// 没有 Play/Pause/Step——那些是在 Studio 里做这个 agent 时用的，不是用它时
// 用的。取消是个例外：那是最终用户真会需要的动作（跑岔了要停下来），不是
// 调试器动词。
import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "../src/components/Markdown";
import { useAgentRun, type Card, type StepInfo } from "./useAgentRun";

/** 变量名 → 给人看的标签。customer_email → Customer email。
 *  spec 里没有给入口输入配标签的地方，与其显示裸变量名，不如做这个最小的
 *  美化；作者想要更好的文案时该做的是在 spec 里加标签，那是后面的事。 */
function humanize(name: string): string {
  const spaced = name.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function formatValue(v: unknown): string {
  if (v === undefined || v === null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function Spinner() {
  return (
    <span className="inline-block h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-gray-300 border-t-gray-600" />
  );
}

function CardShell({
  card,
  children,
  tone = "normal",
}: {
  card: Card;
  children: React.ReactNode;
  tone?: "normal" | "result";
}) {
  const base =
    card.status === "error"
      ? "border-red-200 bg-red-50 text-red-800"
      : tone === "result"
        ? "border-emerald-200 bg-emerald-50 text-gray-800"
        : "border-gray-200 bg-white text-gray-800";
  return (
    <div className={`rounded-xl border px-4 py-3 text-sm shadow-sm ${base}`}>
      <div className="mb-1.5 flex items-center gap-2 text-xs text-gray-500">
        {card.status === "running" && <Spinner />}
        <span>{tone === "result" ? "结果" : humanize(card.stepName)}</span>
      </div>
      {children}
    </div>
  );
}

function TableBody({ card, fields }: { card: Card; fields: string[] }) {
  if (fields.length === 0) return <Markdown text={card.text} />;
  return (
    <table className="w-full text-xs">
      <tbody>
        {fields.map((name) => (
          <tr key={name} className="border-t border-gray-200 first:border-t-0">
            <td className="whitespace-nowrap py-1.5 pr-4 align-top text-gray-500">
              {humanize(name)}
            </td>
            <td className="break-words py-1.5">{formatValue(card.fields?.[name])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ChartBody({ card, fields }: { card: Card; fields: string[] }) {
  const values = fields.map((f) => card.fields?.[f]).filter(isFiniteNumber);
  const max = Math.max(1, ...values.map(Math.abs));
  if (fields.length === 0) return <Markdown text={card.text} />;
  return (
    <div className="space-y-2">
      {fields.map((name) => {
        const value = card.fields?.[name];
        if (!isFiniteNumber(value)) {
          return (
            <div key={name} className="text-xs text-gray-600">
              {humanize(name)}: {formatValue(value)}
            </div>
          );
        }
        return (
          <div key={name}>
            <div className="mb-0.5 flex justify-between text-xs text-gray-600">
              <span>{humanize(name)}</span>
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

function StepCard({ card, step }: { card: Card; step: StepInfo | undefined }) {
  const display = step?.display ?? "chat";
  const fields = step?.fields ?? [];

  // status：一行进度，不占版面。作者用它标"正在做某件事但结果不值得展开"。
  if (display === "status") {
    return (
      <div className="flex items-center gap-2 px-1 py-1 text-xs text-gray-500">
        {card.status === "running" ? (
          <Spinner />
        ) : (
          <span className="h-3 w-3 shrink-0 text-center leading-3 text-gray-300">✓</span>
        )}
        {/* shrink-0 + min-w-0：不加的话 flex 会先压缩标签（"Classify message"
            被折成两行），而该被截断的是后面那段长文本 */}
        <span className="shrink-0 font-medium text-gray-600">{humanize(card.stepName)}</span>
        <span className="min-w-0 flex-1 truncate">{card.text}</span>
      </div>
    );
  }

  const tone = step?.terminal ? "result" : "normal";
  return (
    <CardShell card={card} tone={tone}>
      {display === "table" ? (
        <TableBody card={card} fields={fields} />
      ) : display === "chart" ? (
        <ChartBody card={card} fields={fields} />
      ) : card.text ? (
        <Markdown text={card.text} />
      ) : (
        <span className="text-xs text-gray-400">…</span>
      )}
    </CardShell>
  );
}

function StartForm({
  inputs,
  disabled,
  onStart,
}: {
  inputs: string[];
  disabled: boolean;
  onStart: (values: Record<string, string>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const ready = inputs.every((name) => (values[name] ?? "").trim() !== "");

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !disabled) onStart(values);
      }}
    >
      {inputs.map((name) => (
        <div key={name}>
          <label className="mb-1.5 block text-sm font-medium text-gray-700" htmlFor={name}>
            {humanize(name)}
          </label>
          <textarea
            id={name}
            rows={5}
            value={values[name] ?? ""}
            onChange={(e) => setValues((v) => ({ ...v, [name]: e.target.value }))}
            className="w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />
        </div>
      ))}
      <button
        type="submit"
        disabled={!ready || disabled}
        className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
      >
        开始
      </button>
    </form>
  );
}

export default function AgentApp() {
  const {
    info,
    connected,
    phase,
    cards,
    pendingStep,
    error,
    finishedState,
    start,
    decide,
    cancel,
    reset,
  } = useAgentRun();

  useEffect(() => {
    if (info?.name) document.title = info.name;
  }, [info?.name]);

  const steps = info?.steps ?? {};
  // display: "none" 的 step 直接不出现——作者在 spec 里就是这么标的：内部
  // 管道，不讲给最终用户听。
  //
  // 等决定的那个 step 也不单独出卡片：它的正文（审批要点）会并进下面的决定
  // 区。分成两块的话同一件事出现两次——一张转圈的卡片 + 一块按钮，中间还隔
  // 着边框，读起来像是还有别的事在跑。
  const visible = useMemo(
    () =>
      cards.filter(
        (c) => (steps[c.stepId]?.display ?? "chat") !== "none" && c.stepId !== pendingStep
      ),
    [cards, steps, pendingStep]
  );
  const choices = pendingStep ? (steps[pendingStep]?.choices ?? []) : [];
  const pendingText = pendingStep
    ? [...cards].reverse().find((c) => c.stepId === pendingStep)?.text ?? ""
    : "";

  // 新卡片出现、或者轮到用户做决定时滚到底。只看数量不看正文——跟着每个
  // token 滚会把正在读的内容一直往上顶走。
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [visible.length, pendingStep, phase]);

  if (!info) {
    return <div className="p-8 text-sm text-gray-400">加载中…</div>;
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto max-w-3xl px-6 py-5">
          <h1 className="text-lg font-semibold text-gray-900">{info.name}</h1>
          {info.description && (
            <p className="mt-1 text-sm text-gray-500">{info.description}</p>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-4 px-6 py-6">
        {info.error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
            这个 agent 没法运行：{info.error}
          </div>
        )}

        {!connected && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            与服务的连接已断开，刷新页面重试。
          </div>
        )}

        {phase === "idle" && !info.error && (
          <StartForm inputs={info.inputs} disabled={!connected} onStart={start} />
        )}

        {phase !== "idle" && (
          <>
            <div className="space-y-3">
              {visible.map((card, i) => (
                <StepCard
                  key={`${card.stepId}-${i}`}
                  card={card}
                  step={steps[card.stepId]}
                />
              ))}
            </div>

            {pendingStep && (
              <div className="rounded-xl border border-amber-300 bg-amber-50 px-4 py-3">
                <div className="mb-2 text-sm font-medium text-amber-900">需要你的决定</div>
                {pendingText && (
                  <div className="mb-3 text-sm text-amber-900/90">
                    <Markdown text={pendingText} />
                  </div>
                )}
                <div className="flex flex-wrap gap-2">
                  {choices.length === 0 ? (
                    <span className="text-xs text-amber-800">
                      这一步没有配置可选项，无法继续。
                    </span>
                  ) : (
                    choices.map((choice) => (
                      <button
                        key={choice}
                        onClick={() => decide(pendingStep, choice)}
                        className="rounded-lg bg-amber-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-amber-600"
                      >
                        {humanize(choice)}
                      </button>
                    ))
                  )}
                </div>
              </div>
            )}

            {error && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                {error}
              </div>
            )}

            <div ref={bottomRef} className="flex items-center gap-3 pt-2">
              {phase === "running" && !pendingStep && (
                <button
                  onClick={cancel}
                  className="rounded-lg border border-gray-300 bg-white px-4 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
                >
                  取消
                </button>
              )}
              {phase === "done" && (
                <>
                  <button
                    onClick={reset}
                    className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
                  >
                    再来一次
                  </button>
                  {finishedState && finishedState !== "succeeded" && (
                    <span className="text-xs text-gray-500">结束状态：{finishedState}</span>
                  )}
                </>
              )}
            </div>
          </>
        )}
      </main>
    </div>
  );
}
