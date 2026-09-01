// studio_frontend/src/components/GameView.tsx
import { useEffect, useRef, useState } from "react";
import { useStudioStore } from "../store";
import Markdown from "./Markdown";
import type { GameCard } from "../types";

const STATUS_LABEL: Record<string, string> = {
  running: "运行中…",
  done: "完成",
  error: "出错",
};

type SpecLike = { stages: { name: string; ui?: { display?: string; fields?: string[] }; [k: string]: unknown }[] };

// checker step 的审批选项就是它自己的 next_on_* 标签（跟 play.py 的
// build_route_maps 读法一致）——不是写死的"批准/拒绝"，spec 作者可以自己
// 定义任意标签（比如 approve/escalate/reject）。
function routeLabelsFor(spec: SpecLike, stepName: string): string[] {
  const stage = spec.stages.find((s) => s.name === stepName);
  if (!stage) return [];
  return Object.keys(stage)
    .filter((k) => k.startsWith("next_on_") && typeof stage[k] === "string")
    .map((k) => k.slice("next_on_".length));
}

function displayConfigFor(spec: SpecLike, stepName: string): { display: string; fields: string[] } {
  const stage = spec.stages.find((s) => s.name === stepName);
  return { display: stage?.ui?.display ?? "chat", fields: stage?.ui?.fields ?? [] };
}

function formatFieldValue(v: unknown): string {
  if (v === undefined || v === null) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function StepCard({ card }: { card: GameCard; display: string; fields: string[] }) {
  return (
    <div
      className={`rounded-lg p-3 text-sm mr-8 ${
        card.status === "error" ? "bg-red-50 text-red-800" : "bg-gray-50 text-gray-800"
      }`}
    >
      <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
        <span className="font-medium">{card.stepName}</span>
        <span>{STATUS_LABEL[card.status]}</span>
      </div>
      <Markdown text={card.text} />
    </div>
  );
}

function StatusCard({ card }: { card: GameCard }) {
  return (
    <div
      className={`rounded-lg px-3 py-2 text-sm mr-8 flex items-center gap-2 ${
        card.status === "error" ? "bg-red-50 text-red-800" : "bg-gray-50 text-gray-800"
      }`}
    >
      <span className="font-medium shrink-0">{card.stepName}</span>
      <span className="truncate flex-1 text-gray-600">{card.text}</span>
      <span className="text-xs text-gray-500 shrink-0">{STATUS_LABEL[card.status]}</span>
    </div>
  );
}

function TableCard({ card, fields }: { card: GameCard; fields: string[] }) {
  return (
    <div
      className={`rounded-lg p-3 text-sm mr-8 ${
        card.status === "error" ? "bg-red-50 text-red-800" : "bg-gray-50 text-gray-800"
      }`}
    >
      <div className="flex items-center justify-between text-xs text-gray-500 mb-2">
        <span className="font-medium">{card.stepName}</span>
        <span>{STATUS_LABEL[card.status]}</span>
      </div>
      {fields.length === 0 ? (
        <div className="text-xs text-gray-400">未配置展示字段（set_ui_config 的 fields 参数）</div>
      ) : (
        <table className="w-full text-xs">
          <tbody>
            {fields.map((name) => (
              <tr key={name} className="border-t border-gray-200 first:border-t-0">
                <td className="py-1 pr-3 text-gray-500 align-top whitespace-nowrap">{name}</td>
                <td className="py-1 font-mono break-words">{formatFieldValue(card.fields?.[name])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ChartCard({ card, fields }: { card: GameCard; fields: string[] }) {
  const numericValues = fields
    .map((name) => card.fields?.[name])
    .filter((v) => isFiniteNumber(v)) as number[];
  const maxVal = Math.max(1, ...numericValues.map((v) => Math.abs(v)));

  return (
    <div
      className={`rounded-lg p-3 text-sm mr-8 ${
        card.status === "error" ? "bg-red-50 text-red-800" : "bg-gray-50 text-gray-800"
      }`}
    >
      <div className="flex items-center justify-between text-xs text-gray-500 mb-2">
        <span className="font-medium">{card.stepName}</span>
        <span>{STATUS_LABEL[card.status]}</span>
      </div>
      {fields.length === 0 ? (
        <div className="text-xs text-gray-400">未配置展示字段（set_ui_config 的 fields 参数）</div>
      ) : (
        <div className="space-y-1.5">
          {fields.map((name) => {
            const value = card.fields?.[name];
            if (isFiniteNumber(value)) {
              const pct = Math.min(100, (Math.abs(value) / maxVal) * 100);
              return (
                <div key={name}>
                  <div className="flex justify-between text-xs text-gray-600 mb-0.5">
                    <span>{name}</span>
                    <span>{value}</span>
                  </div>
                  <div className="h-2 rounded bg-gray-200 overflow-hidden">
                    <div className="h-full bg-blue-400" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            }
            return (
              <div key={name} className="text-xs text-gray-600">
                {name}: {formatFieldValue(value)}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function GameView() {
  const gameCards = useStudioStore((s) => s.gameCards);
  const spec = useStudioStore((s) => s.spec);
  const ws = useStudioStore((s) => s.ws);
  const pausedStepId = useStudioStore((s) => s.pausedStepId);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [gameCards, pausedStepId]);

  // 换成一个新的等待审批的 step（或者审批完清空）时，重置按钮的禁用态。
  useEffect(() => {
    setSubmitting(false);
  }, [pausedStepId]);

  const submitDecision = (decision: string) => {
    if (!ws || !pausedStepId || submitting) return;
    setSubmitting(true);
    ws.send(
      JSON.stringify({ type: "submit_decision", step_id: pausedStepId, decision })
    );
  };

  const routeLabels = pausedStepId ? routeLabelsFor(spec, pausedStepId) : [];

  return (
    <div className="flex flex-col h-full w-full bg-white">
      <div className="px-4 py-3 border-b border-gray-200 font-medium text-gray-700 shrink-0">
        Game View
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-3">
        {gameCards.length === 0 && (
          <div className="text-sm text-gray-400">等待运行开始…</div>
        )}
        {gameCards.map((card, i) => {
          const { display, fields } = displayConfigFor(spec, card.stepId);
          // "none" 的 step 依然记在 stepStatus/DAG 高亮里，只是不出现在
          // Game View 的时间线上——spec 作者用来隐藏不想讲给最终用户看的
          // 内部管道 step。
          if (display === "none") return null;
          const key = `${card.stepId}-${i}`;
          if (display === "status") return <StatusCard key={key} card={card} />;
          if (display === "table") return <TableCard key={key} card={card} fields={fields} />;
          if (display === "chart") return <ChartCard key={key} card={card} fields={fields} />;
          return <StepCard key={key} card={card} display={display} fields={fields} />;
        })}
        {pausedStepId && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm mr-8">
            <div className="text-amber-800 font-medium mb-2">
              ⏸ 等待人工审批 — {pausedStepId}
            </div>
            <div className="flex gap-2 flex-wrap">
              {routeLabels.length === 0 && (
                <span className="text-xs text-amber-700">
                  这个 checker step 没有配置 next_on_* 路由，无法提交决定
                </span>
              )}
              {routeLabels.map((label) => (
                <button
                  key={label}
                  onClick={() => submitDecision(label)}
                  disabled={submitting}
                  className="rounded-lg bg-amber-500 px-3 py-1 text-sm text-white hover:bg-amber-600 disabled:opacity-50"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
