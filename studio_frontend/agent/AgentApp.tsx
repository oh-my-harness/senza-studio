// studio_frontend/agent/AgentApp.tsx —— 导出 Agent 的宿主。
//
// 薄薄一层：拿契约、开 WebSocket、把状态映射成 AgentRunView 的 props。界面本身
// 在 src/player/ 里，和 Studio 的 Game view 是同一个组件——不然两边迟早长得
// 不一样。
import { useEffect } from "react";
import AgentRunView from "../src/player/AgentRunView";
import { useAgentRun } from "./useAgentRun";

export default function AgentApp() {
  const run = useAgentRun();

  useEffect(() => {
    if (run.info?.title) document.title = run.info.title;
  }, [run.info?.title]);

  if (!run.info) {
    return <div className="p-8 text-sm text-gray-400">加载中…</div>;
  }

  return (
    <AgentRunView
      info={run.info}
      phase={run.phase}
      cards={run.cards}
      pendingStep={run.pendingStep}
      error={run.error}
      finishedState={run.finishedState}
      connected={run.connected}
      onStart={run.start}
      onDecide={run.decide}
      onCancel={run.cancel}
      onReset={run.reset}
    />
  );
}
