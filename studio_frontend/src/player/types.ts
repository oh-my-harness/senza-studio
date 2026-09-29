// studio_frontend/src/player/types.ts
import type { AgentTheme } from "./theme";
//
// 后端 contract.describe_agent 回的那份契约，以及一次运行的可观测状态。
// 这两样东西 Studio 的 Game view 和导出 Agent 完全一致——它们渲染的是同一个
// 产品（Game view 就是导出产品的预览），所以类型也只有这一份。

/** 一个入口输入字段。label/placeholder/multiline 都是后端算好的：默认值
 *  （humanize 出来的 label、多行）和作者在 spec 的 ui.inputs 里写的覆盖值，
 *  在后端就合并完了。前端不做任何猜测——猜测放在前端等于放两份。 */
export interface AgentInput {
  name: string;
  label: string;
  placeholder: string;
  multiline: boolean;
}

/** 停下来问人时的一个选项。value 是 next_on_<value> 的路由名，label 是给
 *  人看的文案。 */
export interface AgentChoice {
  value: string;
  label: string;
}

export interface AgentStep {
  title: string;
  /** chat / status / table / chart / approval_form / none */
  display: string;
  /** table / chart / approval_form 要展示的字段名 */
  fields: string[];
  /** 非空只可能出现在 checker 上——只有它会停下来问人 */
  choices: AgentChoice[];
  terminal: boolean;
}

export interface AgentInfo {
  title: string;
  description: string;
  /** 整体形态。后端回的永远是**最终生效的那个**（作者写的，或按流程形态
   *  猜的）——前端不该也去猜一遍，那就又是两份实现了。 */
  layout: string;
  theme: AgentTheme;
  inputs: AgentInput[];
  steps: Record<string, AgentStep>;
  /** 组件展不开之类——界面显示一条"这个 agent 装坏了"，而不是白屏 */
  error: string | null;
}

export type CardStatus = "running" | "done" | "error";

/** 时间线上的一张卡片。一个 step 在循环里跑多次就有多张。 */
export interface RunCard {
  stepId: string;
  stepName: string;
  text: string;
  status: CardStatus;
  fields?: Record<string, unknown> | null;
}

/** idle：还没跑 / running：跑着 / done：这一轮结束了（成功或失败）。
 *  刻意没有 "paused"：等人工决定时流程并没有停止，只是在等用户，界面上体现
 *  为多出一块决定区，不是换一个界面。 */
export type RunPhase = "idle" | "running" | "done";
