// studio_frontend/src/components/GameView.tsx
//
// Game view = **导出 Agent 界面的预览**。所以这里没有任何渲染逻辑：界面是
// src/player/AgentRunView，和导出项目跑的是同一个组件；数据是后端
// /api/projects/{id}/agent，和导出项目的 /api/agent 由同一个 describe_agent
// 生成。这个文件只做一件事——把 Studio 的 store 映射成那个组件要的 props。
//
// 以前这里自己翻 spec 算 ui.display、审批选项、标签，等于把同一套规则实现了
// 两遍；两份实现很快就不一样了（默认值、标签、审批区文案差了七八处）。
import { useEffect, useState } from "react";
import { api } from "../api";
import AgentRunView from "../player/AgentRunView";
import type { AgentInfo, RunPhase } from "../player/types";
import { useStudioStore } from "../store";

export default function GameView({ projectId }: { projectId: string }) {
  const [info, setInfo] = useState<AgentInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const ws = useStudioStore((s) => s.ws);
  const gameCards = useStudioStore((s) => s.gameCards);
  const pausedStepId = useStudioStore((s) => s.pausedStepId);
  const runFinishedState = useStudioStore((s) => s.runFinishedState);
  const playError = useStudioStore((s) => s.playError);
  const playStartPaused = useStudioStore((s) => s.playStartPaused);
  const resetPlay = useStudioStore((s) => s.resetPlay);

  // 进入运行视图时取一次契约。Game view 只在 status === "playing" 时挂载
  // （App.tsx），所以"挂载"就等于"用户刚点了 Play"——正好是该按当前 spec
  // 重新算一遍界面的时机。
  useEffect(() => {
    let alive = true;
    api
      .getAgent(projectId)
      .then((data) => alive && setInfo(data))
      .catch((e) => alive && setLoadError(String(e)));
    return () => {
      alive = false;
    };
  }, [projectId]);

  // 还没发 play 的时候就是 idle——这时 AgentRunView 显示的是开始表单，也就是
  // 最终用户打开导出产品看到的第一屏。入口输入从控制条搬到这里，就是为了让
  // 这一屏也能被预览到（它以前在 Studio 里根本没法看）。
  const started = gameCards.length > 0;
  const phase: RunPhase = runFinishedState ? "done" : started ? "running" : "idle";

  const send = (payload: Record<string, unknown>) => {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  };

  if (loadError) {
    return (
      <div className="h-full bg-gray-50 p-4 text-sm text-red-700">
        读不到界面配置：{loadError}
      </div>
    );
  }
  if (!info) {
    return <div className="h-full bg-gray-50 p-4 text-sm text-gray-400">加载中…</div>;
  }

  return (
    <AgentRunView
      info={info}
      phase={phase}
      cards={gameCards}
      pendingStep={pausedStepId}
      error={playError}
      finishedState={runFinishedState}
      connected={ws !== null}
      compact
      onStart={(inputs) =>
        // start_paused 是"从头单步"按钮记下的（控制条 → store → 这里）。
        // 它是调试用的，不属于产品界面，所以按钮留在控制条上。
        send({ type: "play", inputs, start_paused: playStartPaused })
      }
      onDecide={(stepId, decision) =>
        send({ type: "submit_decision", step_id: stepId, decision })
      }
      onCancel={() => send({ type: "stop" })}
      onReset={() => {
        // 回到开始表单，但不退出运行视图——"再来一次"是产品行为，"退回编辑"
        // 是控制条上的 Stop。后端那边上一轮的 play_task 已经结束，下一次
        // play 会新建一个 PlaySession（app.py 的 play 分支只挡还在跑的）。
        resetPlay();
      }}
    />
  );
}
