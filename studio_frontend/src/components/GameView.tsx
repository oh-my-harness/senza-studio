// studio_frontend/src/components/GameView.tsx
import { useEffect, useRef } from "react";
import { useStudioStore } from "../store";
import Markdown from "./Markdown";

const STATUS_LABEL: Record<string, string> = {
  running: "运行中…",
  done: "完成",
  error: "出错",
};

export default function GameView() {
  const gameCards = useStudioStore((s) => s.gameCards);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [gameCards]);

  return (
    <div className="flex-1 h-full overflow-y-auto p-4 space-y-3 bg-white">
      {gameCards.length === 0 && (
        <div className="text-sm text-gray-400">等待运行开始…</div>
      )}
      {gameCards.map((card, i) => (
        <div
          key={`${card.stepId}-${i}`}
          className={`rounded-lg p-3 text-sm mr-8 ${
            card.status === "error"
              ? "bg-red-50 text-red-800"
              : "bg-gray-50 text-gray-800"
          }`}
        >
          <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
            <span className="font-medium">{card.stepName}</span>
            <span>{STATUS_LABEL[card.status]}</span>
          </div>
          <Markdown text={card.text} />
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
