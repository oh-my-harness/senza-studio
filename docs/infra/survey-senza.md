# Senza SDK 基础设施调研报告

调研对象：`../Senza`（Rust+PyO3 Python SDK，封装 llm-harness-runtime）。所有行号引用均为当前仓库实际实现。

## 1. API 全景（lib.rs 注册）

模块入口 `#[pymodule] fn senza` 在 `src/lib.rs:70-302`。错误类型注册（全部继承自 pyerror 树）`lib.rs:76-173`（SenzaError/ProviderError/RateLimitError/…/CompactionError/StreamIdleTimeoutError 等 25+）。

**core 组** `lib.rs:195-238`：`PyAgent`（仅 test-utils 特性）；`PyEventIterator`、`PyHookWrapper`、`PyToolWrapper`、`PyToolContext`；`create_sync_tool/create_tool/create_judge/create_composite_judge/create_executor/create_shell_executor/create_http_executor/create_os_env/create_fs_tools_plugin/create_plugin`；`PyNativeTool` + `create_web_search_tool/create_web_fetch_tool/create_web_tools_plugin/create_code_exec_tool`；`PyInspector`、`PyHarnessBuilder`、`PyUsageLedger`、`PyPluginWrapper`。另有 `PyResponseFormat`/`PyProvider`/`create_openai_provider/create_anthropic_provider`。

**runtime 组**：`PyJudgeWrapper`、`PyCompositeJudge`、`PyExecutorWrapper`、`PyEnvWrapper`；`PyWorkflowEngine`、`PyWorkflowEventIterator`；`PyMcpServerConfig`、`PyMcpManager`；`PyPricingProvider`/`create_pricing_provider(_callback)`、`PyBudgetExceededHook`；`PyPredicate/PyRuleChain/PyRuleChainBuilder` + predicates + `create_rule_approval_hook`；`PySkill/load_skills`。

**strategy 组**：10 个 Plugin 工厂 + WebhookStream/TimerStream/HeartbeatStream/ShellMonitorStream + context-aware compaction prompt。

**knowledge 组**：`PyKnowledgeSource`+`create_local_knowledge_source`、`create_knowledge_plugin`；`PyMemoryStore/PyMemoryWritePolicy/PyMemoryMutationGate` + `create_in_memory_store/create_secure_write_policy/create_allow_all_gate/create_memory_plugin`；`PySessionRecallIndex/PySessionRepo/PySessionRecallKnowledgeSource` + `create_in_memory_session_recall_index/create_sqlite_session_recall_index/create_in_memory_session_repo/create_jsonl_session_repo/create_session_recall_knowledge_source/create_history_recall_plugin`。

**infra 组**：`PyJsonlAuditSink`、`PyInMemoryTraceExporter`、`PySandbox` + `create_seatbelt_sandbox`(macOS)/`create_bwrap_sandbox`(linux)。

Python 侧命名空间（`senza-pkg/senza/__init__.py`）：`providers/hooks/strategy/knowledge/infra/rules` 六个 `SimpleNamespace` 分组。

## 2. AgentHarness 能力（pyharness.rs + pybuilder.rs）

`PyAgentHarness` 方法全集：`prompt`、`message_count`、`get_messages`、`last_response`、`phase`、`events`、`abort`、`collect_until_settled`、`prompt_and_collect`、`chat`、`chat_async`、`prompt_async`、`set_model`、`set_system_prompt`、`set_temperature`、`set_thinking_level`、`set_max_tokens`、`set_tools`、`set_active_tools`、`steer`、`follow_up`、`continue_run`、`next_turn`、`compact`、`usage`、`usage_ledger`、`reset_usage`、`wait_for_idle`、`wait_for_settled`、`clear_steering_queue`、`clear_follow_up_queue`、`clear_all_queues`、`has_queued_messages`、`fork_branch`、`navigate_tree`、`list_branches`、`read_active_path`、`read_all_entries`、`delete_branch`、`generate_branch_summary`、`__enter__/__exit__`、`shutdown`、`mount_inspector`。

- **Streaming**：`PyHarnessEventIterator` 包装 broadcast receiver；`stream_prompt/stream_events` 提供 async 生成器。
- **Session 持久化**：builder `.session_repo(repo, session_id=...)` → `build()` 用 `repo.open(id)` 或 `repo.create()`。
- **Budget**：builder `.budget(limit, exceeded_hook)` = UsageLedger + BudgetControlAdapter。`.pricing(provider)`。
- **MCP**：`mcp_server(name, config)` / `mcp_config_file(path)` / `with_mcp_manager(manager)`。

## 3. WorkflowEngine（pyworkflow.rs）

方法：`new`、`restore`/`restore_from_step`/`list_tasks`（类方法）、`with_tool`/`with_external_tool`/`with_hooks`/`with_step_plugin`/`with_step_builder`/`with_executor`/`with_task_store`/`with_max_tokens`/`with_thinking_level`/`with_max_steps`/`with_max_retries`/`with_pricing`、`set/get_context_variable`、`run`/`run_async`、`task_id`、`state`、`current_step`、`step_history`、`pause`/`resume`/`cancel`、`checkpoint`、`total_cost`、`subscribe`、`inspect`。

**stages_to_workflow**（`pyworkflow.rs:642-785`）：声明式 pipeline dict → Workflow。terminal→`Step::Terminal`；非 terminal→`Step::Executor`（默认 `eda_executor`）；`next_on_*`→Label 边；`loop`→LoopConfig。

## 4. Session 持久化

`create_jsonl_session_repo(root_dir)` → `JsonlSessionRepo`（每 session 子目录 `{root}/{id}/`）。`HarnessBuilder.session_repo(repo, session_id=...)` 恢复。`create_sqlite_session_recall_index(path)` → FTS5 检索。`create_history_recall_plugin` → 自动注入召回历史。

## 5. Memory

`InMemoryStore` — **纯内存，不持久化**。`create_memory_plugin(source, store, policy, gate)` 注册 `memory_write/memory_forget` 工具。Python 无法继承 MemoryStore trait（无 trait 内建暴露）。**记忆持久化靠 SessionRecall，不靠 MemoryStore**。

## 6. Knowledge

`create_local_knowledge_source(path, source_id)` → BM25 索引本地文档。`create_knowledge_plugin(sources=[...])` → 注册 `knowledge_search/knowledge_read` 工具。

## 7. 工具系统

`create_tool(name, description, parameters, callback)` — 支持 sync/async，JSON Schema 参数。`@senza.tool` 装饰器用类型注解自动生成 schema。`create_fs_tools_plugin()` → bash/read/write/edit/grep/glob 六件套。

## 8. Hooks — 14 种

BeforeTurn/AfterTurn/BeforeRun/AfterProviderResponse/BeforeProviderRequest/BeforeToolCall/AfterToolCall/ShouldStop/BeforeCompact/TransformContext/PrepareNextTurn/FinalAnswerValidator/AfterRun/OnAbort。全部支持 async def。

## 9. strategy 层 — 10 个 Plugin

SafetyDefaults/LoopSafety/InjectionFilter/MemoryDefense/ToolOutputGuard/SourceTag/ProjectInstruction/Audit/Notify/StatusPanel。

## 10. 最佳实践

- 构建：`HarnessBuilder(model).provider().system_prompt().tool().plugin().build()`
- 流式：`async for e in senza.stream_prompt(harness, prompt)`
- Workflow：`WorkflowEngine(dict, provider, model, judge).with_executor(...).run()`
- 会话分支：`fork_branch/navigate_tree/read_active_path`
- RAG：`knowledge.local_source()` + `knowledge.plugin(sources=[...])`
