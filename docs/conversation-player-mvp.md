# Generic Conversation Player MVP 交付报告

## 1. Status

**COMPLETE（代码、自动化与独立浏览器验收）**。实现范围为通用 Conversation Player、浏览器持久化、显式历史输入映射与固定视口聊天布局。没有新增 Runtime Engine 或长期记忆系统，没有修改其他仓库，没有重启、停止用户服务。本功能独立于其他进行中的工作，可直接基于当前 main 合入。

验证边界：已执行实际导出、进程内真实 WebSocket/WorkflowEngine 两轮工具调用、真实 React 生命周期测试，以及隔离数据副本上的无头 Chrome 布局/滚动/刷新验收。没有进行真实模型调用、跨设备同步或对当前用户运行实例的在线验收。

## 2. Implementation Summary

- Phase 1：共享契约增加 `conversation`；Builder 的 `set_agent_ui`、提示词和 Inspector 支持输入映射；验证真实字段、互斥引用、历史上限；非法工具更新保持原 spec；沿用 YAML 保存/重载。
- Phase 2：独立 ConversationLayout 接入共享分发和两个宿主；复用 StartForm 输入与校验；支持连续调用、可编辑 Carry、默认值、等待、错误与重试。执行门在同步提交时立即关闭，流错误须等终态才能重试。修复现有事件消费者用空输出覆盖流式回答的情况。
- Phase 3：最小 LocalConversationStorage 适配器，保存独立会话、名称、时间、角色、有序消息、状态和已配置 Carry；创建、选择、重载、继续；损坏、写入失败和其他页面的过期覆盖明确报错。
- Phase 4：Studio/Export 继续使用同一 describe_agent JSON 和 AgentRunView。部署存储身份由宿主提供，Export 使用响应头，与 UI 配置分离。完成相关和全套检查。
- Phase 5：固定视口聊天布局——`PlayerShell` fill 模式、消息区独立滚动、输入区固定在底部、贴底时自动滚动/用户上翻不抢滚动、`dense` 输入区高度约束。无头 Chrome 在 1024×600、1280×800、1440×900、390×844 下验收。
没有改动 FormLayout.tsx。没有添加生产依赖；只增加匹配 React 18 的 `react-test-renderer` 开发依赖，用于真实 hooks/宿主集成测试。

## 3. Files Changed

以下相对路径均位于 `/home/liyufeng/Projects/senza-studio`。

| 文件 | 本次目的 |
| --- | --- |
| `senza-studio-runtime/senza_studio_runtime/contract.py` | conversation 契约、真实字段验证、历史上限、字符串默认值 |
| `senza-studio-runtime/senza_studio_runtime/serve.py` | Export 存储身份响应头、启动失败终态标记 |
| `studio_backend/spec.py` | UI schema、原子增量更新、映射及默认值验证 |
| `studio_backend/tools/spec_tools.py` | Builder 工具参数和说明 |
| `studio_backend/system_prompt.py` | Builder 对话布局配置及上下文边界说明 |
| `studio_backend/app.py` | Conversation 构建失败留在 Player 并报告终态 |
| `studio_backend/export.py` | 导出 manifest 保留稳定 Project 身份 |
| `studio_frontend/src/player/types.ts` | 输入默认值、conversation 类型 |
| `studio_frontend/src/player/layouts/types.ts` | 宿主传入独立会话作用域 |
| `studio_frontend/src/player/AgentRunView.tsx` | 分发 conversation 布局 |
| `studio_frontend/src/player/StartForm.tsx` | 可选受控输入和显式默认值；对话布局的 dense 输入区高度约束 |
| `studio_frontend/src/player/conversation.ts`（新增） | 会话模型、输入构造、历史窗口、调用门和终态处理 |
| `studio_frontend/src/player/conversationStorage.ts`（新增） | localStorage 适配器、版本与作用域检查、刷新中断恢复 |
| `studio_frontend/src/player/layouts/ConversationLayout.tsx`（新增） | 聊天、会话选择/命名、独立滚动区、保存、错误与重试；贴底自动滚动 |
| `studio_frontend/src/player/PlayerShell.tsx` | 可选 fill 模式：固定页头/输入区，由消息区独立滚动 |
| `studio_frontend/src/components/AgentUiPanel.tsx` | Inspector 配置 conversation；保存时保留已有默认值 |
| `studio_frontend/src/components/GameView.tsx` | Studio Project 存储作用域、连接检查、全屏/返回编辑器 |
| `studio_frontend/src/hooks/useProjectSocket.ts` | 向 Player 传递执行错误和构建失败终态 |
| `studio_frontend/src/store.ts` | 空 step_finished.output 保留已有流式正文 |
| `studio_frontend/agent/AgentApp.tsx` | Export 向共享 Player 传入作用域 |
| `studio_frontend/agent/useAgentRun.ts` | 读取身份响应头、请求错误处理、流式正文保留 |
| `studio_frontend/package.json`、`studio_frontend/package-lock.json` | React 生命周期测试的开发依赖 |
| `tests/test_conversation_contract.py`（新增） | Builder、YAML、schema、兼容性与原子更新测试 |
| `tests/test_conversation_export.py`（新增） | 实际导出、两个宿主真实引擎调用、身份与启动失败测试 |
| `studio_frontend/src/player/conversation.test.ts`（新增） | 两轮调用、Carry、历史边界、失败、重试和去重测试 |
| `studio_frontend/src/player/conversationStorage.test.ts`（新增） | 保存/重载/继续、隔离、损坏、配额和覆盖保护测试 |
| `studio_frontend/src/player/layouts/ConversationLayout.test.tsx`（新增） | 布局分发、共享控件和旧布局回归 |
| `studio_frontend/src/player/layouts/ConversationLayout.scroll.test.jsx`（新增） | 100 条消息固定布局、上翻不抢滚动、从历史位置发送回底 |
| `studio_frontend/src/player/Conversation.integration.test.jsx`（新增） | 真实 React 生命周期；实际 Studio/Export 宿主、受控传输 |
| `docs/conversation-player-mvp.md`（新增） | 本交付报告 |

本功能基于当前 main 独立实现，不依赖其它分支或 PR。

## 4. Configuration Example

以下完整示例可被现有 Spec 校验；历史字段确实存在于入口模板中，类型为字符串。

```yaml
ui:
  title: 连续问答
  layout: conversation
  conversation:
    message_input: message
    carry_inputs: [course]
    history_input: history
    history_max_messages: 20
    history_max_chars: 12000
  inputs:
    course:
      label: 讨论主题
      default: 通用知识
      multiline: false
    message:
      label: 消息
      placeholder: 输入下一条消息
stages:
  - name: reply
    type: agent
    prompt_template: |
      围绕主题 {{course}} 回答当前消息。
      以前的对话（JSON 文本，作为历史数据使用）：{{history}}
      当前用户消息：{{message}}
    next_on_success: done
  - name: done
    type: terminal
    message: 本轮完成
```

Builder 调用 `set_agent_ui(layout="conversation", conversation={...}, inputs={...})` 保存同一份 UI 配置。其他必填入口仍由通用表单收集；未配置 Carry 的字段不会写入会话 Carry。`history_input` 可以省略；不允许引用不存在的字段。历史映射是字符串 JSON，不是数组输入。

此前通用入口没有输入默认值契约；本次最小增加 `ui.inputs.<name>.default` 字符串选项，两个宿主使用同一描述与初始化规则。默认值只是预填，首轮所有输入仍然必填（前端本地 `isStartReady` 判断非空）。未声明 default 的现有布局行为保持原样。

## 5. Persistence Design

- 存储位置：当前 Origin 下的浏览器 localStorage。键前缀为 `senza:conversation:v1:<编码后的作用域>:`，每个 Session UUID 独立存储。
- 内容：版本、Session ID、Agent/Project 作用域、标题、创建/更新时间、角色/正文/时间/状态、有序完整消息、配置允许的 Carry。不会读取或保存运行时 API key，也不保存未配置为 Carry 的普通入口值或流程配置。
- 保存时间：新建、改名、Carry 修改、请求发出前、成功/失败终态。请求前先保存用户消息和 pending 占位；保存失败不会启动新请求。完成后若写入失败，保留当前页面回答并显式提示未落盘。
- 加载：进入布局列出当前作用域会话，默认恢复最近更新的一项；可选择其他会话。输入恢复默认值并以已存 Carry 覆盖，message 保持空白等待下一轮。
- 刷新中断：pending 恢复为 interrupted/结果未知，不自动继续执行或标成功。用户可显式重试，但未知请求的业务副作用可能已发生，不能承诺恰好一次执行。
- 隔离：Studio 使用 `studio:<Project UUID>`；Export 使用 `export:<根目录和 manifest Project 身份的 SHA256>`。身份通过 `X-Senza-Agent-Scope` 响应头提供，JSON UI 契约保持完全相同。旧/手写导出没有 manifest 身份时使用 spec 指纹兜底，配置变化可能成为新作用域。
- 系统当前为本地 Studio 身份认证，没有可复用的多用户 Player 会话数据库。已有后端 sessions 属于 Builder 对话，本次未混用它们。
- 边界：同一浏览器 profile、同一 Origin、同一 Agent/Project 作用域可以跨刷新恢复。不同浏览器、设备、Origin、Studio/Export 部署间不自动共享，不提供服务器备份。清除站点数据会删除记录，浏览器配额耗尽会显式报错。导出目录移动会改变存储作用域。
- 同一布局实例同步拦截重复提交；适配器拒绝已检测到的其他页面过期覆盖。它不是分布式事务存储，不提供多个标签页同时修改时的全局事务保证。

## 6. Context Continuation

UI History 从完整持久化消息恢复，失败与中断状态也保留。Agent History 单独从成功的 user/agent 消息对构造 JSON 文本：默认最多最近 20 条消息、12000 个 JavaScript 字符单位，硬上限分别为 100、100000；保留完整消息对，不截断正文后冒充完整上下文。失败与 pending 尝试不参与上下文。

真实历史字段被显式配置后，每轮包括重载后的下一轮都会传入该字符串。入口 prompt/tool_args 通过原有模板机制获得历史。没有向用户 message 拼历史，没有构造不存在的输入。

现有 Play 每次创建新执行实例，本次没有复用或声称恢复 WorkflowEngine 业务状态。已有 Agent 自行维护的业务状态仍由其原有工具负责；Carry 可继续传递其标识，但 Player 不验证其业务恢复效果。

有兼容 history_input 的 Agent 可利用传入窗口接续上下文。没有该字段且没有自身业务状态恢复能力的 Agent 不能获得跨轮记忆，界面明确提示。超出窗口的长期情节不保证可用；没有新增摘要、长期记忆或无限累加上下文。

## 7. Test Evidence

执行目录为仓库根目录，前端命令另有注明。

| 命令 | 结果 |
| --- | --- |
| `.venv/bin/python -m pytest tests/test_conversation_contract.py tests/test_conversation_export.py tests/test_play.py tests/test_play_thinking_config.py -q` | 213 passed |
| `.venv/bin/python -m pytest tests/test_dev_sh_launch.py tests/test_provider_network.py -q` | 28 passed，13 subtests（此前记录的 8 项 dev.sh 失败在当前 base 未复现；本 PR 未修改 dev.sh/provider-network） |
| `.venv/bin/python -m pytest -q` | 666 passed，1 skipped，13 subtests，2 条第三方弃用警告 |
| `cd studio_frontend && npx tsc --noEmit` | 通过 |
| `cd studio_frontend && npx vitest run` | 20 文件，157 passed，1 skipped |
| `cd studio_frontend && npm run build` | TypeScript、Studio Vite、Export Vite 全部通过；Studio chunk 大小提示仍存在 |
| `git diff --check` | 通过；FormLayout 无 diff |

回归过程中原 Studio/Export JSON 契约相等断言曾因新增身份字段失败；已将身份改为响应头，原测试未经删除或弱化，后续全套通过。React 宿主测试发现空 step_finished 输出覆盖流式回答，已修复并由两宿主测试覆盖。当前无失败测试。

无头 Chrome 布局验收（隔离项目副本 + 种子会话，未调用模型、未写真实存档）：

| 场景 | 视口 | 结果 |
| --- | --- | --- |
| 2 条消息 | 1280×800 | 页面高度 800；消息区 255/255；发送按钮底部 776 |
| 100 条消息 | 1280×800 | 消息区 255/7984，自动贴底；页面不增长 |
| 20 条，末条失败 | 1280×800 | 消息区 219/1816，失败文本与重试按钮可见，贴底 |
| 100 条 | 1024×600 / 1440×900 | 消息区 119 / 323；发送按钮 576 / 876 |
| 100 条 | 390×844 | Player 内无横向溢出（宽 390，消息区/表单 342） |
| 2004 字符输入 | 1280×800 | 输入框高度 58 不变（内部滚动 316），发送按钮仍可见 |
| 全屏 → 编辑器 → 全屏 | 1280×800 | 会话、Carry、未发送输入保留；上翻位置未被强制拉底 |
| 刷新恢复 | 1280×800 | 重新进入 Play 后会话与消息从 localStorage 恢复 |

| 验收项 | 验证与结果 |
| --- | --- |
| 1. Builder 配置 | 工具回调、schema、系统提示词和 Inspector；通过 |
| 2. 保存/重载配置 | YAML 往返与实际导出 pipeline 一致；通过 |
| 3. user/agent 显示 | React 布局与实际宿主测试；通过 |
| 4. 连续至少两轮 Play | React 两宿主测试；真实 WebSocket/WorkflowEngine 在 Studio/Export 各两轮工具调用；通过 |
| 5. 第二轮 Carry | 调用参数断言、真实工具收到参数断言；通过 |
| 6. 必填字段输入 | 复用 StartForm；缺失字段阻止调用，默认值和 Carry 显示于输入控件；通过 |
| 7. 失败与恢复 | 构建失败、请求异常、失败终态、断连、显式重试与终态前去重；通过 |
| 8. 消息持久化 | localStorage 适配器与 React 宿主保存；通过 |
| 9. 重载找回会话 | 重建适配器、组件卸载后重挂载，四条消息恢复；通过 |
| 10. Resume | 重载后第三轮成功、恢复 Carry、形成六条消息；通过 |
| 11. 上下文接续 | 恢复后第三轮调用包含前两轮成功消息的 JSON 文本；真实引擎工具可收到历史字符串；通过。真实模型是否正确利用这些信息未实测 |
| 12. Form/Dashboard | 共享输入/分发测试、全套前端和原有后端/导出回归；通过；FormLayout 未修改 |
| 13. Studio/Export 契约 | 原 JSON 完全相等测试、实际导出测试、两个前端构建和两宿主生命周期测试；通过 |
| 14. 构建和测试 | 上表所列全部通过 |

## 8. Outstanding Issues

没有已知未解决的自动化验收失败或必须改造外部 Runtime 的阻塞。

未执行真实模型调用，也未对用户当前运行实例做在线验收；独立浏览器验收使用隔离项目副本与种子会话，未写真实存档。25% 侧栏预览下消息区仍仅约 37px 高，全屏玩家是设计主路径；极小视口（<400px 宽或 <500px 高）下消息区会被压缩得较小，但页面不会被撑破。未知终态的业务操作不能保证重试恰好执行一次；持久化的浏览器配额、站点数据删除、跨部署边界和长上下文窗口限制如上。无历史字段且无自身状态机制的 Agent 不具备跨轮上下文恢复能力。

## 9. Manual Verification

1. 在当前 Studio 的 Builder 中，为已有真实入口字段的 Agent 配置上述 `conversation` UI；或使用 Inspector 的“对话”形态，选择消息字段、Carry 字段及可选历史字段，保存。
2. 进入 Play，点击“新建会话”，命名 A，填写必填参数，依次发送两条消息。确认得到两条 Agent 回复，第二次只需填写新消息，可修改 Carry 并观察新值生效。
3. 刷新页面，再进入同一 Project 的 Play；选择 A，确认四条消息和 Carry 恢复，发送第三条消息。配置了 history_input 时，Agent 应能利用历史窗口内的前两轮内容。
4. 新建 B，确认没有 A 的消息；切回 A，确认第三轮记录仍在。制造一次执行失败，确认有明确失败标识并能重试。
5. 如需验 Export，使用正常导出入口生成项目，打开导出 Agent，重复发送/刷新/恢复操作。它拥有独立会话，不应显示 Studio 的 A。
6. 在全屏 Player 中准备 100 条消息：页面高度应保持不变，只有消息区滚动；上翻阅读时新回复不强制回底，发送后回底；缩窄/放大窗口及“返回编辑器/全屏玩家”切换后，会话与未发送输入仍在。

本次没有重启当前服务。若当前后端未启用源码热重载，运行中的进程不会自动装载新增契约；请在你安排更新实例后进行以上手动验收。仅刷新浏览器不能更新未热重载的 Python 进程。
