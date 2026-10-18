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
