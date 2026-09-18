// studio_frontend/src/player/AgentRunView.tsx
//
// **导出 Agent 的界面**，同时也是 Studio 里 Game view 渲染的东西——同一个组件，
// 两个宿主。Game view 是导出产品的预览，所以"看到的就是发出去的"必须是结构上
// 成立的，而不是靠人工把两份实现对齐（对齐过一次，然后就漂了：默认值、标签、
// 审批区文案差了七八处）。
//
// 这里是纯展示：没有 store、没有 WebSocket、没有 fetch。状态和动作全部由宿主
// 传进来（Studio 从 zustand store 映射，导出项目从 useAgentRun 映射）。
import { useEffect, useMemo, useRef, useState } from "react";
import Markdown from "../components/Markdown";
import StepCard, { FieldTable } from "./Cards";
import type { AgentInfo, RunCard, RunPhase } from "./types";

function StartForm({
  info,
  disabled,
  onStart,
}: {
  info: AgentInfo;
  disabled: boolean;
  onStart: (values: Record<string, string>) => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const ready = info.inputs.every((field) => (values[field.name] ?? "").trim() !== "");

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !disabled) onStart(values);
      }}
    >
      {info.inputs.map((field) => (
        <div key={field.name}>
          <label
            className="mb-1.5 block text-sm font-medium text-gray-700"
            htmlFor={`input-${field.name}`}
          >
            {field.label}
          </label>
          {field.multiline ? (
            <textarea
              id={`input-${field.name}`}
              rows={5}
              placeholder={field.placeholder}
              value={values[field.name] ?? ""}
              onChange={(e) =>
                setValues((v) => ({ ...v, [field.name]: e.target.value }))
              }
              className="w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
          ) : (
            <input
              id={`input-${field.name}`}
              placeholder={field.placeholder}
              value={values[field.name] ?? ""}
              onChange={(e) =>
                setValues((v) => ({ ...v, [field.name]: e.target.value }))
              }
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
          )}
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

export interface AgentRunViewProps {
  info: AgentInfo;
  phase: RunPhase;
  cards: RunCard[];
  /** 正在等人工决定的 step id，没有就是 null */
  pendingStep: string | null;
  error: string | null;
  /** 运行的终态（succeeded / failed / cancelled…），没跑完就是 null */
  finishedState: string | null;
  /** 连接断了——宿主自己判断怎么算断 */
  connected: boolean;
  onStart: (inputs: Record<string, string>) => void;
  onDecide: (stepId: string, decision: string) => void;
  onCancel: () => void;
  onReset: () => void;
  /** Studio 的 Game view 是一条窄栏，导出是整页。窄的时候收一收边距，
   *  别的一律相同——"看起来一样"指的是同一套组件按容器自适应，不是像素级
   *  一致（一个 25% 的面板和一整页本来也不可能像素一致）。 */
  compact?: boolean;
}

export default function AgentRunView({
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
}: AgentRunViewProps) {
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
  const pendingInfo = pendingStep ? steps[pendingStep] : undefined;
  const choices = pendingInfo?.choices ?? [];
  // approval_form：把 checker 已经产出的结构化字段摆成表格，放在按钮上面。
  // 审批的人要看的是事实（分类结果、订单号、金额），不是一段散文。
  const approvalFields =
    pendingInfo?.display === "approval_form" ? (pendingInfo.fields ?? []) : [];

  // 新卡片出现、或者轮到用户做决定时滚到底。只看数量不看正文——跟着每个
  // token 滚会把正在读的内容一直往上顶走。
  const bottomRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [visible.length, pendingStep, phase]);

  const pad = compact ? "px-4 py-4" : "px-6 py-6";

  return (
    <div className="h-full overflow-y-auto bg-gray-50">
      <header className="border-b border-gray-200 bg-white">
        <div className={`mx-auto max-w-3xl ${compact ? "px-4 py-3" : "px-6 py-5"}`}>
          <h1
            className={`font-semibold text-gray-900 ${compact ? "text-base" : "text-lg"}`}
          >
            {info.title}
          </h1>
          {info.description && (
            <p className="mt-1 text-sm text-gray-500">{info.description}</p>
          )}
        </div>
      </header>

      <main className={`mx-auto max-w-3xl space-y-4 ${pad}`}>
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
          <StartForm info={info} disabled={!connected} onStart={onStart} />
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
                <div className="mb-2 text-sm font-medium text-amber-900">
                  需要你的决定
                </div>
                {approvalFields.length > 0 && pendingCard && (
                  <div className="mb-3 rounded-lg bg-white/70 px-3 py-2">
                    <FieldTable card={pendingCard} fields={approvalFields} />
                  </div>
                )}
                {pendingCard?.text && (
                  <div className="mb-3 text-sm text-amber-900/90">
                    <Markdown text={pendingCard.text} />
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
                        key={choice.value}
                        onClick={() => onDecide(pendingStep, choice.value)}
                        className="rounded-lg bg-amber-500 px-4 py-1.5 text-sm font-medium text-white hover:bg-amber-600"
                      >
                        {choice.label}
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
                  onClick={onCancel}
                  className="rounded-lg border border-gray-300 bg-white px-4 py-1.5 text-sm text-gray-600 hover:bg-gray-50"
                >
                  取消
                </button>
              )}
              {phase === "done" && (
                <>
                  <button
                    onClick={onReset}
                    className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
                  >
                    再来一次
                  </button>
                  {finishedState && finishedState !== "succeeded" && (
                    <span className="text-xs text-gray-500">
                      结束状态：{finishedState}
                    </span>
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
