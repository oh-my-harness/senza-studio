// studio_frontend/src/components/agentTeam/AgentTeamChatPanel.test.jsx
//
// 停止按钮的可判定性：只有探测确认是旧 Runtime（"unsupported"）才禁用。
// 探测本身失败（"unknown"）必须保持可用并给出"重新检测"，否则一次 502 或
// 掉网就会把按钮永久锁死在禁用态。这里用 react-test-renderer（与
// src/panels/useStudioPanelLayout.test.jsx 同一套约定），不引入 DOM 环境。
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";

import { TEAM_CONVERSATION_ID } from "../../agentTeamChat";
import AgentTeamChatPanel from "./AgentTeamChatPanel";

const STOP_TEST_ID = { "data-testid": "agent-team-stop-workflow" };
const RETRY_TEST_ID = { "data-testid": "agent-team-stop-probe-retry" };

// react-test-renderer 只有打开这个标志才把 act() 当成提交边界。
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function renderPanel(stopSupported, onRetryStopProbe = vi.fn()) {
  let renderer;
  act(() => {
    renderer = create(
      <AgentTeamChatPanel
        selectedTeam={{ id: "team-1" }}
        activeConversation={TEAM_CONVERSATION_ID}
        activeMember={null}
        members={[]}
        pulse={null}
        pulseByAgentId={new Map()}
        memberById={new Map()}
        connectionState="open"
        loadError={null}
        actionError={null}
        actionNotice={null}
        busyAction={null}
        chatFilter="all"
        setChatFilter={vi.fn()}
        showMentionMenu={false}
        setShowMentionMenu={vi.fn()}
        messageText=""
        setMessageText={vi.fn()}
        chatEndRef={{ current: null }}
        chatItems={[]}
        onRestartTeam={vi.fn()}
        onDeleteTeam={vi.fn()}
        onAbort={vi.fn()}
        onStopWorkflow={vi.fn()}
        stopSupported={stopSupported}
        onRetryStopProbe={onRetryStopProbe}
        onSendMessage={vi.fn()}
      />
    );
  });
  return {
    stopButton: renderer.root.findByProps(STOP_TEST_ID),
    retryButtons: renderer.root.findAllByProps(RETRY_TEST_ID),
    onRetryStopProbe,
  };
}

describe("stop control gating", () => {
  it("keeps Stop usable and offers a re-probe when the probe failed", () => {
    const { stopButton, retryButtons, onRetryStopProbe } = renderPanel("unknown");
    expect(stopButton.props.disabled).toBe(false);
    expect(stopButton.props.title).toContain("重新检测");
    expect(retryButtons).toHaveLength(1);
    act(() => {
      retryButtons[0].props.onClick();
    });
    expect(onRetryStopProbe).toHaveBeenCalledTimes(1);
  });

  it("disables Stop only for a proven older runtime", () => {
    const { stopButton, retryButtons } = renderPanel("unsupported");
    expect(stopButton.props.disabled).toBe(true);
    expect(stopButton.props.title).toContain("不支持停止工作流");
    expect(retryButtons).toHaveLength(0);
  });

  it("keeps Stop usable without a retry once supported", () => {
    const { stopButton, retryButtons } = renderPanel("supported");
    expect(stopButton.props.disabled).toBe(false);
    expect(retryButtons).toHaveLength(0);
  });

  it("keeps Stop usable before the first probe answers", () => {
    const { stopButton, retryButtons } = renderPanel(null);
    expect(stopButton.props.disabled).toBe(false);
    expect(retryButtons).toHaveLength(0);
  });
});
