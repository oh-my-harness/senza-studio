# Phase 0: WorkflowEvent TextDelta — 需求文档

> 阶段：Phase 0 of Senza Studio
> 仓库：`llm-harness-runtime`
> 状态：待实现

## 目标

让 WorkflowEngine 的 `subscribe()` 事件流包含 LLM step 的 streaming text delta，使外部订阅者（如 Studio 的 Game 视图）能实时渲染 LLM streaming 输出。

## 背景

当前 `WorkflowEvent` 有 `StepProgress`（ToolCallStart/End、TurnEnd、MessageEnd），但不含 text delta。`step_progress_from()` 函数（`event.rs:76`）明确将 `AgentEvent::TextDelta` 过滤为 `None`——注释写的是"TextDelta、ThinkingDelta 等不透传到 WorkflowEvent"。

`run_llm_step`（`runner.rs:1404`）内部已经在消费 `AgentEvent::TextDelta`——它把 text delta 拼接进 `text_delta_output` 字符串，用于 StepResult.output。但这个拼接是内部的，外部订阅者看不到中间过程。

## 需求

### 1. WorkflowEvent 加 TextDelta 变体

**文件**：`crates/llm-harness-workflow/src/workflow/engine/event.rs`

在 `WorkflowEvent` enum 里加一个变体：

```rust
/// LLM step 的 streaming text delta。
/// 高频事件，overflow 时优先丢弃——订阅者应容忍丢事件，
/// StepFinished 的 StepResult.output 有完整输出兜底。
TextDelta {
    step_id: StepId,
    text: String,
},
```

### 2. run_llm_step 转发 TextDelta

**文件**：`crates/llm-harness-workflow/src/workflow/engine/runner.rs`

当前 `run_llm_step` 的事件消费循环（约 `runner.rs:1393-1450`）里，`AgentEvent::TextDelta` 分支只做 `text_delta_output.push_str(text)`。改为：在拼接的同时，也通过 `self.event_tx.send()` 发出 `WorkflowEvent::TextDelta`。

```rust
AgentHarnessEvent::Agent(AgentEvent::TextDelta { text, .. }) => {
    text_delta_output.push_str(text);
    let _ = self.event_tx.send(WorkflowEvent::TextDelta {
        step_id: step.id().clone(),
        text: text.clone(),
    });
}
```

`let _ =` 忽略 send 错误（channel 满时 drop，不阻塞 step 执行）。

### 3. 不改 step_progress_from

`step_progress_from()` 继续对 `TextDelta` 返回 `None`。TextDelta 不走 `StepProgress` 通道，而是直接在 `run_llm_step` 里作为独立的 `WorkflowEvent` 变体发出。理由：

- `StepProgress` 是粗粒度事件（工具调用边界），TextDelta 是细粒度事件（token 流），语义不同
- 分开走更清晰，且 TextDelta 的 drop 策略和 StepProgress 不同（两者都可以 drop，但 TextDelta 更高频，更需要独立处理）

### 4. Executor step 不受影响

`ExecutorCtx` 不需要加 event sender。TextDelta 只在 LLM step（`run_llm_step`）里产生，因为只有 LLM step 内部创建 AgentHarness 并产生 streaming tokens。Executor step（`run_executor_step`）是确定性执行，不产生 text delta。

如果未来 Studio 的 executor callback 内部也创建 AgentHarness 并需要 streaming，那是一个后续需求——可以在 `ExecutorCtx` 加 event sender。但 Phase 0 不做。

### 5. Executor step 的 TextDelta（后续需求，不在 Phase 0）

Studio 的 executor callback 在 `type: agent` 的 step 里会创建自己的 AgentHarness。这个 Harness 的 streaming tokens 也需要回流到 WorkflowEvent。但这需要改 `ExecutorCtx` 加 event sender 字段，影响面更大。

Phase 0 只做 runtime 内置 LLM step（`Step::Llm`）的 TextDelta 转发。Studio executor callback 的 TextDelta 在 Phase 2 处理（那时 `ExecutorCtx` 加 sender 字段）。

## 不改什么

- `step_progress_from()` 不改
- `ExecutorCtx` 不改
- `StepExecutor` trait 不改
- broadcast channel 容量不改（64）
- `EVENT_CHANNEL_CAPACITY` 不改

## 测试

### 单元测试

在 `event.rs` 或 `runner.rs` 的测试模块里：

1. **TextDelta 出现在事件流**：构造一个 workflow 含一个 LLM step，运行后 subscribe，验证事件流里除了 StepStarted/StepFinished 之外还有 TextDelta 事件。
2. **TextDelta 文本拼接等于 StepResult.output**：收集所有 TextDelta 的 text 拼接，和 StepFinished 里 StepResult.output 比较（当没有 final_answer 时应该一致）。
3. **Channel 满时不阻塞**：不订阅 channel，运行 LLM step，验证 step 仍然正常完成（send 错误被忽略）。

### 集成测试

可以用现有的 `integration_test.rs` 或 `tests/` 目录加一个测试：真实 LLM 调用，验证 TextDelta 事件连续到达。

## 验收标准

- [ ] `WorkflowEvent` 有 `TextDelta { step_id, text }` 变体
- [ ] `run_llm_step` 在收到 `AgentEvent::TextDelta` 时发出 `WorkflowEvent::TextDelta`
- [ ] channel 满时 send 错误被忽略，不阻塞 step 执行
- [ ] `step_progress_from()` 行为不变（TextDelta 仍返回 None）
- [ ] `ExecutorCtx` / `StepExecutor` trait 不变
- [ ] 单元测试通过
- [ ] 现有测试全部通过（无回归）
