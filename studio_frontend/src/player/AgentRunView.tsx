// studio_frontend/src/player/AgentRunView.tsx
//
// **导出 Agent 的界面**，同时也是 Studio 里 Game view 渲染的东西——同一个组件，
// 两个宿主。Game view 是导出产品的预览，所以"看到的就是发出去的"必须是结构上
// 成立的，而不是靠人工把两份实现对齐（对齐过一次，然后就漂了）。
//
// 这一层只做一件事：按契约里的 layout 选一种形态。每种形态收的是**同一份**
// props（LayoutProps），所以形态之间不可能对同一次运行给出不一致的说法，加一
// 种形态也只是加一个文件。
//
// 纯展示：没有 store、没有 WebSocket、没有 fetch。状态和动作全部由宿主传进来
// （Studio 从 zustand store 映射，导出项目从 useAgentRun 映射）。
import DashboardLayout from "./layouts/DashboardLayout";
import FormLayout from "./layouts/FormLayout";
import type { LayoutProps } from "./layouts/types";

const LAYOUTS: Record<string, (props: LayoutProps) => JSX.Element> = {
  form: FormLayout,
  dashboard: DashboardLayout,
};

export type { LayoutProps as AgentRunViewProps };

export default function AgentRunView(props: LayoutProps) {
  // 认不出来的 layout 回落到 form。契约是后端给的，理论上只会是枚举里的值，
  // 但导出目录里的 pipeline.yaml 是用户可以手改的——手滑写错一个词不该白屏。
  const Layout = LAYOUTS[props.info.layout] ?? FormLayout;
  return <Layout {...props} />;
}
