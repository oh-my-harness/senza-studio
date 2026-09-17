// studio_frontend/agent/useAgentRun.ts
import { useCallback, useEffect, useRef, useState } from "react";
import { PENDING_APPROVAL_ROUTE_KEY } from "../src/types";
import type { AgentInfo, CardStatus, RunCard, RunPhase } from "../src/player/types";

interface StructuredPayload {
  route_key?: string;
  fields?: Record<string, unknown> | null;
}

/** 导出 Agent 的一次运行：连接、发起、回答、取消。
 *
 * 没有用 Studio 的 zustand store：那个 store 有 27 个字段，绝大多数是编辑器
 * 的状态（spec、selectedStepName、sessions、logs、toolCalls…）。产品界面需要
 * 的只有下面这几样，共用一个 store 只会把编辑器的概念漏进来。
 */
export function useAgentRun() {
  const [info, setInfo] = useState<AgentInfo | null>(null);
  const [connected, setConnected] = useState(false);
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [cards, setCards] = useState<RunCard[]>([]);
  const [pendingStep, setPendingStep] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [finishedState, setFinishedState] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    fetch("/api/agent")
      .then((r) => r.json())
      .then(setInfo)
      .catch(() => setError("没能读到 agent 信息，服务可能没起来"));
  }, []);

  useEffect(() => {
    // React 18 StrictMode 会 mount → cleanup → 再 mount 一遍。上一轮的 socket
    // 常常在 handshake 完成前就被关掉，浏览器按异常断开处理——不加这个标志位
    // 就会把"连接断开"永久显示出来，即使真正的连接完全正常。
    let isCurrent = true;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const socket = new WebSocket(`${proto}//${location.host}/ws/run`);
    wsRef.current = socket;

    socket.onopen = () => {
      if (isCurrent) setConnected(true);
    };

    socket.onmessage = (e) => {
      if (!isCurrent) return;
      const event = JSON.parse(e.data);

      switch (event.type) {
        case "step_started":
          setCards((prev) => {
            // checker 被 resume 之后会再收到一次 step_started——同一个 step
            // 不是新卡片，别插重复的。
            const last = [...prev].reverse().find((c) => c.stepId === event.step_id);
            if (last && last.status === "running") return prev;
            return [
              ...prev,
              {
                stepId: event.step_id,
                stepName: event.step_name,
                text: "",
                status: "running" as CardStatus,
              },
            ];
          });
          break;

        case "text_delta":
          if (event.step_id) {
            setCards((prev) => patchLast(prev, event.step_id, (c) => ({
              ...c,
              text: c.text + (event.text || ""),
            })));
          }
          break;

        case "step_finished": {
          const structured = event.structured as StructuredPayload | null | undefined;
          if (structured?.route_key === PENDING_APPROVAL_ROUTE_KEY) {
            // 等人工决定：这一轮 run() 只是提前退出，step 并没有执行完。
            // 卡片保持 running，好让用户回答之后的第二次 step_finished 还能
            // 命中同一张卡片就地更新。
            setCards((prev) =>
              patchLast(prev, event.step_id, (c) => ({ ...c, text: event.output ?? c.text }))
            );
            setPendingStep(event.step_id);
          } else {
            setCards((prev) =>
              patchLast(prev, event.step_id, (c) =>
                c.status === "running"
                  ? {
                      ...c,
                      status: "done" as CardStatus,
                      text: event.output ?? c.text,
                      fields: structured?.fields,
                    }
                  : c
              )
            );
            setPendingStep(null);
          }
          break;
        }

        case "failed":
          setCards((prev) =>
            prev.map((c) => (c.status === "running" ? { ...c, status: "error" as CardStatus } : c))
          );
          setError(event.error || "运行失败");
          break;

        case "error":
          setError(event.message || "发生错误");
          break;

        case "workflow_done":
          setFinishedState(event.state);
          setPendingStep(null);
          setPhase("done");
          break;

        case "play_stopped":
          setPhase("idle");
          setPendingStep(null);
          setFinishedState(null);
          break;

        case "warning":
          // 插件没加载成功之类——最终用户对此无能为力，不往界面上堆。
          console.warn(event.message);
          break;

        // runtime_spec 故意忽略：展开后的展示配置已经由 /api/agent 给过了，
        // 产品界面不需要（也不该拿到）整份 spec。
      }
    };

    socket.onclose = () => {
      if (isCurrent) setConnected(false);
    };

    return () => {
      isCurrent = false;
      socket.close();
    };
  }, []);

  const start = useCallback((inputs: Record<string, string>) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    setCards([]);
    setError(null);
    setFinishedState(null);
    setPendingStep(null);
    setPhase("running");
    ws.send(JSON.stringify({ type: "start", inputs }));
  }, []);

  const decide = useCallback((stepId: string, decision: string) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    setPendingStep(null);
    ws.send(JSON.stringify({ type: "decision", step_id: stepId, decision }));
  }, []);

  const cancel = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(JSON.stringify({ type: "cancel" }));
  }, []);

  const reset = useCallback(() => {
    setCards([]);
    setError(null);
    setFinishedState(null);
    setPendingStep(null);
    setPhase("idle");
  }, []);

  return { info, connected, phase, cards, pendingStep, error, finishedState, start, decide, cancel, reset };
}

/** 就地更新某个 step 最后一张卡片。从后往前找：同一个 step 可能因为循环
 *  跑过多次，要改的永远是最近这一张。 */
function patchLast(cards: RunCard[], stepId: string, fn: (c: RunCard) => RunCard): RunCard[] {
  const idx = [...cards].reverse().findIndex((c) => c.stepId === stepId);
  if (idx === -1) return cards;
  const real = cards.length - 1 - idx;
  const next = [...cards];
  next[real] = fn(next[real]);
  return next;
}
