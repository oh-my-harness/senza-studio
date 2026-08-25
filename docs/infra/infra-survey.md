# Senza Studio — 现有基础设施与最佳实践调研

> 调研日期：2026-08-25
> 调研对象：Senza SDK、llm-harness-runtime、Folumi、arcgensenza、senza-agent
> 目的：为 Senza Studio 设计提供基础设施底座和可复用模式的全景图

---

## §1 技术栈全景

### 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  应用层                                                       │
│  Folumi (Tauri 桌面 Agent)    arcgensenza (EDA Agent)        │
│  senza-agent (通用 Agent)     Senza Studio (待建)             │
├─────────────────────────────────────────────────────────────┤
│  SDK 层                                                       │
│  Senza (PyO3, import senza)                                  │
│  · core: AgentHarness, Tool, Plugin, Hook, Provider          │
│  · runtime: WorkflowEngine, Judge, Executor, MCP             │
│  · strategy: 10 个安全/审计策略 Plugin                        │
│  · knowledge: Knowledge, Memory, SessionRecall               │
│  · infra: Audit, Trace, Sandbox                               │
├─────────────────────────────────────────────────────────────┤
│  Runtime 层 (Rust, 19 crates)                                │
│  llm-harness-runtime                                         │
│  L0 types → L1 loop → L2 agent → L3 platform/tools/          │
│  strategy/knowledge/inspector → L4 memory/session-recall     │
│  /knowledge-local/subagents/mcp → L5 workflow                │
├─────────────────────────────────────────────────────────────┤
│  Adapter 层                                                   │
│  llm-api-adapter (多 provider wire 格式归一化)                │
└─────────────────────────────────────────────────────────────┘
```

### 仓库清单

| 仓库 | 角色 | 语言 | 关键产出 |
|---|---|---|---|
| `llm-harness-runtime` | Rust 内核 | Rust | 19 crate，WorkflowEngine/AgentHarness/Session/Memory/Knowledge 全栈 |
| `Senza` | Python SDK | Rust+PyO3 | `pip install senza-sdk`，209 签名，497 tests |
| `Folumi` | 桌面 Agent 应用 | Rust+TS | Saved Memory SQLite 实现、Notebook、Session Recall、Tauri 壳 |
| `arcgensenza` | EDA Agent | Python | pipeline.yaml→workflow、FastAPI webui、Electron 壳、打包脚本 |
| `senza-agent` | 通用 Agent | Python | Senza SDK 最佳实践参考：plugin 栈组装、behavior 模式、webserver、Electron 壳 |

---

## §2 Runtime 层 (llm-harness-runtime)

### 2.1 Crate 依赖图

```
L0  llm-harness-types (根, 依赖 llm_adapter)
    session-viewer (零依赖独立 viewer)
L1  llm-harness-loop → types
L2  llm-harness-agent → types, loop
L3  llm-harness-platform → types, agent
    llm-harness-audit-jsonl → types
    llm-harness-sandbox → platform, types
    llm-harness-trace-otel → platform
    llm-harness-tools → agent, types
    llm-harness-strategy → types, agent (runtime 不依赖此 crate)
    llm-harness-knowledge → types, agent
    llm-harness-inspector → agent, types
L4  llm-harness-knowledge-local → types, knowledge
    llm-harness-memory → agent, types, knowledge
    llm-harness-session-recall → types, agent, knowledge
    llm-harness-subagents → agent, loop, types, platform
    llm-harness-mcp → platform, agent, types
L5  llm-harness-workflow → agent, loop, types, platform, subagents
L6  llm-harness-live-tests (聚合测试, publish=false)
```

关键：`types` 是纯根；`strategy` 刻意不被 runtime 依赖（用户按需引）；`workflow` 依赖链最深。

### 2.2 WorkflowEngine 核心

**文件**：`crates/llm-harness-workflow/src/workflow/`

#### 数据模型 (model.rs)

| 类型 | 说明 |
|---|---|
| `Workflow` | steps + edges + entry_step |
| `Step` enum | `Llm{prompt,allowed_tools,structured}` / `Executor{executor_name,config}` / `Terminal{exit_code,message}` |
| `Edge` | from + to + condition(Label 或 Expr) |
| `ConditionExpr` | 声明式 op: exists/missing/eq/ne/gt/gte/lt/lte/all/any/not，JSON pointer 求值 |
| `Transition` | `To(StepId)` / `Retry` / `Fail{reason}` / `Abort{reason}` / `Pause{reason}` |
| `WorkflowStatus` | Idle/Running/Paused/Succeeded/Failed/Cancelled |
| `StepExecutionPolicy` | timeout_ms + max_attempts + retry_backoff_ms + loop |
| `LoopConfig` | max_iterations + target_stage + exit_route |

#### 运行循环 (engine/runner.rs, ~1896 行)

- `run()` — Idle|Paused→Running；Running→Running 处理崩溃恢复
- `run_loop()` — StepStarted → run_step → StepFinished → decide_transition → apply_transition → pause_if_requested(步边界)
- `pause_if_requested()` — 检查 `pause_requested: AtomicBool`，置 Paused + persist + 发事件

#### 两条 pause 路径

1. **外部信号**：`engine.pause(reason)` 非阻塞设 AtomicBool → 步边界消费
2. **judge 主动**：`Transition::Pause{reason}` → 立即置 Paused + 发事件

两者汇聚到同一个 `Paused` 状态，走同一个 `resume()` 恢复。

#### 事件流 (engine/event.rs)

`WorkflowEvent` enum，broadcast channel 容量 64：

| 事件 | 内容 |
|---|---|
| `StepStarted` | step_id, step_name |
| `StepFinished` | step_id, StepResult |
| `StepProgress` | ToolCallStart/End, ToolExecutionStart/End, TurnEnd, MessageEnd（**不含 TextDelta**） |
| `Paused` / `Resumed` / `Cancelled` / `Failed` | reason |

**关键**：text_delta 不透传到 WorkflowEvent。LLM streaming 需在 executor callback 里直接从 AgentHarness 取。

#### Judge (judge.rs)

- `StepTransitionJudge` trait — `decide(StepCtx) → Transition`
- `EdgeConditionJudge` — 声明式边求值，Label 边按 `structured.route_key` fallback 语义匹配
- `CompositeJudge` — 按 step_id 注册 handler + fallback
- `default_declarative_judge()` — 若 workflow 有 Expr/Label 边且 judge 是 Noop，自动启用 EdgeConditionJudge

#### Executor (executor.rs)

- `StepExecutor` trait — validate_step + execute + recover(崩溃恢复)
- 内置：`JsonTransformExecutor`、`ShellExecutor`(白名单)、`HttpCallExecutor`(白名单)
- Shell/HttpCall 需显式 `with_executor` 注入（安全设计）

#### TaskStore (lifecycle/task_store.rs)

- `JsonlTaskStore` — 落盘 `<base>/<task_id>/{plan.json, workflow.json, checkpoints.jsonl, event_wait.json}`；原子写(临时+rename)

### 2.3 AgentHarness 核心

#### Session 系统

| 组件 | 说明 |
|---|---|
| `SessionRepo` trait | create/open/list/delete/fork |
| `JsonlSessionRepo` | 生产持久化，`{root}/{id}/`，meta.json+entries.jsonl |
| `Session` | 树结构: append_message/branch/fork/navigate/build_context |
| `ObservedSessionRepo` | 包装任意 repo 发 SessionMutation 事件供 recall 投影 |

#### Compaction

- 阈值：reserve=16384, keep_recent=20000, context=200000
- CJK 权重 4（1 char/token，压缩更早触发）
- 结构化摘要格式：Goal/Progress/Key Decisions/Next Steps/Critical Context

### 2.4 Memory 系统

| 组件 | 说明 |
|---|---|
| `MemoryStore` trait | upsert/delete（不继承 KnowledgeSource，读写分离） |
| `MemoryService` | 组合 access_control + read_source + write_store + write_policy + mutation_gate |
| `SecureMemoryWritePolicy` | HMAC-SHA256 幂等 + 内容守卫(拒绝私钥/sk-/AKIA) + max_content_bytes=16KB |
| `MemoryMutationGate` | 审批网关（应用必须提供显式审批） |
| `MemoryMutationOrigin` | ExplicitTool/Application/Capture（运行时注入，不从模型参数反序列化） |

### 2.5 Session Recall

| 组件 | 说明 |
|---|---|
| `SessionRecallIndex` trait | search/replace_session/remove_session/rebuild |
| `SqliteSessionRecallIndex` | SQLite FTS5, bm25() 排序, contentless FTS |
| `SessionRecallProjector` | 实现 SessionMutationObserver, 增量投影 |
| `SessionRecallService` | search 后对照 Session 权威源重新校验 |
| `HistoryRecallPlugin` | 自动注入召回历史（TransformContextHook），有预算上限 |

### 2.6 Knowledge 系统

| 组件 | 说明 |
|---|---|
| `KnowledgeSource` trait | descriptor + search_projection + search + read |
| `KnowledgeRegistry` | 多源联邦搜索（逐源 authorize） |
| `LocalDocumentSource` | 本地 Markdown/Text, BM25 搜索, CJK 逐字 token |
| `EvidenceAuthority` + `CitationPolicy` | 证据权威 + 引用策略 |

### 2.7 Plugin trait

```rust
pub trait Plugin: Send + Sync {
    fn name(&self) -> &str;
    fn register_tools(&self, _tools: &mut Vec<Arc<dyn Tool>>) {}
    fn register_hooks(&self, _hooks: &mut HarnessHooks) {}
    fn register_skills(&self, _skills: &mut Vec<Skill>) {}
    fn register_templates(&self, _templates: &mut Vec<PromptTemplate>) {}
}
```

四个贡献向量：tools、hooks、skills、templates。注册顺序决定组合行为（tool 冲突 last-wins, skill 冲突 first-wins）。**只在 harness 构建时注册，不支持运行时发现。**

### 2.8 MCP 集成

- `McpManager` — 多 MCP server 生命周期管理
- `McpServerConfig` — stdio/HTTP/SSE 三种连接方式
- `discover_and_connect` — 运行时发现工具
- MCP server 的工具自动注册为 AgentHarness 可用工具

### 2.9 Strategy 层 (10 个 Plugin, runtime 不依赖)

SafetyDefaults / LoopSafety / InjectionFilter / MemoryDefense / ToolOutputGuard / SourceTag / ProjectInstruction / Audit / Notify / StatusPanel

### 2.10 Inspector / Viewer

- `llm-harness-inspector` — axum HTTP/WS 内省服务器（`SENZA_INSPECT` env, auth token）
- `session-viewer` — 零依赖静态 HTML viewer

---

## §3 SDK 层 (Senza)

### 3.1 API 结构

PyO3 module `senza`，6 模块：core / runtime / strategy / knowledge / infra / providers。

Python 侧 `__init__.py` 二次封装为 `providers/hooks/strategy/knowledge/infra/rules` 命名空间 + `stream_prompt/stream_run` 异步封装 + `@senza.tool` 装饰器。

### 3.2 AgentHarness 方法全集

| 类别 | 方法 |
|---|---|
| prompt | prompt, prompt_and_collect, chat, chat_async, prompt_async |
| streaming | events, collect_until_settled, stream_prompt (模块级) |
| tool | set_tools, set_active_tools |
| session | get_messages, message_count, last_response |
| steering | steer, follow_up, next_turn, continue_run |
| compaction | compact |
| budget | usage, usage_ledger, reset_usage |
| 分支 | fork_branch, navigate_tree, list_branches, read_active_path, delete_branch, generate_branch_summary |
| 运行时配置 | set_model, set_system_prompt, set_temperature, set_thinking_level, set_max_tokens |
| 生命周期 | abort, shutdown, __enter__/__exit__, mount_inspector |

### 3.3 WorkflowEngine 方法全集

| 类别 | 方法 |
|---|---|
| 构造 | new, with_tool, with_external_tool, with_hooks, with_step_plugin, with_step_builder, with_executor, with_task_store |
| 参数 | with_max_tokens, with_thinking_level, with_max_steps, with_max_retries, with_pricing |
| 上下文 | set_context_variable, get_context_variable |
| 运行 | run, run_async |
| 恢复 | restore, restore_from_step, list_tasks (类方法) |
| 控制 | pause, resume, cancel, checkpoint |
| 查询 | state, current_step, step_history, task_id, total_cost, inspect |
| 事件 | subscribe |

### 3.4 stages_to_workflow

接受 `{"stages": [...]}` dict：
- `type: terminal` → `Step::Terminal`
- **其他所有 type** → `Step::Executor`（默认 executor 名 `"eda_executor"`）
- `prompt_template`、`output_key`、`tool` 等 reserved keys 保留但不解析（交给 executor callback）
- `next_on_*` 前缀 → `EdgeCondition::Label` 边
- `loop: {max_iterations, target_stage}` → `LoopConfig`

**Studio 的 pipeline.yaml 格式直接兼容**，但 `type: agent/checker/tool` 的语义执行需要 Studio 提供 executor callback。

---

## §4 Folumi — 记忆/Notebook/Session Recall 参考实现

### 4.1 整体架构

```
Folumi = Tauri 桌面壳 + AXUM Web 后端 (tutor-web) + llm-harness-runtime
├── src-tauri/          Tauri 壳, sidecar 拉起 tutor-web
├── crates/tutor-web/   AXUM 后端: memory_store, memory_runtime, session, notebook, routes
├── crates/tutor-agent/ Agent 构建: runtime_harness, chat, knowledge, capability
├── crates/tutor-rag/   LanceDB 知识源
└── web-ui/             React + TypeScript + Tailwind
```

### 4.2 Saved Memory 实现 (memory_store.rs, 1363 行)

**这是 Studio 决策记忆的直接参考实现。**

#### SQLite 表结构

```sql
CREATE TABLE memory_items (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK(kind IN ('fact','preference','goal','continuity')),
    content TEXT NOT NULL,
    topic_key TEXT,
    status TEXT NOT NULL CHECK(status IN ('active','resolved','superseded')),
    priority TEXT NOT NULL CHECK(priority IN ('normal','pinned')),
    origin TEXT NOT NULL CHECK(origin IN ('user_explicit','assistant_suggested')),
    provenance TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    last_confirmed_at TEXT NOT NULL, valid_until TEXT, resolved_at TEXT,
    revision TEXT NOT NULL
);
CREATE TABLE memory_relations (
    from_id TEXT, relation_type TEXT CHECK(relation_type IN ('supersedes')),
    to_id TEXT, PRIMARY KEY(from_id, relation_type, to_id)
);
CREATE TABLE memory_history (memory_id, revision, operation, prior_value, changed_at, origin);
CREATE TABLE memory_idempotency (policy_scope, idempotency_key, result_id, result_revision, created_at);
CREATE TABLE memory_tombstones (id TEXT PRIMARY KEY, deleted_at, content_hash);
CREATE VIRTUAL TABLE memory_items_fts USING fts5(memory_id UNINDEXED, content, topic_key);
```

#### 关键机制

| 机制 | 实现 |
|---|---|
| CAS (revision) | 每次变更生成新 revision，不匹配返回 Stale |
| supersede 事务 | BEGIN IMMEDIATE + 旧条目 superseded + 新条目创建 + relations 记录 |
| topic_key 冲突 | find_topic_conflict → Reject/Replace/KeepBoth |
| 写入授权 | origin: user_explicit/assistant_suggested + approval flow |
| idempotency | idempotency_key + policy_scope 唯一约束 |
| tombstones | 遗忘只保留 id + 删除时间 + 不可逆内容摘要 |
| schema migration | v1→v2→v3, PRAGMA user_version |

### 4.3 Memory Runtime 适配

```
SavedMemoryKnowledgeSource (读) → KnowledgeSource trait → knowledge_search/read
SavedMemoryWriteStore    (写) → MemoryStore trait     → memory_write/forget
SavedMemoryApprover           → 审批流程
```

组装链：`MemoryService(access_control, read_source, write_store, write_policy, mutation_gate)` → `MemoryPlugin`

### 4.4 Session Recall

```
SessionPool = JsonlSessionRepo (权威) + SqliteSessionRecallIndex (FTS5 投影)
├── history_recall_enabled 独立开关, 默认关闭
├── 临时对话不索引、不召回
├── 删除 Session → 同步删索引
├── 索引损坏 → 从 Session 权威源重建
└── ObservedSessionRepo → SessionMutationObserver → SessionRecallProjector 增量更新
```

### 4.5 设计文档要点 (user-memory-redesign)

- 退役旧 L1/L2/L3 分层模型
- 双通道：Saved Memory（显式、可编辑）+ History Recall（可选、按需）
- Memory 是全局的，不按 session/workspace 分区
- 写入只有三条路径：用户明确说"记住"、用户直接陈述+助手提议、用户手动新增
- 助手不得从模糊暗示中推断

---

## §5 arcgensenza — pipeline/webui/打包参考实现

### 5.1 整体架构

```
arcgensenza = pipeline.yaml → Senza WorkflowEngine + FastAPI/React WebUI + Electron 壳
├── pipeline.yaml              # 唯一编排真相
├── eda_agent_py/
│   ├── orchestrator/config.py # pipeline 解析
│   ├── workflow_adapter/ffi_bridge.py  # stages→workflow, executor, judge
│   ├── executor.py            # 按 type 分派 (agent/tool/checker)
│   ├── tools/registry.py      # ~35 个预制工具
│   └── agent_call.py          # LLM 调用
├── webui/ (FastAPI + React)
├── electron/main.cjs          # sidecar 壳
├── pack_python.sh             # 完整包
└── pack_code_only.sh          # 轻量包
```

### 5.2 executor/judge 分派模式

**路由模型**：executor 产 `route_key` → judge 结合 `next_on_*` 映射到转移字符串 → Rust 推进。

```python
# executor callback
def executor_cb(ctx):
    route_key = execute_stage(stage, ctx)  # 按 type 分派
    return {"output": ..., "structured": {"route_key": route_key}}

# judge callback
def judge_cb(ctx):
    route_key = ctx["structured"]["route_key"]
    next_stage = resolve_next(current_step, route_key, loop_counter)
    return f"to:{next_stage}"  # or "abort:done" / "fail:reason"
```

### 5.3 WebUI 模式

- 后端：FastAPI REST（薄包装）+ WebSocket（SnapshotWatcher 2s 轮询快照，SHA256 hash 去重推送）
- 前端：React + Vite + zustand，SessionSocket 指数退避重连

### 5.4 打包

| 脚本 | 产出 | 说明 |
|---|---|---|
| `pack_python.sh` | 完整包 | Python3.14+stdlib+site-packages，可选 `--bundle-glibc` |
| `pack_code_only.sh` | 轻量包 | 仅代码 |

### 5.5 Electron 壳

sidecar 模式：spawn Python webserver → 轮询 `/api/health` → BrowserWindow → 退出杀进程组。

---

## §6 senza-agent — Senza SDK 最佳实践参考

### 6.1 整体架构

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

### 6.2 Agent 组装最佳实践 (agent.py:59-268)

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

### 6.3 Behavior 模式 (behavior/)

senza-agent 实现了三层行为机制，Studio 的元 agent 可直接借鉴：

| 机制 | 说明 | 实现 |
|---|---|---|
| **Advisor** | 独立 LLM context 的战略顾问，每 N 轮触发，看精选上下文给指导 | advisor.py — 构建自己的 one-shot HarnessBuilder，不携带主 agent 对话历史 |
| **Acceptance Gate** | 3 阶段完成报告审查：报告完整性 → 证据文件存在性 → 情景记忆 | acceptance_gate.py — final_answer_validator hook |
| **Wrapup** | 结束前收尾：总结、清理、通知 | wrapup.py — prepare_next_turn hook + should_stop hook |
| **Context Injector** | 上下文注入：工作日志、scratchpad、进度 | context_injector.py — transform_context hook |

### 6.4 工具注册模式 (tools/registry.py)

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

### 6.5 Persistence 模式 (persistence.py)

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

### 6.6 WebServer 模式 (webserver/app.py)

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

### 6.7 Electron 壳 (desktop/main.js)

与 arcgensenza 相同的 sidecar 模式，但额外功能：
- `.env` 文件加载（Electron 侧读取后注入子进程环境）
- 端口检测（找空闲端口）
- 单实例锁
- 菜单栏定制

### 6.8 AGENTS.md 运行规范

senza-agent 的 AGENTS.md 是一个**通用 Agent 运行规范**，包含：
- 工作目录管理（$RUN_DIR vs 长期 workspace + WORKLOG.md）
- 死循环处理（3 次相同失败 → 换策略，5 次 → ask_user）
- 长耗时操作（shell_bg + 框架通知，不用轮询）
- Watcher 机制（框架推送式环境感知）
- 工具注册规范（register_tool，禁止改框架源码）

### 6.9 Studio 可借鉴的要点

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

---

## §7 对 Senza Studio 设计的基础设施映射

### 7.1 Studio 需求 → 基础设施映射

| Studio 需求 | 基础设施 | 复用方式 |
|---|---|---|
| 元 agent (AgentHarness) | Senza `HarnessBuilder` + `AgentHarness` | 直接用，参考 senza-agent create_agent() |
| 对话历史持久化 | Senza `JsonlSessionRepo` | 直接用 |
| 跨对话搜索 | Senza `SessionRecallIndex` (FTS5) + `HistoryRecallPlugin` | 直接用 |
| 决策记忆 | **Folumi `memory_store.rs`** | Python 重新实现，接入 SDK MemoryPlugin |
| pipeline.yaml 编译 | Senza `stages_to_workflow` | 直接用 SDK 侧 |
| step 语义执行 | arcgensenza executor callback 模式 | 参考，自建分派逻辑 |
| pause/resume/step | Senza `engine.pause/resume` + judge `Transition::Pause` | 直接用 |
| 事件流 (Scene 视图) | Senza `engine.subscribe()` → WorkflowEvent | 直接用 |
| LLM streaming (Game 视图) | AgentHarness `events()` / `stream_prompt` | executor callback 里取 |
| Inspector | runtime `Inspector` (axum) | 可选 |
| webui 后端 | arcgensenza FastAPI 或 senza-agent aiohttp | 参考自建 |
| webui 前端 | arcgensenza React+zustand | 参考自建 |
| 打包 | arcgensenza `pack_python.sh` | 参考自建 |
| Electron 壳 | arcgensenza/senza-agent sidecar 模式 | 参考自建 |
| Plugin 栈组装 | senza-agent `create_agent()` | 参考模板 |
| Advisor / 行为层 | senza-agent `behavior/` | 参考模式 |
| 预制件/插件 | Senza `Plugin` trait + `MCP` + `create_tool` | **需扩展（见下）** |

### 7.2 Plugin trait 的能力边界

**能做的**：注册工具、hooks、skills、templates（harness 构建时）

**不能做的**：运行时发现/安装、UI 组件注册、能力组件展开（workflow 片段）、版本管理/依赖声明、插件元数据

### 7.3 MCP 作为插件分发机制

**优势**：标准协议、跨语言、运行时发现工具、进程隔离

**局限**：只注册工具，不管 hooks/skills/templates/UI 组件/能力组件，没有插件市场机制

### 7.4 插件市场架构建议

基于现有基础设施，Studio 的插件体系应该是**三层模型**：

```
┌─────────────────────────────────────────────────┐
│  插件市场 (Plugin Registry)                      │
│  · 注册表：插件元数据                              │
│  · 搜索/安装/更新/版本管理                         │
├─────────────────────────────────────────────────┤
│  插件包 (Plugin Package)                          │
│  · manifest.yaml：声明插件提供什么                 │
│  · 三种贡献类型：                                  │
│    1. 工具预制件 → Senza create_tool / MCP server │
│    2. 能力组件 → workflow 片段模板                 │
│    3. UI 组件 → React 组件（前端注册）             │
├─────────────────────────────────────────────────┤
│  插件运行时 (Plugin Runtime)                      │
│  · 工具预制件 → Senza Plugin trait (register_tools)│
│  · 或 MCP server (运行时 discover_and_connect)     │
│  · 能力组件 → 元 agent 展开 (add_step/add_edge)    │
│  · UI 组件 → 前端组件注册表                         │
└─────────────────────────────────────────────────┘
```

**manifest.yaml 示例**：
```yaml
name: email-toolkit
version: 1.0.0
author: oh-my-harness
description: 邮件发送/接收/审批工具集
capabilities:
  tools:
    - name: send_email
      description: 发送邮件
    - name: read_inbox
      description: 读取收件箱
  components:
    - name: approval_flow
      description: 审批流组件
      stages_template: |
        - name: {prefix}_request
          type: tool
          tool: send_email
        - name: {prefix}_wait
          type: checker
          tool: wait_approval
  ui_components:
    - name: approval_form
      display: approval_form
      component: ./dist/ApprovalForm.js
```

**与现有基础设施的关系**：
- 工具预制件 = `senza.create_tool()` + `senza.create_plugin()` 或 MCP server
- 能力组件 = 元 agent 读 manifest 的 stages_template → `add_step`/`add_edge` 展开
- UI 组件 = 前端组件注册表（独立于 SDK，Studio 自己管理）
- 插件市场 = Studio 自己的注册表 + 安装机制（独立于 SDK 和 runtime）

**不需要改 SDK 或 runtime**——Plugin trait 和 MCP 是工具层的注入点，能力组件和 UI 组件是 Studio 应用层的概念。

---

## §8 待讨论的设计决策

1. **Play 覆盖用户手改代码**：spec 说重新 Play 覆盖代码。但定制工具被开发人员修改后，覆盖会冲掉工作。需要 code→spec 回路或 hash 对比策略。

2. **pipeline.yaml 和 ui_config.yaml 一致性**：两个文件平行，元 agent 改 pipeline 忘了同步 ui_config 怎么办。建议 ui_config 从 pipeline 派生默认值 + `validate_spec` 校验一致性。

3. **能力组件展开时机**：spec 说"元 agent 展开成多个 step+edge"。展开后不可逆，组件升级无法同步。建议 spec 里保留组件引用（`component: approval_flow`），运行时展开。

4. **Scene 视图复用 Studio 画布**：编辑态和只读态的复用粒度。建议共享渲染层但分离交互层（`<DAGCanvas mode="edit"|"readonly">`）。

5. **插件市场 v1 范围**：v1 是否需要完整的插件市场，还是先做 `senza-studio-components` 静态包 + MCP server 动态工具？

6. **元 agent 行为层**：是否借鉴 senza-agent 的 Advisor + Acceptance Gate 模式？元 agent 在构建 spec 时也可以有独立的"审查员"检查 spec 完整性。
