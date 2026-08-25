# senza-agent 基础设施调研报告

调研对象：`../senza-agent`（通用 Agent，Senza SDK 最佳实践参考）。

## 1. 整体架构

```
senza-agent = Senza SDK 通用 Agent + aiohttp WebServer + Electron 壳
├── senza_agent/
│   ├── agent.py          # create_agent(): 完整 plugin 栈组装
│   ├── config.py         # 分层配置: file → env → derived
│   ├── persistence.py    # RunPersistence: per-run 目录, 原子写
│   ├── system_prompt.py  # 系统提示构建
│   ├── behavior/         # 行为层: advisor + acceptance_gate + wrapup
│   ├── tools/            # 工具层: standard(41) + graph + web_ui
│   ├── webserver/        # aiohttp: WS + render + terminal + files + apps
│   ├── interrupt.py      # 用户中断处理
│   └── i18n.py           # 国际化
├── desktop/main.js       # Electron 壳 (sidecar 模式)
├── SKILLS/               # Skill 定义 (coding, data_analysis, ui_app, ...)
├── AGENTS.md             # 运行规范 (工作目录、死循环处理、长耗时操作)
└── tests/
```

## 2. Agent 组装最佳实践 (agent.py:59-268)

`create_agent()` 是 **Senza SDK 完整 plugin 栈组装的参考范本**：

```python
builder = (
    senza.HarnessBuilder(config.model)
    .provider("*", provider)
    .system_prompt(system_prompt)
    .env(env)
    # 1. 文件工具
    .plugin(senza.create_fs_tools_plugin())
    # 2. 策略 Plugin 栈 (8 个)
    .plugin(senza.strategy.safety_defaults())
    .plugin(senza.strategy.loop_safety())
    .plugin(senza.strategy.status_panel())
    .plugin(senza.strategy.tool_output_guard(env))
    .plugin(senza.strategy.injection_filter())
    .plugin(senza.strategy.project_instruction(env))
    .plugin(senza.strategy.audit(config.audit_path))
    .plugin(senza.strategy.notify())
    # 3. Web/Code 工具
    .plugin(senza.create_web_tools_plugin(config))
    .tool(senza.create_code_exec_tool(timeout_secs=30))
    # 4. 行为工具 (submit_completion_report 等)
    .tools(behavior.tools)
    # 5. 行为 Hooks (advisor, context_injector, wrapup)
    .hooks(behavior.hooks)
    # 6. 验证器 (acceptance gate)
    .final_answer_validator(behavior.validator)
    .should_stop_hook(behavior.should_stop)
    # 7. Compaction + Retry
    .auto_compact(True)
    .retry(3, 1000)
)
```

**关键模式**：
- 每个 plugin/hook/tool 都有 try/except 保护，单个组件失败不阻塞整体
- Compaction 参数从 config 层层注入
- Session 持久化、Budget、UsageLedger、Skills、MCP、子 Agent spawn 全部条件装配
- Knowledge + Memory + History Recall 三件套条件装配

## 3. Behavior 模式 (behavior/)

senza-agent 实现了三层行为机制，Studio 的元 agent 可直接借鉴：

| 机制 | 说明 | 实现 |
|---|---|---|
| **Advisor** | 独立 LLM context 的战略顾问，每 N 轮触发，看精选上下文给指导 | advisor.py — 构建自己的 one-shot HarnessBuilder，不携带主 agent 对话历史 |
| **Acceptance Gate** | 3 阶段完成报告审查：报告完整性 → 证据文件存在性 → 情景记忆 | acceptance_gate.py — final_answer_validator hook |
| **Wrapup** | 结束前收尾：总结、清理、通知 | wrapup.py — prepare_next_turn hook + should_stop hook |
| **Context Injector** | 上下文注入：工作日志、scratchpad、进度 | context_injector.py — transform_context hook |

### 3.1 BehaviorBundle 组装 (bundle.py)

```python
class BehaviorBundle:
    def __init__(self, state, config):
        self.tools = acceptance_gate_tools(state)
        self.hooks = [
            senza.hooks.after_turn(advisor_runner(state, config)),
            senza.hooks.transform_context(behavior_transform_context(state)),
            senza.hooks.prepare_next_turn(wrapup_window(state, config)),
        ]
        self.validator = senza.hooks.final_answer_validator(
            acceptance_validator(state)
        )
        self.should_stop = senza.hooks.should_stop(behavior_should_stop(state))
```

### 3.2 Advisor 设计 (advisor.py)

- 独立 context：构建自己的 one-shot `HarnessBuilder`，不携带主 agent 对话历史
- 触发条件：周期性（每 N 轮）、按需（state.advisor_requested）、停滞检测
- 非致命：任何失败静默吞掉，不影响主循环
- 精选上下文：只传递 goal、progress、recent actions、user injections

### 3.3 Acceptance Gate (acceptance_gate.py)

3 阶段审查：
1. 完成报告完整性：必填字段（goal_understanding, completed_work, outcome, confidence）+ 证据文件存在性
2. 情景记忆（可选）
3. 综合判定：pass / weak_pass / needs_more_work

失败时返回错误字符串，反馈给模型让其补救。

## 4. 工具注册模式 (tools/registry.py)

```python
def get_standard_tools() -> list:
    tools = []
    tools.append(senza.create_tool(
        name="remember",
        description="Write an important conclusion to long-term memory.",
        parameters=_str_schema({"content": "The content to remember"}, ["content"]),
        callback=standard.tool_remember,
    ))
    # ... 41 个工具
    return tools
```

**模式**：工具函数（`standard.py`）与工具注册（`registry.py`）分离。`_str_schema` / `_mixed_schema` 辅助函数简化 JSON Schema 构建。

工具分类：
- Memory: remember, raw_append, recall_history
- Scratchpad: scratchpad_get, scratchpad_set
- Graph: plan_create, plan_revise, plan_abandon
- Web UI: web_show, terminal, file_tab, apps

## 5. Persistence 模式 (persistence.py)

Per-run 目录结构：
```
~/.senza-agent/runs/<YYYYMMDD-HHMMSS>/
├── short_term.jsonl      # append-only per-turn records
├── meta.json             # run metadata (atomic)
├── status.json           # run status snapshot (atomic)
├── scratchpad.md         # working scratchpad (atomic)
├── final_answer.md       # final answer (atomic)
├── execution_summary.md  # post-run summary (atomic)
├── advisor_log.jsonl     # append-only advisor entries
└── graph.json            # execution graph snapshot (atomic)
```

原子写：`tempfile.mkstemp` + `os.replace`，3 次重试（Windows 兼容）。

## 6. Config 模式 (config.py)

- `Config` 数据类：`WebConfig`, `BehaviorConfig`, `CompactionConfig`
- 从 `~/.senza-agent/config.json` 加载
- 环境变量覆盖
- `load_config()` 和 `create_provider()` 函数

## 7. WebServer 模式 (webserver/app.py)

aiohttp WebServer，端口 8090（与 Inspector 8080 并存）：

| 路由 | 功能 |
|---|---|
| `GET /ws` | render panel state stream (broadcast) |
| `GET /ws/term` | interactive terminal (per-client PTY) |
| `POST /api/show` | push content to panel |
| `GET /api/panels` | list all panels |
| `GET/POST/DELETE /api/term` | terminal session CRUD |
| `GET /api/fs/list?path=` | list directory |
| `GET /api/fs/read?path=` | read file |
| `PUT /api/fs/write` | write file |
| `POST /api/browser-action` | browser automation |
| `GET/POST/DELETE /api/app/:id` | app CRUD |
| `POST /api/app/:id/run` | run app |

## 8. Electron 壳 (desktop/main.js)

与 arcgensenza 相同的 sidecar 模式，但额外功能：
- `.env` 文件加载（Electron 侧读取后注入子进程环境）
- 端口检测（找空闲端口）
- 单实例锁
- 菜单栏定制

## 9. AGENTS.md 运行规范

senza-agent 的 AGENTS.md 是一个**通用 Agent 运行规范**，包含：
- 工作目录管理（$RUN_DIR vs 长期 workspace + WORKLOG.md）
- 死循环处理（3 次相同失败 → 换策略，5 次 → ask_user）
- 长耗时操作（shell_bg + 框架通知，不用轮询）
- Watcher 机制（框架推送式环境感知）
- 工具注册规范（register_tool，禁止改框架源码）

## 10. Studio 可借鉴要点

| 模式 | 来源 | Studio 用途 |
|---|---|---|
| 完整 plugin 栈组装 | agent.py create_agent() | 元 agent + 导出项目的 agent 构建模板 |
| try/except 条件装配 | agent.py 每个 plugin/hook/tool | 防止单组件失败阻塞整体 |
| Advisor 模式 | behavior/advisor.py | 元 agent 的战略指导层 |
| Acceptance Gate | behavior/acceptance_gate.py | spec 完成度审查 |
| 工具函数与注册分离 | tools/registry.py + standard.py | 预制件系统设计 |
| Per-run persistence | persistence.py | Studio 项目运行日志 |
| aiohttp WebServer | webserver/app.py | 导出项目 webui 的替代方案 |
| .env 加载 | desktop/main.js | Electron 壳 |
| AGENTS.md 规范 | AGENTS.md | 元 agent 的 system prompt 参考 |
