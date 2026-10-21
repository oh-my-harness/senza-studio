// studio_frontend/src/utils.ts
import type { ChatMessage, ToolCallEntry } from "./types";

/** 把从 /messages 拿到的历史记录拆成对话消息和工具调用两份——"tool" role
 * 的条目（调用工具:.../结果:...）不属于对话，挪到底部面板的"工具调用"
 * 标签页，不管是刚从后端加载的历史还是这次会话里实时收到的都一样处理。 */
export function splitToolCalls(messages: ChatMessage[]): {
  chat: ChatMessage[];
  tools: ToolCallEntry[];
} {
  const chat: ChatMessage[] = [];
  const tools: ToolCallEntry[] = [];
  for (const m of messages) {
    if (m.role === "tool") {
      tools.push({ content: m.content, toolName: m.toolName, timestamp: m.timestamp });
    } else {
      chat.push(m);
    }
  }
  return { chat, tools };
}

// ---- WebSocket 断连诊断 ------------------------------------------------
//
// CloseEvent 提供 code(u16)/wasClean/reason;code 仅 1000-1011 有标准含义
// (1006 是浏览器对异常断开的占位,reason 恒为空)。其他 code 不猜测人类
// 可读原因。ErrorEvent 没有任何诊断字段——诊断一律取自 CloseEvent。
const WS_CLOSE_CODE_LABELS: Record<number, string> = {
  1000: "normal closure",
  1001: "going away",
  1002: "protocol error",
  1003: "unsupported data",
  1005: "no status received",
  1006: "abnormal closure",
  1008: "policy violation",
  1009: "message too big",
  1010: "extension negotiation failed",
  1011: "internal server error",
};

export function wsCloseDiagnostics(e: {
  code?: number;
  wasClean?: boolean;
  reason?: string;
}): { text: string; detail: string } {
  const code = typeof e.code === "number" ? e.code : 1006;
  const clean = e.wasClean === true;
  const reason = typeof e.reason === "string" ? e.reason : "";
  const codeLabel = WS_CLOSE_CODE_LABELS[code] ?? `unknown code ${code}`;
  const detail = [
    `code=${code}${codeLabel ? ` (${codeLabel})` : ""}`,
    `clean=${clean}`,
    reason ? `reason=${reason}` : "reason=(浏览器未提供)",
  ].join("\n");
  return {
    text: `WebSocket disconnected · code=${code} · clean=${clean} · reconnect required`,
    detail,
  };
}

// 活动行经过时长格式化:<1min → "37s";≥1min → "2m 37s";≥1h → "1h 2m"。
export function formatElapsed(ms: number): string {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const sec = totalSec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (totalSec >= 60) return `${m}m ${sec}s`;
  return `${totalSec}s`;
}
