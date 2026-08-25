# llm-harness-runtime 基础设施调研报告

调研对象：`../llm-harness-runtime`（Rust 内核，19 crate）。所有行号引用均为当前仓库实际实现。

## 1. Crate 依赖图

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

## 2. WorkflowEngine 核心

**文件**：`crates/llm-harness-workflow/src/workflow/`

### 2.1 数据模型 (model.rs)

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

### 2.2 运行循环 (engine/runner.rs, ~1896 行)

- `run()` — Idle|Paused→Running；Running→Running 处理崩溃恢复
- `run_loop()` — StepStarted → run_step → StepFinished → decide_transition → apply_transition → pause_if_requested(步边界)
- `pause_if_requested()` — 检查 `pause_requested: AtomicBool`，置 Paused + persist + 发事件

### 2.3 两条 pause 路径

1. **外部信号**：`engine.pause(reason)` 非阻塞设 AtomicBool → 步边界消费
2. **judge 主动**：`Transition::Pause{reason}` → 立即置 Paused + 发事件

两者汇聚到同一个 `Paused` 状态，走同一个 `resume()` 恢复。

### 2.4 事件流 (engine/event.rs)

`WorkflowEvent` enum，broadcast channel 容量 64：

| 事件 | 内容 |
|---|---|
| `StepStarted` | step_id, step_name |
| `StepFinished` | step_id, StepResult |
| `StepProgress` | ToolCallStart/End, ToolExecutionStart/End, TurnEnd, MessageEnd（**不含 TextDelta**） |
| `Paused` / `Resumed` / `Cancelled` / `Failed` | reason |

**关键**：text_delta 不透传到 WorkflowEvent。LLM streaming 需在 executor callback 里直接从 AgentHarness 取。

### 2.5 Judge (judge.rs)

- `StepTransitionJudge` trait — `decide(StepCtx) → Transition`
- `EdgeConditionJudge` — 声明式边求值，Label 边按 `structured.route_key` fallback 语义匹配
- `CompositeJudge` — 按 step_id 注册 handler + fallback
- `default_declarative_judge()` — 若 workflow 有 Expr/Label 边且 judge 是 Noop，自动启用 EdgeConditionJudge

### 2.6 Executor (executor.rs)

- `StepExecutor` trait — validate_step + execute + recover(崩溃恢复)
- 内置：`JsonTransformExecutor`、`ShellExecutor`(白名单)、`HttpCallExecutor`(白名单)
- Shell/HttpCall 需显式 `with_executor` 注入（安全设计）

### 2.7 TaskStore (lifecycle/task_store.rs)

- `JsonlTaskStore` — 落盘 `<base>/<task_id>/{plan.json, workflow.json, checkpoints.jsonl, event_wait.json}`；原子写(临时+rename)

## 3. AgentHarness 核心

### 3.1 Session 系统

| 组件 | 说明 |
|---|---|
| `SessionRepo` trait | create/open/list/delete/fork |
| `JsonlSessionRepo` | 生产持久化，`{root}/{id}/`，meta.json+entries.jsonl |
| `Session` | 树结构: append_message/branch/fork/navigate/build_context |
| `ObservedSessionRepo` | 包装任意 repo 发 SessionMutation 事件供 recall 投影 |

### 3.2 Compaction

- 阈值：reserve=16384, keep_recent=20000, context=200000
- CJK 权重 4（1 char/token，压缩更早触发）
- 结构化摘要格式：Goal/Progress/Key Decisions/Next Steps/Critical Context

## 4. Memory 系统

| 组件 | 说明 |
|---|---|
| `MemoryStore` trait | upsert/delete（不继承 KnowledgeSource，读写分离） |
| `MemoryService` | 组合 access_control + read_source + write_store + write_policy + mutation_gate |
| `SecureMemoryWritePolicy` | HMAC-SHA256 幂等 + 内容守卫(拒绝私钥/sk-/AKIA) + max_content_bytes=16KB |
| `MemoryMutationGate` | 审批网关（应用必须提供显式审批） |
| `MemoryMutationOrigin` | ExplicitTool/Application/Capture（运行时注入，不从模型参数反序列化） |

## 5. Session Recall

| 组件 | 说明 |
|---|---|
| `SessionRecallIndex` trait | search/replace_session/remove_session/rebuild |
| `SqliteSessionRecallIndex` | SQLite FTS5, bm25() 排序, contentless FTS |
| `SessionRecallProjector` | 实现 SessionMutationObserver, 增量投影 |
| `SessionRecallService` | search 后对照 Session 权威源重新校验 |
| `HistoryRecallPlugin` | 自动注入召回历史（TransformContextHook），有预算上限 |

## 6. Knowledge 系统

| 组件 | 说明 |
|---|---|
| `KnowledgeSource` trait | descriptor + search_projection + search + read |
| `KnowledgeRegistry` | 多源联邦搜索（逐源 authorize） |
| `LocalDocumentSource` | 本地 Markdown/Text, BM25 搜索, CJK 逐字 token |
| `EvidenceAuthority` + `CitationPolicy` | 证据权威 + 引用策略 |

## 7. Plugin trait

**文件**：`crates/llm-harness-agent/src/plugin.rs:70`

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

## 8. MCP 集成

- `McpManager` — 多 MCP server 生命周期管理
- `McpServerConfig` — stdio/HTTP/SSE 三种连接方式
- `discover_and_connect` — 运行时发现工具
- MCP server 的工具自动注册为 AgentHarness 可用工具

## 9. Strategy 层 (10 个 Plugin, runtime 不依赖)

SafetyDefaults / LoopSafety / InjectionFilter / MemoryDefense / ToolOutputGuard / SourceTag / ProjectInstruction / Audit / Notify / StatusPanel

## 10. Inspector / Viewer

- `llm-harness-inspector` — axum HTTP/WS 内省服务器（`SENZA_INSPECT` env, auth token）
- `session-viewer` — 零依赖静态 HTML viewer
