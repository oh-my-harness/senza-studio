// studio_frontend/src/player/layouts/types.ts
//
// 每种 layout 都收**同一份** props：同样的契约、同样的运行状态、同样四个动作。
// 加一种形态只是换一种排版，不是换一套数据——所以形态之间不可能对同一次运行
// 给出不一致的说法。
import type { AgentInfo, RunCard, RunPhase } from "../types";

export interface LayoutProps {
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
  /** Studio 的 Game view 是一条窄栏，导出是整页。窄的时候收一收边距，别的
   *  一律相同——"看起来一样"指的是同一套组件按容器自适应，不是像素级一致。 */
  compact?: boolean;
}
