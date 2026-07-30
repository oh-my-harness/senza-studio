# Senza Studio — 设计文档

> 日期：2026-07-30
> 状态：设计草案 v5.3（workflow Studio 模式运行代码 + workflow 事件 schema + tool implementation 字段 + 停止按钮 + steering 路线图）

---

## §1 定位与使命

**Senza Studio** — 一个面向开发者的 Senza Agent 开发工作台。

开发者通过自然语言对话描述意图、从示例库起步、或直接编辑代码，快速构建基于 Senza 的 agent。Studio 生成可运行的 Python 项目脚手架，提供运行、trace、工作流可视化、迭代的闭环。Studio 是 Senza 能力的展示窗口——条件路由、预算管控等 Senza 独有能力通过对话和示例库被直接暴露给开发者。

### 目标用户

**开发者**——会写 Python、懂 agent 概念、可能不熟悉 Senza API 细节。Studio 帮他们跳过查文档、写样板代码，快速组装出可运行的 Senza agent，并在迭代中展示 Senza 的高级能力。非技术用户不是 MVP 目标。

### 三种起步方式

1. **从示例开始**：内置示例库（复用 Senza examples），选一个示例 → 复制项目文件 → 微调 → 运行。首次体验入口。
2. **从对话开始**：自然语言描述意图 → 元 agent 反问澄清 → 生成脚手架。
3. **从代码开始**：直接在代码 Tab 编辑，或导入已有 Senza 项目。

### 核心价值闭环

```
对话/模板/代码 → 生成 Python 脚手架 → 运行
  → 看 trace（时间线 + 失败高亮）→ 看工作流 DAG
  → 对话增量修改（spec diff，不覆盖手改代码）→ 重新运行
```

### 与竞品的关键差异

| 维度 | Senza Studio | Coze/Dify | LangGraph Studio | 直接抄 examples |
|---|---|---|---|---|
| 内核 | Rust runtime | 自研 | Python | Senza |
| 产出物 | 可运行 Senza Python 项目 | 平台内运行 | 可视化图 | 手动复制 |
| 差异化能力 | 条件路由 + 预算管控 | 平台功能 | 图编排 | 无 |
| 工作流可视化 | ✅ DAG 渲染 | ✅ | ✅ | ❌ |
| 不绑定平台 | ✅ 产出独立 Python 项目 | ❌ | 部分 | ✅ |

Studio 的杀手锏：**Senza 独有能力（条件路由、预算管控）通过对话和示例库直接暴露，产出物是不绑定平台的独立 Python 项目**。

### 不做的事（MVP）

- 桌面应用形态（后续，架构预留）
- 多 run 评估对比（后续）
- 项目版本管理（后续）
- 非技术用户零代码体验（后续）
- 导入已有 Senza 项目（后续，MVP 只支持从对话/示例/空白开始）
- DAG 可编辑（MVP 只读渲染 + 运行时高亮，后续支持拖拽编辑 → 生成 spec diff）
- human-in-the-loop 结构化交互（MVP 只支持纯文本 stdin 输入；后续扩展事件类型 `choice_request` / `approval_request` + stdin JSON 协议，支持按钮选择/审批/表单提交——展示 Senza `create_event_channel()` + pause/resume 能力）
- steering / 中途打断（MVP 只支持严格交替输入：等 agent settled 后才读下一行；后续利用 SDK 的 `steer()` / `follow_up()` / `next_turn()` 实现运行中打断、补充、改方向）
---

## §2 整体架构

```
┌──────────────────────────────────────────────────────┐
│  前端（React + Tailwind + shadcn/ui）                  │
│                                                       │
│  ┌─────────┐ ┌─────────┐ ┌────────┐ ┌────────────┐  │
│  │对话面板  │ │运行面板  │ │trace   │ │项目文件树   │  │
│  │(元agent)│ │(用户agent)│ │列表    │ │            │  │
│  └─────────┘ └─────────┘ └────────┘ └────────────┘  │
│                                                       │
│  前端状态机：对话中 → 已生成 → 运行中 → 看trace → 迭代  │
└──────────────────────┬───────────────────────────────┘
                       │ HTTP (REST) + WebSocket
┌──────────────────────▼───────────────────────────────┐
│  Rust 后端（axum + llm-harness-runtime）              │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │  元 agent 层（2 个独立 AgentHarness）             │ │
│  │                                                   │ │
│  │  ┌──────────┐  ┌────────────────┐               │ │
│  │  │对话 agent │  │Senza coding    │               │ │
│  │  │          │  │agent           │               │ │
│  │  └──────────┘  └────────────────┘               │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────┐  │
│  │ 项目管理     │  │ Python runner │  │ 示例库      │  │
│  │（文件系统）   │  │（subprocess）  │  │（预制项目）  │  │
│  └─────────────┘  └──────────────┘  └────────────┘  │
└──────────────┬───────┬───────────────────────────────┘
               │       │ stdin/fd3 管道（Studio 模式）
               │       │ 文件读写（trace 持久化）
┌──────────────────────▼───────────────────────────────┐
│  用户 agent（Senza Python 项目，独立进程）             │
│                                                       │
│  my-agent/                                           │
│  ├── main.py          # 入口，HarnessBuilder 或 WF    │
│  ├── tools.py         # tool 定义                     │
│  ├── workflow.py      # workflow dict（如果是 WF）     │
│  ├── pyproject.toml   # 依赖 senza-sdk                │
│  └── .studio/         # 元数据 + trace 输出            │
│      ├── spec.json    # 生成时的结构 metadata          │
│      └── runs/        # 每次运行的 trace               │
│          └── <run-id>/                                │
│              ├── events.jsonl                         │
│              └── sessions/                            │
└──────────────────────────────────────────────────────┘
```

### 三层职责

| 层 | 职责 | 技术 |
|---|---|---|
| **前端** | 对话交互、代码展示、trace 渲染、项目状态管理 | React + shadcn/ui |
| **Rust 后端** | 元 agent 运行、项目管理、Python 进程管理、示例库 | axum + runtime |
| **用户 agent** | 被定制的 agent，独立运行 | Senza Python |

- **前端 ↔ Rust 后端**：HTTP REST（CRUD 操作）+ WebSocket（agent 事件流、运行状态推送）
- **Rust 后端 ↔ 用户 agent**：
  - Studio 模式：stdin（用户输入）+ fd 3（事件输出，帧协议）+ 文件读写（trace 持久化）
  - 独立模式：用户直接在终端运行，不经过 Rust 后端
- **元 agent 之间**：松散协作，不直接通信。通过项目文件 + 前端状态传递

### 关键设计决策
1. **元 agent 在 Rust runtime 上**——直接用 `AgentHarness` + `Tool` trait，性能好，可 audit
2. **用户 agent 是独立 Python 进程**——隔离干净，用户可自由修改代码
3. **双模式运行**——用户 agent 既可在 Studio 内运行（stdin + fd 3 帧协议 + 前端复用对话组件），也可独立运行（`python main.py`，终端交互）。Studio 提供前端组件，用户不需要自己写 UI
4. **Senza coding agent 直接写代码**——不用模板引擎，LLM 根据 spec + 示例库直接写 Python 代码，覆盖 Senza 全部 API 表面。system prompt 内嵌 Senza 3 个 SKILL.md 知识
5. **先只做 Web**——axum 独立进程 + 前端静态文件。架构预留 Tauri 套壳能力（后端不绑死 UI 层）

---

## §3 数据模型

### 项目（Project）

一个项目 = 一个目录，是用户工作的基本单位。

```
~/.senza-studio/projects/<project-id>/
├── .studio/                    # Studio 管理数据
│   ├── meta.json               # 项目元数据
│   ├── conversations/          # 与元 agent 的对话历史
│   │   ├── <conv-id>.jsonl     # 每次对话一个文件
│   ├── specs/                  # 意图描述快照
│   │   ├── <spec-id>.json      # 对话 agent 输出的结构化意图
│   │   └── <spec-id>/          # 对应 spec 的生成快照
│   │       └── snapshot/       # 上次生成的文件版本（用于 diff 覆盖保护）
│   └── runs/                   # 用户 agent 运行记录
│       └── <run-id>/
│           ├── events.jsonl    # 事件流
│           ├── sessions/       # Senza session JSONL
│           ├── stdout.log
│           ├── stderr.log
│           └── exit_code
├── main.py                     # 生成的入口
├── tools.py                    # 生成的 tool 定义
├── workflow.py                 # 生成的 workflow dict（如适用）
├── server.py                   # FastAPI HTTP API（仅 deploy="api" 时生成）
├── pyproject.toml              # 依赖配置
└── .env                        # API keys（用户填写）
```

### meta.json

```json
{
  "id": "proj-abc123",
  "name": "订单分类助手",
  "created_at": "2026-07-30T...",
  "updated_at": "2026-07-30T...",
  "agent_type": "single_with_tools",
  "model": "gpt-4o",
  "status": "generated"
}
```

`agent_type` 枚举：`single` / `single_with_tools` / `linear_workflow` / `conditional_workflow`

`status` 枚举：`conversing` / `generated` / `running` / `completed` / `failed` / `iterating`

### spec.json（意图描述）

对话 agent 的结构化输出，生成 agent 的输入：

```json
{
  "spec_id": "spec-xxx",
  "project_id": "proj-abc123",
  "created_at": "...",
  "agent_type": "single_with_tools",
  "name": "订单分类助手",
  "description": "根据订单内容自动分类到预设类别",
  "model": "gpt-4o",
  "system_prompt": "你是一个订单分类助手...",
  "max_tokens": 4096,
  "budget": null,
  "tools": [
    {
      "name": "lookup_order",
      "description": "根据订单号查询订单详情",
      "parameters": { "type": "object", "properties": { "order_id": { "type": "string" } }, "required": ["order_id"] },
      "implementation": "查询订单数据库（SELECT * FROM orders WHERE id = ?）或调用内部 API GET /api/orders/{order_id}。coding agent 根据此描述生成 callback 实现。如果是 stub，填 'TODO: 实现订单查询逻辑'。"
    }
  ],
  "workflow": null,
  "deploy": "cli",
  "provider": { "type": "openai", "base_url": null }
}
```

`provider.base_url` 为 `null` 时，生成的代码从环境变量读取（`OPENAI_API_BASE` / `ANTHROPIC_API_BASE`），与 Senza examples 一致。用户在 `.env` 中配置 `OPENAI_API_KEY` + `OPENAI_API_BASE`（如 DeepSeek、Ollama、Azure 等自定义 endpoint）。spec 中的 `base_url` 仅作为覆盖值——非 null 时硬编码到代码中。
`workflow` 字段在 `agent_type` 为 `linear_workflow` 或 `conditional_workflow` 时填充。包含必需的 `judge` 策略（WorkflowEngine 构造需要 judge 参数）。

线性 workflow 示例：
```json
{
  "entry_step": "classify",
  "steps": [
    { "id": "classify", "name": "分类", "prompt": "...", "allowed_tools": [] },
    { "id": "report", "name": "报告", "prompt": "...", "allowed_tools": [] }
  ],
  "edges": [ { "from": "classify", "to": "report" } ],
  "judge": {
    "strategy": "linear",
    "transitions": {
      "classify": "to:report",
      "report": "done"
    }
  }
}
```

条件路由 workflow 示例（declarative edge conditions）：
```json
{
  "entry_step": "check",
  "steps": [
    { "id": "check", "name": "质检", "prompt": "检查质量，返回JSON含status字段", "allowed_tools": [] },
    { "id": "fix", "name": "修复", "prompt": "修复问题", "allowed_tools": [] },
    { "id": "report", "name": "报告", "prompt": "生成报告", "allowed_tools": [] }
  ],
  "edges": [
    { "from": "check", "to": "fix", "condition": { "op": "eq", "pointer": "/status", "value": "fail" } },
    { "from": "check", "to": "report", "condition": { "op": "eq", "pointer": "/status", "value": "ok" } },
    { "from": "fix", "to": "check" }
  ],
  "judge": {
    "strategy": "declarative"
  }
}
```

`judge.strategy` 枚举：
- `"linear"` — 按 edges 顺序路由，最后一步返回 `"done"`。模板生成固定 judge callback。
- `"declarative"` — 使用 declarative edge conditions（`ConditionExpr`），引擎自动启用 `EdgeConditionJudge`，无需自定义 judge callback。
- `"custom"` — 对话 agent 在 `judge.code` 字段提供 Python 代码片段。MVP 不支持。

### events.jsonl（运行 trace）

用户 agent 运行时产出的事件流，一行一个 JSON：

```jsonl
{"ts":"...","type":"text_delta","text":"这个订单属于..."}
{"ts":"...","type":"tool_call_start","tool_call_id":"call_1","tool_name":"lookup_order"}
{"ts":"...","type":"tool_call_args_delta","tool_call_id":"call_1","args_delta":"{\"order_id\":"}
{"ts":"...","type":"tool_call_end","tool_call_id":"call_1","arguments":{"order_id":"A123"}}
{"ts":"...","type":"tool_execution_start","tool_call_id":"call_1","tool_name":"lookup_order"}
{"ts":"...","type":"tool_execution_end","tool_call_id":"call_1","result":{"content":[...]}}
{"ts":"...","type":"settled"}
```

以上是 single agent 的 `AgentHarnessEvent` 序列化。注意：
- `tool_call_start` / `tool_call_end` 是 LLM 流式工具调用的生命周期（参数解析）
- `tool_execution_start` / `tool_execution_end` 是工具执行的生命周期（结果在 `tool_execution_end.result`）
- 字段名遵循 SDK 实际输出：`tool_call_id`（不是 `tool_name` + `result` 平铺），`arguments`（不是 `args`）

**Workflow 事件 schema**（linear_workflow / conditional_workflow）：

Workflow agent 使用 `WorkflowEvent`（通过 `senza.stream_run(engine)` 获取），与 single agent 的 `AgentHarnessEvent` 不同：

```jsonl
{"ts":"...","type":"step_started","step_id":"classify","step_name":"分类"}
{"ts":"...","type":"step_progress","step_id":"classify","progress":{"type":"tool_call_start","tool_use_id":"call_1","name":"lookup_order"}}
{"ts":"...","type":"step_progress","step_id":"classify","progress":{"type":"tool_execution_end","tool_use_id":"call_1","ok":true,"error":null}}
{"ts":"...","type":"step_finished","step_id":"classify","result":{"output":"订单属于退货类","structured":{"status":"fail"},"tool_calls_count":1,"session_id":"sess-xxx","cost":{"total_cost":0.002}}}
{"ts":"...","type":"step_started","step_id":"fix","step_name":"修复"}
{"ts":"...","type":"step_finished","step_id":"fix","result":{"output":"已修复问题","structured":null,"tool_calls_count":0,"session_id":"sess-yyy","cost":{"total_cost":0.001}}}
{"ts":"...","type":"paused","reason":"等待审批"}
{"ts":"...","type":"step_started","step_id":"report","step_name":"报告"}
{"ts":"...","type":"step_finished","step_id":"report","result":{"output":"报告已生成","structured":{"summary":"fixed"},"tool_calls_count":0,"session_id":"sess-zzz","cost":{"total_cost":0.001}}}
{"ts":"...","type":"failed","error":"step 'report' exceeded max retries"}
```

Workflow 事件类型：

| 事件类型 | 字段 | 说明 |
|---|---|---|
| `step_started` | `step_id`, `step_name` | step 开始执行 |
| `step_progress` | `step_id`, `progress` | step 内部进度（tool_call/tool_execution/turn_end 等），高频 |
| `step_finished` | `step_id`, `result` | step 完成，`result` 是 `StepResult`（含 `output`/`structured`/`tool_calls_count`/`cost`） |
| `paused` | `reason` | workflow 暂停（human-in-the-loop），等 `resume()` |
| `resumed` | （无额外字段） | workflow 恢复执行 |
| `cancelled` | `reason` | workflow 被取消 |
| `failed` | `error` | workflow 失败 |

`StepResult` 结构（`step_finished.result`）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `output` | string | 所有 turn 的 text_delta 拼接的完整文本 |
| `structured` | object\|null | 从 final answer 提取的结构化 JSON（条件路由的 `condition.pointer` 对此求值） |
| `tool_calls_count` | int | 本步调用的工具次数 |
| `session_id` | string | 本步的 session ID |
| `cost` | object | 本步成本（`total_cost` 等） |
| `started_at` | string\|null | 开始时间 |
| `ended_at` | string\|null | 结束时间 |

条件路由判定：`step_finished.result.structured` 中的字段值被 edge condition 的 `pointer` 求值。例如 `condition: {op: "eq", pointer: "/status", value: "fail"}` 检查 `structured.status == "fail"`。前端执行视图据此高亮被点亮的条件 edge。

Studio 模式下，这些事件同时通过 fd 3 帧协议输出（供 Rust 后端实时读取 → WebSocket 推前端）和写入 `events.jsonl` 文件（持久 trace）。独立模式下不产出此文件。Rust 后端读取后通过 WebSocket 推给前端，或前端直接请求 REST 接口拉取。

### 设计要点

- **项目自包含**：所有数据在项目目录内，可复制/移动/分享
- **`.studio/` 隐藏目录**：管理数据与用户代码分离，用户可忽略
- **trace 和代码同目录**：运行记录就在项目里，debug 时上下文完整
- **spec 是快照**：每次对话 agent 输出意图都存一份，可追溯演化历史。`meta.json` 的 `model`/`agent_type` 等字段是当前活跃值（用户可改），`spec.json` 里的同名字段是生成时的快照值——两者可能不同步，以 `meta.json` 为准。

---

## §4 元 Agent 层

2 个独立 AgentHarness（对话 agent + Senza coding agent），松散协作，前端编排。trace 渲染由前端确定性完成，无 LLM。迭代由对话 agent 的 emit_spec_diff 驱动，coding agent 执行。

### 4.1 对话 Agent（Converser）

**职责**：与用户多轮对话，理解意图，反问澄清，输出结构化 spec JSON。

**模型**：gpt-4o 或同等级模型

**System Prompt**：

```
你是 Senza Studio 的助手，帮助用户定制基于 Senza（一个 Python Agent SDK）的 AI agent。

## Senza 能力概览

Senza 是 oh-my-harness Rust runtime 的 Python SDK，支持两种 agent 模式：

### 单 Agent 模式（AgentHarness）
- 通过 HarnessBuilder 链式构建：provider → system_prompt → max_tokens → tool(s) → build()
- 支持 OpenAI 兼容 provider（create_openai_provider）和 Anthropic（create_anthropic_provider）
- 工具创建：create_tool(name, description, parameters_schema: str, callback) — parameters_schema 是 JSON Schema 的 **字符串**（`json.dumps(schema_dict)`），不是 dict
  - callback 签名：(args: dict, ctx: ToolContext) -> dict
  - 返回：{"content": [ContentBlock...], "terminate": bool}
  - 支持 async def callback
- 事件流：prompt_and_collect() 返回事件列表
  - 事件类型：text_delta, tool_call_start, tool_call_end, settled, aborted, error
- 控制：abort() 取消，phase() 查状态
- **预算管控**：builder.budget(max_cost) + create_pricing_provider() 设置定价。agent 超预算时自动停止。

### Workflow 模式（WorkflowEngine）
- workflow dict 定义：entry_step + steps + edges
- Step 类型：
  - LLM step：{id, name, prompt, allowed_tools}
  - Executor step：{id, name, executor, executor_config}
- Edge：
  - 顺序连接：{from, to}
  - **条件路由**：{from, to, condition: {op, pointer, value}} — declarative edge condition，支持 eq/ne/gt/gte/lt/lte/exists/missing。无需自定义 judge，引擎自动启用 EdgeConditionJudge。
- Judge：create_judge(callback) → 返回 "to:<step>" / "retry" / "fail:<reason>" / "done"
  - 线性流程用 `"linear"` strategy（自动按 edges 顺序路由）
  - 条件路由用 `"declarative"` strategy（edge condition 驱动，无需写 judge callback）
- 共享上下文：engine.set_context_variable(key, value)
- 事件流：subscribe() / stream_run() → step_started / step_finished / step_progress / paused / resumed / cancelled / failed。`step_finished.result` 含 `output`（文本）/ `structured`（JSON，条件路由求值用）/ `tool_calls_count` / `cost`
- **崩溃恢复**：with_task_store(dir) 持久化，WorkflowEngine.restore(dir, task_id, ...) 恢复
- **预算管控**：with_pricing(pricing_provider) 设置定价

1. 通过多轮对话理解用户想构建什么 agent
2. 每轮对话后判断信息是否足够生成脚手架
3. 信息不足时反问，按以下维度逐个澄清：

### 需要澄清的维度

| 维度 | 问题 | 选项 |
|------|------|------|
| agent 类型 | "你需要单次对话的助手，还是多步骤的流程？" | 单轮对话 / 带工具的助手 / 线性 workflow / 条件路由 workflow |
| 用途 | "这个 agent 要解决什么问题？" | 开放式 |
| 模型 | "用哪个模型？" | gpt-4o / claude / deepseek / 其他 |
| 工具 | "agent 需要调用哪些外部能力？每个工具怎么实现？" | 搜索 / 文件读写 / 数据库查询 / API 调用 / 自定义。**追问实现细节**：API endpoint、SQL 查询、文件路径等。如用户不确定，标记为 stub |
| workflow 步骤 | （如适用）"流程分几步？每步做什么？" | 逐步描述 |
| 条件路由 | （如适用）"哪些步骤有分支？基于什么条件？" | 如"质检失败就回修，成功就进下一步" |
| 预算 | "每个 agent 运行一次最多花多少钱？" | 如 $0.10 / 无限制 |
| 系统提示 | "agent 的角色和行为约束是什么？" | 开放式，可帮你起草 |
| 部署方式 | "agent 只在终端跑，还是需要一个 HTTP API？" | cli（终端）/ api（FastAPI + 极简网页） |

4. 信息充分后，调用 emit_spec 工具输出结构化意图 JSON

## spec JSON 格式

{
  "agent_type": "single" | "single_with_tools" | "linear_workflow" | "conditional_workflow",
  "name": "项目名",
  "description": "一句话描述",
  "model": "模型 ID",
  "system_prompt": "系统提示词",
  "max_tokens": 4096,
  "budget": null | { "max_cost": 0.10 },
  "tools": [
    { "name": "...", "description": "...", "parameters": {JSON Schema}, "implementation": "tool callback 的实现描述（API endpoint / SQL / 文件路径 / 逻辑说明）。如不确定，填 'TODO: stub'，coding agent 生成占位实现" }
  ],
  "workflow": null | {
    "entry_step": "...",
    "steps": [...],
    "edges": [
      { "from": "...", "to": "..." },
      { "from": "...", "to": "...", "condition": { "op": "eq", "pointer": "/status", "value": "ok" } }
    ],
    "judge": { "strategy": "linear" | "declarative", "transitions": {...} }
  },
  "deploy": "cli" | "api",
  "provider": { "type": "openai" | "anthropic", "base_url": null }
}

- 不要一次性问太多问题，每轮最多问 1-2 个
- 用户表述模糊时主动给选项，不要让用户空想
- 用户说的功能超出 MVP 能力（如 hook、MCP、executor step、崩溃恢复）时，坦诚说明并记录为未来需求。条件路由和预算管控 **在 MVP 能力范围内**，应该主动询问
- 不要生成代码，代码生成是 Senza coding agent 的工作
- 如果用户描述的是迭代已有项目，先用 read_project 读取当前代码再对话

## "信息充分"判断标准

调用 `emit_spec` 前必须满足以下最低条件（缺一不可）：

| agent_type | 必须明确的维度 |
|---|---|
| `single` | agent 类型、用途（description）、模型、system_prompt（可由你起草，用户确认） |
| `single_with_tools` | 上面 + 至少 1 个 tool（name + description + parameters） |
| `linear_workflow` | 上面 + 至少 2 个 step（id + name + prompt）+ edges 连接 + judge strategy |
| `conditional_workflow` | 上面 + 至少 1 个带 condition 的 edge + judge strategy = `"declarative"` |
兜底规则：
- 如果到第 5 轮对话仍未收集齐最低条件，总结已收集的信息，列出缺失维度，明确告知用户"还差 X 就能生成了"
- provider.type 默认 `"openai"`，只有用户明确说要 Claude 时才用 `"anthropic"`
- 如果用户描述的是迭代已有项目，先用 read_project 读取当前代码再对话
```

**工具**：
| 工具 | 说明 |
|---|---|
| `emit_spec(spec_json)` | 信息充分时调用，输出完整结构化意图 JSON，终止对话 |
| `emit_spec_diff(diff_json)` | 增量修改时调用，输出 spec diff patch（模式 2），只修改受影响字段 |
| `read_project(path)` | 读取当前项目已有文件（迭代场景下用户已有代码） |
| `read_current_spec()` | 读取当前项目的 spec.json（增量修改场景下，对话 agent 基于当前 spec 输出 diff） |

**输出**：spec.json 写入 `.studio/specs/`

**关键设计**：对话 agent 不生成代码，只输出结构化意图。代码生成是 Senza coding agent 的事。spec 是 coding agent 的 brief，不是模板的输入。

### 4.2 Senza Coding Agent

**职责**：根据 spec JSON（意图 brief）+ 项目目录（已有文件），直接写/改 Senza Python 代码。这是 Studio 内嵌的、最了解 Senza 的 coding agent——不走模板渲染，直接用 LLM 写代码。

**为什么不用模板**：模板只能产出预设结构，无法覆盖 Senza 全部能力（hooks、budget、条件路由、executor 混合、自定义 judge callback 等）。LLM 直接写代码能覆盖 Senza 的全部 API 表面，且产出更自然、更符合实际项目结构。Senza 已有 3 个 SKILL.md（senza-agent、senza-workflow、senza-advanced）教 coding agent 怎么用 Senza——coding agent 的 system prompt 内嵌这些知识。

**System Prompt 要点**：
```
你是一个 Senza 专家 coding agent，负责根据意图描述（spec JSON）写/改 Senza Python 项目代码。

## Senza API 参考

（内嵌 senza-agent SKILL.md + senza-workflow SKILL.md + senza-advanced SKILL.md 的完整内容）

## Studio 运行时接入

生成的 main.py 必须支持双模式运行（Studio 模式 + 独立模式）。Studio 模式通过环境变量 SENZA_STUDIO_RUN_ID 检测。**single agent 和 workflow agent 的交互模型完全不同**：

- 事件输出：Studio 模式下通过 fd 3 帧协议输出事件（长度前缀 + JSON），独立模式不输出
- 用户输入：Studio 模式下从 stdin 读取，独立模式用 input()
- trace 文件：SENZA_STUDIO_TRACE_DIR 存在时写 events.jsonl
- **single agent**（AgentHarness）：多轮对话模型。Studio 模式用 `senza.stream_prompt(harness, text)` async generator，独立模式用双线程 `events()`+`prompt()`。`prompt()` 自动追加到 session，保持多轮上下文
- **workflow agent**（WorkflowEngine）：一次性任务提交模型。Studio 模式用 `senza.stream_run(engine)` async generator（启动 `engine.run()` 并 yield workflow 事件），独立模式用双线程 `subscribe()`+`run()`。用户输入通过 `engine.set_context_variable()` 注入。pause 时从 stdin 读取后 `engine.resume()`

## 你的工具

- write_file(path, content) — 写项目文件
- read_file(path) — 读项目文件
- read_spec() — 读当前 spec JSON
- list_project_files() — 列出项目文件
- ast_check(path) — 用 python -c "import ast; ast.parse(open(path).read())" 验证语法

## 行为约束

- 拿到 spec 后，先 read_spec() 理解意图，再决定文件结构
- 每个 write_file 后调用 ast_check 验证语法
- Studio 运行时接入代码（_emit / _get_input / _run_studio / _run_standalone / _run_studio_workflow / _run_standalone_workflow）是固定的——参考 §4.2 标准运行时接入代码。**必须根据 agent_type 选择正确的运行函数**
- 如果 spec.deploy == "api"，额外生成 server.py（FastAPI + 极简 chat 网页），把 agent 包成 HTTP API。server.py 复用 main.py 中的 harness 构建逻辑，不重复定义
- 如果是增量修改（spec diff），只在规则引擎指定的受影响文件内修改，不碰其他文件
```

**工具**：
| 工具 | 说明 |
|---|---|
| `write_file(path, content)` | 写项目文件 |
| `read_file(path)` | 读项目文件 |
| `read_spec()` | 读当前 spec JSON |
| `list_project_files()` | 列出项目文件 |
| `ast_check(path)` | 验证 Python 语法合法性 |

**示例库**：预制 Senza 项目（从 examples 转化），不是 tera 模板。coding agent 可 `read_file` 参考示例的风格和结构。示例库存放在 Studio 安装目录下：
```
examples/
├── basic_chat/               # 基础对话（01_basic_prompt）
├── tool_calling/             # 带工具（02_tool_calling）
├── streaming/                # 流式输出（03_streaming）
├── budget_controlled/        # 预算管控（08_budget_pricing）
├── linear_pipeline/          # 线性流水线（01_linear_workflow）
├── conditional_routing/      # 条件路由（02_conditional_routing）
├── crash_recovery/           # 崩溃恢复（04_crash_recovery）
└── human_in_loop/            # 人工介入（06_human_in_the_loop）
```

**标准运行时接入代码**：coding agent 生成的 main.py 需要包含 Studio 双模式接入。single agent 和 workflow agent 的交互模型完全不同，有各自的标准实现。

**共用接入代码**（两种 agent 类型都需要）：

```python
import os
import sys
import json
import asyncio
import senza

# Studio 双模式接入
_run_id = os.environ.get("SENZA_STUDIO_RUN_ID")
_trace_dir = os.environ.get("SENZA_STUDIO_TRACE_DIR")
_studio_mode = _run_id is not None

if _trace_dir:
    os.makedirs(_trace_dir, exist_ok=True)
    _events_file = os.path.join(_trace_dir, "events.jsonl")
else:
    _events_file = None

_event_fd = None
if _studio_mode:
    try:
        _event_fd = os.fdopen(3, "w")
    except OSError:
        _event_fd = None

def _emit(event):
    """输出事件。Studio 模式：写 trace 文件 + fd 3 帧协议。独立模式：仅写 trace 文件（如有）。"""
    if _events_file:
        with open(_events_file, "a") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    if _event_fd:
        line = json.dumps(event, ensure_ascii=False, default=str)
        _event_fd.write(f"{len(line)}\n{line}\n")
        _event_fd.flush()

def _get_input(prompt="> "):
    """Studio 模式：发 input_request 事件，从 stdin 读取。独立模式：input()。"""
    if _studio_mode:
        _emit({"type": "input_request", "prompt": prompt})
        return sys.stdin.readline().rstrip("\n")
    else:
        return input(prompt)
```

**Single agent 模式**（single / single_with_tools）：

AgentHarness 的交互模型是多轮对话：while True 循环 → `stream_prompt(harness, user_input)` → 等 settled → 下一轮。`prompt()` 往 session 追加消息，自动保持多轮上下文。SDK 的 `auto_compact` 机制处理长对话的 token 压缩。

```python
def _run_studio(harness):
    """Studio 模式：用 stream_prompt() async generator 实现真流式。"""
    async def _loop():
        while True:
            user_input = _get_input("> ")
            if not user_input:
                break
            _settled = False
            async for event in senza.stream_prompt(harness, user_input, timeout_ms=30000):
                _emit(event)
                if event.get("type") in ("settled", "aborted", "error"):
                    _settled = True
            if not _settled:
                _emit({"type": "error", "message": "stream ended without terminal event"})
    asyncio.run(_loop())

def _run_standalone(harness):
    """独立模式：用双线程 stream 模式（参考 03_streaming.py）。"""
    import threading
    while True:
        try:
            user_input = input("> ")
        except EOFError:
            break
        if not user_input:
            break
        done = threading.Event()
        def stream_events():
            for event in harness.events(timeout_ms=30000):
                t = event["type"]
                if t == "text_delta":
                    print(event.get("text", ""), end="", flush=True)
                elif t in ("settled", "aborted", "error"):
                    done.set()
                    break
        t = threading.Thread(target=stream_events)
        t.start()
        harness.prompt(user_input)
        t.join(timeout=30)
        print()
```

**Workflow agent 模式**（linear_workflow / conditional_workflow）：

WorkflowEngine 的交互模型与 AgentHarness 完全不同——不是多轮对话，而是一次性任务提交：
- 用户提交一个任务（通过 `set_context_variable` 注入）
- `engine.run()` 阻塞执行整个 workflow
- 事件通过 `senza.stream_run(engine)` 获取（`step_started` / `step_finished` / `step_progress` / `paused` / `cancelled` / `failed`）
- 如果 workflow pause（human-in-the-loop），从 stdin 读取输入后 `engine.resume()`

```python
def _run_studio_workflow(engine):
    """Studio 模式：用 stream_run() 获取 workflow 事件。"""
    async def _run():
        # 1. 从 stdin 读初始任务输入
        task_input = _get_input("提交任务: ")
        if not task_input:
            return
        # 2. 注入到 workflow context
        engine.set_context_variable("user_input", task_input)
        # 3. stream_run 启动 engine.run() 并 yield 事件
        async for event in senza.stream_run(engine, timeout_ms=60000):
            _emit(event)
            # workflow pause → 等待用户输入 → resume
            if event.get("type") == "paused":
                _resume_input = _get_input(f"[paused] {event.get('reason', '')}: ")
                if _resume_input:
                    engine.set_context_variable("resume_input", _resume_input)
                    engine.resume()
            # 终端事件
            if event.get("type") in ("failed", "cancelled"):
                break
    asyncio.run(_run())

def _run_standalone_workflow(engine):
    """独立模式：engine.run() 阻塞，subscribe() 在另一线程消费事件。"""
    import threading
    task_input = input("提交任务: ")
    if not task_input:
        return
    engine.set_context_variable("user_input", task_input)
    done = threading.Event()
    def stream_events():
        for event in engine.subscribe(timeout_ms=60000):
            t = event.get("type", "")
            if t == "step_started":
                print(f"\n[step] {event.get('step_name', event.get('step_id', '?'))}")
            elif t == "step_finished":
                result = event.get("result", {})
                output = result.get("output", "")
                if output:
                    print(f"  → {output.strip()[:200]}")
            elif t == "paused":
                print(f"\n[paused] {event.get('reason', '')}")
            elif t in ("failed", "cancelled"):
                done.set()
                break
    t = threading.Thread(target=stream_events)
    t.start()
    engine.run()
    t.join(timeout=120)
    print(f"\nFinal state: {engine.state()}")
```

**入口选择**：

```python
if __name__ == "__main__":
    # harness/engine 构建由 coding agent 根据 spec 写
    if _studio_mode:
        if _is_workflow:
            _run_studio_workflow(engine)
        else:
            _run_studio(harness)
    else:
        if _is_workflow:
            _run_standalone_workflow(engine)
        else:
            _run_standalone(harness)
```

### 4.3 Trace 渲染（前端确定性，无 LLM）

**职责**：前端渲染 trace 时间线 + 失败高亮。不使用 LLM agent——trace 数据是结构化的（events.jsonl），前端确定性渲染更可靠、更可控、无延迟。

**实现**：前端 Trace Tab 读取 events.jsonl，按事件类型渲染：
- 时间线：step_started → text_delta → tool_call_start → tool_execution_end → step_finished
- 失败高亮：`type: "error"` 或 `tool_execution_end.result.isError: true` 的事件红色标记
- step 展开：点击 step 看 output / structured / tool calls
- 无需 LLM 诊断——开发者看 trace 本身就能发现问题

### 4.4 迭代模式

迭代不是独立 agent——由对话 agent + coding agent 协作完成。

**三种迭代模式**：
1. **重新对话（全量重生成）**：用户反馈 → 对话 agent 重新理解意图 → 新 spec → coding agent 重新生成所有文件。适合大改。**覆盖前提示确认**，diff 当前文件与上次生成的 snapshot，识别用户手改的部分。
2. **增量 spec 修改**：用户说"加一个搜索工具"或"改 system prompt" → 对话 agent 调用 `read_current_spec()` 读取当前 spec → 输出 `emit_spec_diff(diff_json)` → **规则引擎根据 spec diff 字段映射到受影响文件**（见下表）→ coding agent 只在指定文件内修改。适合小改，不覆盖未受影响的文件。
3. **代码级修改**：开发者直接在代码 Tab 编辑代码，不经过 spec。spec 标记为"已偏离"。适合精细调整。

**MVP 做模式 1 + 2 + 3**。

**模式 2 的 diff 格式**（JSON Patch 风格）：
```json
{
  "ops": [
    { "op": "add", "path": "/tools/0", "value": { "name": "search", "description": "...", "parameters": {...} } },
    { "op": "replace", "path": "/system_prompt", "value": "新的 system prompt" }
  ]
}
```

**模式 2 的受影响文件判定（规则引擎，非 LLM）**：

spec diff 的哪些字段影响哪些文件是确定性的——由规则引擎判定，不由 coding agent 判断。coding agent 只在规则引擎指定的文件内修改，不能碰其他文件。

| spec diff 路径 | 受影响文件 | 说明 |
|---|---|---|
| `/system_prompt` | `main.py` (+ `server.py` if exists) | system prompt 在 builder 链中 |
| `/model` | `main.py` (+ `server.py` if exists) | model 在 builder 链中 |
| `/max_tokens` | `main.py` (+ `server.py` if exists) | max_tokens 在 builder 链中 |
| `/budget` | `main.py` (+ `server.py` if exists) | budget 在 builder 链中 |
| `/tools/*` | `tools.py` + `main.py` (+ `server.py` if exists) | tools 定义在 tools.py，注册在 main.py |
| `/provider` | `main.py` (+ `server.py` if exists) | provider 构建在 main.py |
| `/workflow/steps/*` | `workflow.py` + `main.py` (+ `server.py` if exists) | step 定义在 workflow.py，引用可能在 main.py |
| `/workflow/edges/*` | `workflow.py` | edge 定义在 workflow.py |
| `/workflow/judge` | `main.py` (+ `server.py` if exists) | judge 构建在 main.py |
| `/deploy` | `main.py` + create/delete `server.py` | deploy 变更：cli→api 生成 server.py，api→cli 删除 server.py |

规则引擎工作流：
1. 对当前 spec 应用 diff，生成新 spec
2. 遍历 diff ops 的 path，查上表得到受影响文件集合
3. coding agent 收到：新 spec + 受影响文件列表 + 各文件当前内容
4. coding agent 只 `write_file` 受影响文件，每次 `write_file` 后 `ast_check` 验证语法
5. 未在受影响列表中的文件，coding agent 不能写

这样把确定性的部分（哪些文件受影响）留给规则，把创造性的部分（文件内具体怎么改）留给 LLM。

**模式 1 的覆盖保护机制**：
- 重新生成前，diff 当前文件与 `.studio/specs/<spec-id>/snapshot/` 中的版本
- 识别用户手改的部分，提示"检测到你在 main.py 和 tools.py 中有修改，重新生成将覆盖这些文件。是否继续？"
- 用户确认后覆盖。spec 历史保留在 `.studio/specs/` 中可追溯
- 模式 3 是开发者的主要迭代路径——直接改代码 + 运行 + trace，不走 spec 循环

### Agent 间数据流

```
用户 ←→ 对话 agent
              │ emit_spec / emit_spec_diff
         spec.json ──→ Senza coding agent ──→ Python 文件
                                          │
                          用户运行 ←──────┘
                              │
                         events.jsonl
                              │
                    前端 Trace Tab（确定性渲染）
                              │
用户 ←→ 对话 agent（增量修改 / 全量重生成 / 代码级修改）
```

---

## §5 前端架构

### 技术栈

React + Tailwind + shadcn/ui，Vite 构建。与 LLM Space 的 UI 技术栈一致，可参考其组件模式。

### 页面结构

```
┌─────────────────────────────────────────────────────────┐
│ 顶栏：项目名 | 模型选择 | 运行按钮 | 模板库 | 设置      │
├──────────┬──────────────────────────┬───────────────────┤
│          │                          │                   │
│ 项目     │  主面板（标签页切换）      │  右侧面板          │
│ 文件树   │                          │  （上下文感知）    │
│          │  ┌───┬───┬───┬───┬───┐  │                   │
│ ▸ main.py│  │对话│运行│代码│DAG│trace│ │  对话中:          │
│ ▸ tools  │  │   │   │   │   │   │  │  当前 spec        │
│ ▸ workflow│  ├───┼───┼───┼───┼───┤  │  预览             │
│ ▸ .studio│  │   │   │   │   │   │  │                   │
│          │  │   │   │   │   │   │  │  运行中:          │
│          │  │   │   │   │   │   │  │  实时事件流        │
│          │  └───┴───┴───┴───┴───┘  │                   │
│          │                          │  trace 模式:      │
│          │                          │  时间线 + 失败高亮 │
├──────────┴──────────────────────────┴───────────────────┤
│ 底栏：状态 | token 用量 | 运行 ID                         │
└─────────────────────────────────────────────────────────┘
```

### 五个主标签页

**对话 Tab**（与元 agent 对话）：
- 消息列表（用户 / assistant）
- streaming 输出（元 agent 的回复逐字显示）
- assistant 消息中内嵌 spec 预览（当对话 agent 调用 emit_spec / emit_spec_diff 时）
- 底部输入框

**运行 Tab**（与用户 agent 交互，Studio 模式）：

运行 Tab 按 agent 类型分化为两种视图：

**聊天视图**（single / single_with_tools agent）：
- 消息列表（用户 / 用户 agent 的 assistant）
- streaming 输出（text_delta 实时显示）
- tool call 展开（tool_call_start → tool_execution_end），tool 结果如果是 JSON/表格则结构化展示
- 底部输入框 → WebSocket 发送 → subprocess stdin
- agent 等待输入时显示输入提示
- **"停止"按钮**：运行中显示，点击后 Rust 后端 kill subprocess（SIGTERM → SIGKILL），agent 的 `abort()` 由 subprocess 退出触发
- "独立运行"按钮 → 在终端 `python main.py` 跑（不走 Studio）

**执行视图**（linear_workflow / conditional_workflow agent）：

对 workflow agent，运行不是"你说一句我说一句"——用户提交一个任务，然后看它经过各步骤执行，条件路由决定走哪条路。执行视图把 DAG、step 产出、条件判定融合在一个界面：

```
│ 输入区：[提交任务____________] [Run] [停止] │
├─────────────────────────────────────┤
│                                     │
│  ● classify ──→ ○ fix ──→ ○ report │  ← DAG 内联，实时高亮
│  ✅ done        ⏳ running     ⬜    │
│  产出：{status:"fail"}              │  ← 条件判定结果 + step 产出
│                                     │
├─────────────────────────────────────┤
│ 当前 step 输出：                    │
│ > 正在修复问题...                   │  ← 当前 step 的 text_delta
│                                     │
└─────────────────────────────────────┘
```

- 顶部输入区：提交任务（不是聊天框，是"提交任务 → 等待执行完成"模式）
- 中部 DAG 内联：step 节点实时高亮（pending → running → done/failed/skipped），条件 edge 被点亮并显示判定结果
- 每个 step 节点下方展开结构化产出（step_finished 事件的 structured 数据）
- 底部当前 step 输出区：正在执行的 step 的 text_delta 实时流式显示
- 不复用聊天面板组件——执行视图是独立组件
- fd 3 事件流的 `step_started` / `step_finished` 事件驱动 DAG 高亮和产出展示
- "独立运行"按钮同上
- **"停止"按钮**：同聊天视图，kill subprocess

**DAG Tab**（工作流可视化，workflow 项目可见）：
- 只读 DAG 全屏视图（运行 Tab 的执行视图是内联 DAG，此 Tab 是全屏查看/审视用）
- nodes = steps，edges = workflow edges
- 条件路由 edge 显示 condition 标注（如 `eq /status ok`）
- 运行后标注每个 step 的状态（成功/失败/跳过）
- 使用 React Flow 或 @xyflow/react 渲染
- 非 workflow 项目（single/single_with_tools）此 Tab 隐藏

**Trace Tab**（确定性渲染，无 LLM）：
- 运行列表（左侧或顶部下拉选择 run-id）
- 事件时间线：step_started → text_delta → tool_call_start → tool_execution_end → step_finished
- 每个 step 可展开看完整 output / structured / tool calls
- 失败事件红色高亮（`type: "error"` 或 `tool_execution_end.result.isError`）
- 无"分析"按钮——开发者直接看 trace 定位问题

### 示例库入口

顶栏"示例库"按钮打开示例选择面板：
- 网格展示内置示例项目（从 Senza examples 转化，存放在 studio-core `examples/` 目录）
- 每个示例：名称 + 描述 + 能力标签（如"条件路由""预算管控""崩溃恢复"）
- 选择示例 → **复制示例项目文件到新项目目录** → 用户可直接运行或微调
- 示例是 Senza 能力的展示窗口——让开发者在 30 秒内看到 Studio 能做什么
- "从示例开始"不走 spec → coding agent 链路——直接复制文件，用户在代码 Tab 看到完整可运行项目。如需修改，走模式 2（增量 spec）或模式 3（直接编辑）

### 右侧面板（上下文感知）

根据当前状态自动切换内容：
- **对话中**：展示当前对话 agent 正在构建的 spec 预览（如果调用了 emit_spec / emit_spec_diff）
- **已生成**：展示项目结构概要 + "运行"按钮
- **运行中**：实时事件流（WebSocket 推送）+ 运行状态
- **trace 模式**：时间线摘要 + 失败计数

### 前端状态管理

每个打开的项目一个 Zustand store（参考 LLM Space 的 per-thread store 模式）：

```typescript
interface ProjectStore {
  // 项目元数据
  project: ProjectMeta;

  // 对话
  conversation: Message[];
  conversationStatus: 'idle' | 'streaming' | 'emitting_spec';
  currentSpec: Spec | null;

  // 代码
  files: Record<string, string>;  // path → content
  dirtyFiles: Set<string>;

  // 运行（Studio 模式 — 与用户 agent 交互）
  runs: RunSummary[];
  activeRunId: string | null;
  runStatus: 'idle' | 'running' | 'completed' | 'failed' | 'waiting_input';
  runView: 'chat' | 'execution';     // 根据 agent_type 自动选择：single→chat, workflow→execution
  runMessages: Message[];           // 聊天视图的消息列表（single agent 用）
  liveEvents: Event[];              // 实时事件流（trace + 执行视图共用）
  stepStates: Record<string, StepState>;  // 执行视图：step_id → {status, output, structured}
  activeStepId: string | null;      // 执行视图：当前高亮的 step

  // DAG（工作流可视化，全屏 Tab 用）
  workflowGraph: { nodes: WorkflowNode[]; edges: WorkflowEdge[] } | null;

  // Actions
  sendMessage(text: string): void;
  sendRunMessage(text: string): void;   // 聊天视图：向 single agent 发送消息
  submitTask(text: string): void;       // 执行视图：向 workflow 提交任务（不是对话）
  runProject(mode: 'studio' | 'standalone'): void;
  applySpecDiff(diff: SpecDiff): void;  // 模式 2：增量修改
  regenerateFromSpec(): void;           // 模式 1：全量重生成
  loadExample(exampleId: string): void;    // 从示例库创建项目（复制示例文件）

### API 设计（前端 ↔ Rust 后端）

**REST**：
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/projects` | 创建项目 |
| GET | `/api/projects/:id` | 获取项目元数据 |
| GET | `/api/projects/:id/files` | 获取文件列表 |
| GET | `/api/projects/:id/files/:path` | 获取文件内容 |
| PUT | `/api/projects/:id/files/:path` | 保存文件 |
| POST | `/api/projects/:id/converse` | 发送对话消息（触发对话 agent） |
| POST | `/api/projects/:id/generate` | 从 spec 生成代码（全量，模式 1） |
| POST | `/api/projects/:id/generate-diff` | 从 spec diff 增量生成代码（模式 2） |
| POST | `/api/projects/:id/run` | 运行用户 agent |
| GET | `/api/projects/:id/runs` | 运行列表 |
| GET | `/api/projects/:id/runs/:runId/events` | 获取事件流 |
| GET | `/api/projects/:id/workflow-graph` | 获取工作流 DAG（从 spec 解析） |
| GET | `/api/templates` | 列出模板库 |
| POST | `/api/projects/from-template` | 从模板创建项目 |

**WebSocket**：
| 通道 | 方向 | 说明 |
|---|---|---|
| `/ws/converse/:projectId` | 双向 | 对话 agent streaming 事件 |
| `/ws/run/:projectId` | 双向 | 用户 agent 运行：后端推送事件流，前端发送用户输入 |

### 前端到后端的通信模式

对话 agent 的 streaming：前端 POST `/converse` 后，后端启动元 agent，通过 WebSocket `/ws/converse/:projectId` 推送 `text_delta` 等事件。对话结束后，spec JSON 通过 REST 或 WebSocket 最终消息返回。

用户 agent 运行（Studio 模式）：前端 POST `/run`，后端 spawn Python subprocess（stdin/stdout/stderr piped + fd 3 pipe 作为事件通道），通过 WebSocket `/ws/run/:projectId` 双向通信——后端从 fd 3 读取帧协议事件推给前端，前端通过同一 WebSocket 发送用户输入消息，后端写入 subprocess stdin。stdout/stderr 各自捕获到日志文件，不参与事件协议。运行结束后 events.jsonl 完整可通过 REST 获取。独立模式运行不经过 WebSocket，直接 `python main.py`。

---

## §6 Rust 后端架构

### Crate 结构

新建独立仓库 `oh-my-harness/senza-studio`，git 依赖 `llm-harness-runtime` crate。

```
senza-studio/
├── Cargo.toml                 # workspace
├── crates/
│   ├── studio-core/           # 核心业务逻辑（无 web 依赖）
│   │   ├── src/
│   │   │   ├── lib.rs
│   │   │   ├── project.rs     # 项目管理（文件系统 CRUD）
│   │   │   ├── spec.rs        # Spec 数据结构 + 校验
│   │   │   ├── agents/        # 2 个元 agent（对话 + coding agent）
│   │   │   │   ├── mod.rs
│   │   │   │   ├── converser.rs      # 对话 agent
│   │   │   │   └── coding_agent.rs   # Senza coding agent（替代 generator + templates）
│   │   │   └── examples/      # 预制 Senza 项目示例库（从 Senza examples 转化）
│   │   │       ├── basic_chat/
│   │   │       ├── tool_calling/
│   │   │       ├── streaming/
│   │   │       ├── budget_controlled/
│   │   │       ├── linear_pipeline/
│   │   │       ├── conditional_routing/
│   │   │       ├── crash_recovery/
│   │   │       └── human_in_loop/
│   │   └── Cargo.toml
│   └── studio-server/         # axum web 层
│       ├── src/
│       │   ├── lib.rs
│       │   ├── routes/        # REST 路由
│       │   │   ├── projects.rs
│       │   │   ├── converse.rs
│       │   │   ├── generate.rs       # 触发 coding agent
│       │   │   ├── generate_diff.rs  # 增量修改
│       │   │   ├── run.rs
│       │   │   └── templates.rs      # 示例库
│       │   ├── ws/            # WebSocket 处理
│       │   │   ├── converse.rs
│       │   │   └── run.rs
│       │   └── state.rs       # AppState（studio-core 引用 + 连接池）
│       └── Cargo.toml
├── frontend/                  # React 前端（独立 npm 包）
│   ├── package.json
│   ├── vite.config.ts
│   └── src/
├── static/                    # 前端构建产物（studio-server 嵌入）
└── README.md
```

### 依赖关系

```
studio-server → studio-core → llm-harness-runtime
                              → llm-harness-agent
                              → llm-harness-types
                              → axum (web 框架)
                              → tokio (异步运行时)
```

### studio-core 核心模块

**ProjectManager**：
- `create_project(name) -> Project` — 建项目目录
- `open_project(id) -> Project` — 加载已有项目
- `list_projects() -> Vec<ProjectSummary>` — 列出所有项目
- `read_file(project_id, path) -> String` — 读项目文件
- `write_file(project_id, path, content) -> ()` — 写项目文件

**Spec**：
- 数据结构定义（对应 §3 的 spec.json）
- `validate(spec) -> Result<()>` — 校验完整性
- `from_conversation_json(json) -> Spec` — 从对话 agent 输出解析

**CodingAgent**：
- `generate(spec, project_path) -> Result<GeneratedFiles>` — 启动 Senza coding agent，给它 spec + 项目目录 + 示例库，让它写代码
- 内部构建 AgentHarness（coding agent），配备 write_file / read_file / read_spec / list_project_files / ast_check 工具
- agent 的 system prompt 内嵌 Senza SKILL.md 知识 + Studio 运行时接入说明
- 生成完成后，spec snapshot 写入 `.studio/specs/<spec-id>/snapshot/`

**Runner**：
- `run(project_id) -> RunId` — 启动 Python subprocess（Studio 模式）
  - stdin/stdout/stderr 各自 piped
  - 额外打开一个 pipe 作为 fd 3 传给子进程（事件通道）
  - 设置环境变量 `SENZA_STUDIO_RUN_ID=<run-id>` 和 `SENZA_STUDIO_TRACE_DIR=.studio/runs/<run-id>/`
- `run_standalone(project_id) -> RunId` — 启动 Python subprocess（独立模式，继承终端 stdio，不传 fd 3）
- `send_input(run_id, text) -> ()` — 向 subprocess stdin 写入用户消息（Studio 模式）
- `read_events(run_id) -> Vec<Event>` — 读 events.jsonl（持久 trace，两种模式都可用——独立模式不写文件，Studio 模式有文件）
- `read_session(run_id, session_id) -> Vec<SessionEntry>` — 读 session JSONL（复用 `session-viewer` crate 的逻辑）
- `is_running(run_id) -> bool` — 检查进程状态
- Studio 模式下：fd 3 的 pipe 由 `studio-server` 的 WebSocket 处理器实时读取（帧协议：长度前缀 + JSON），推给前端。stdout/stderr 各自独立捕获写入 `stdout.log` / `stderr.log`，不参与事件协议。

**运行时协议演进路径**：MVP 用 fd 3 帧协议（已隔离 `print()` 污染）。后续迁移到 SDK 回调——让 Senza SDK 原生支持 `studio_callback`（事件流通过回调输出而非 fd），彻底解决用户改代码后用 `input()` 替代 `_get_input()` 绕过协议的问题。这需要修改 Senza SDK（在 `AgentHarness` / `WorkflowEngine` 增加 event callback 注入点），是 P1 优先级。

**元 Agent 构建器**：
每个元 agent 是一个 `AgentHarness`，在 studio-core 中用 `HarnessBuilder` 构建。

**Provider 构建方式**：Rust 侧通过 `llm_adapter` crate（`llm_harness_loop` re-export）构建 provider：
```rust
use llm_harness_loop::{OpenAIProvider, AnthropicProvider, LlmClient};
use std::sync::Arc;

let client: Arc<dyn LlmClient> = Arc::new(
    OpenAIProvider::builder(&api_key)
        .base_url(&base_url)  // 可选
        .build()
);
// 或 AnthropicProvider::builder(&api_key).build()
```
配置从环境变量读取：`STUDIO_API_KEY`、`STUDIO_MODEL`、`STUDIO_BASE_URL`（可选）。

**工具实现**：每个元 agent 工具需实现 `Tool` trait（`llm-harness-types`）。实际签名：
```rust
pub trait Tool: Send + Sync {
    fn name(&self) -> &str;
    fn description(&self) -> &str;
    fn parameters_schema(&self) -> &serde_json::Value;  // 注意：返回 &Value，不是字符串
    fn execute<'a>(&'a self, args: serde_json::Value, ctx: &'a ToolContext)
        -> BoxFuture<'a, Result<ToolResult, ToolFailure>>;  // 返回 BoxFuture，不是 async fn
}
```
相比 Python 的 `create_tool(name, desc, schema_str, callback)`，Rust 侧每个工具是一个 struct + impl `Tool`，量更大但类型安全。可定义一个 `StudioTool` helper struct 简化样板代码（接受 name + description + `serde_json::Value` schema + async closure，内部 `Box::pin` 包装）。

**工程量评估**：2 个元 agent（对话 agent 4 个工具 + coding agent 5 个工具 = 9 个工具）= 约 12 个 struct + impl。这是可接受的一次性成本，后续扩展工具时增量小。

### 用户 agent 的运行模式与 trace 接入

生成的 Python 代码支持两种运行模式，通过环境变量 `SENZA_STUDIO_RUN_ID` 检测：

**独立模式**（`python main.py`，无 Studio 环境）：
- 终端交互：`input()` 读取用户输入，`print()` 输出文本
- trace 文件写入：如果设置了 `SENZA_STUDIO_TRACE_DIR` 环境变量（用户手动设置），则写入 events.jsonl；否则不写。用户可 `SENZA_STUDIO_TRACE_DIR=.trace python main.py` 启用，或直接在 Studio 内用 Studio 模式运行。

**Studio 模式**（从 Studio 内启动，环境变量存在）：
- 事件流实时输出：用 `senza.stream_prompt(harness, user_input)` async generator 实现真流式，每个事件通过 **专用文件描述符** 输出（fd 3），与 stdout 彻底分离
- Rust 后端读 subprocess fd 3 → 解析帧 → WebSocket 推前端 → 前端实时渲染对话 + tool call
- 用户输入通过 stdin 管道：前端发送消息 → Rust 后端写入 subprocess stdin → agent 读到
- 同时写入 `.studio/runs/<run-id>/events.jsonl` 作为持久 trace（独立模式不写）
- stdout 和 stderr 不参与事件协议——用户代码中的 `print()` 和 Python traceback 正常走 stdout/stderr，Rust 后端分别捕获写入 `stdout.log` / `stderr.log`，不干扰事件流

**为什么不用 stdout 帧协议**：tool callback 在 SDK 的事件处理线程中执行，如果用户在 callback 里 `print()`（非常常见），会与事件帧输出交错到同一个 stdout，导致 Rust 后端的帧解析器错位且无法恢复。用专用 fd 彻底隔离事件流和用户输出。

**fd 3 事件协议**（Studio 模式）：Studio 模式下，生成的代码打开 fd 3 作为事件输出通道。使用长度前缀帧：
```
<length>\n<json>\n
```
fd 3 不存在时（独立模式），`_emit` 仅写 trace 文件（如果有 `SENZA_STUDIO_TRACE_DIR`），不输出到任何 fd。

模板中的 `_emit` 实现（Studio 模式部分）：
```python
_event_fd = None
if _studio_mode:
    try:
        _event_fd = os.fdopen(3, "w")
    except OSError:
        _event_fd = None  # fd 3 不可用，降级为仅写文件

def _emit(event):
    if _events_file:
        with open(_events_file, "a") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    if _event_fd:
        line = json.dumps(event, ensure_ascii=False, default=str)
        _event_fd.write(f"{len(line)}\n{line}\n")
        _event_fd.flush()
```

Rust 后端启动 subprocess 时，通过 `Stdio::piped()` 配置 stdin/stdout/stderr，并额外打开一个 pipe 作为 fd 3 传给子进程。事件流从 fd 3 的 pipe 读取，stdout/stderr 各自独立捕获。

事件类型遵循 SDK 实际输出（见 §3 events.jsonl），包括：
- `{"type":"input_request","prompt":"> "}`       — agent 等待输入
- `{"type":"text_delta","text":"..."}`            — 文本流式输出
- `{"type":"tool_call_start",...}`               — LLM 工具调用开始
- `{"type":"tool_execution_end",...}`            — 工具执行完成
- `{"type":"settled"}`                            — 本轮结束，等待下一轮输入
- `{"type":"error","message":"..."}`              — 错误

**stdin 协议**（Studio 模式）：Rust 后端写入一行用户消息（无帧协议，纯文本行），agent 的 `sys.stdin.readline()` 读到。

**stderr 处理**：subprocess 的 stderr 独立捕获，不参与帧协议。Python traceback 等多行错误写入 `.studio/runs/<run-id>/stderr.log`，前端在 trace Tab 可查看。

这样 Studio 前端直接复用对话面板组件渲染用户 agent 的交互——用户不需要自己写 UI。

### 静态文件服务

studio-server 启动时：
- 开发模式：前端 Vite dev server 独立运行（端口 5173），Rust 后端跑在 3000，前端配置 proxy
- 生产模式：`frontend/` 构建产物复制到 `static/`，axum 直接 serve 静态文件

---

## §7 错误处理与边界情况

### 元 Agent 层

| 场景 | 处理 |
|---|---|
| 对话 agent LLM 调用失败 | WebSocket 推送 error 事件，前端显示"对话出错，请重试"，对话历史保留 |
| 对话 agent 输出的 spec JSON 格式错误 | Spec::from_conversation_json 解析失败 → 返回错误给对话 agent，让它重新输出（runtime 的 retry 机制） |
| coding agent 生成失败 / ast_check 失败 | 返回错误给前端，显示哪个文件出错 + ast 错误信息。coding agent 内部 retry（最多 2 次），仍失败则提示用户切换模式 3 手动编辑 |
| trace 无数据可读 | 前端 trace Tab 提示"请先运行项目" |

### 用户 Agent 运行

| 场景 | 处理 |
|---|---|
| Python 未安装 / senza-sdk 未安装 | subprocess 启动失败，stderr 捕获，前端显示"请先安装 Python 和 senza-sdk" |
| 用户 agent 运行时崩溃 | subprocess 退出码非 0，读 stderr.log，events.jsonl 保留已写入的部分 |
| 用户 agent 超时 | Runner 设置超时（默认 120s），超时后 kill 进程，标记 run 为 timeout |
| 用户修改了代码导致语法错误 | Python 启动即失败，stderr 返回 SyntaxError，前端在 trace Tab 高亮显示 |
| API key 未配置 | 生成的 .env 模板里有占位符，用户未填则运行报错，前端提示检查 .env |

### 项目管理

| 场景 | 处理 |
|---|---|
| 项目目录被外部删除 | 打开项目时检测目录不存在，前端提示"项目丢失" |
| 并发编辑同一项目 | MVP 不处理跨实例并发。但处理单实例内的并发场景：对话 agent streaming 时用户切到代码 Tab 改代码——允许，代码保存独立于对话；运行中的用户 agent 未结束时再次点"运行"——前端禁用运行按钮，显示"正在运行中"；多个项目同时打开——每个项目独立的 Zustand store + 独立的元 agent 实例，后端按 project_id 隔离状态 |
| 磁盘空间不足 | 文件写入失败返回错误 |

### 迭代循环

| 场景 | 处理 |
|---|---|
| 用户手改代码后增量修改 spec（模式 2） | 规则引擎判定受影响文件 → coding agent 只改指定文件，未在列表中的文件不动 |
| 用户手改代码后全量重生成（模式 1） | 覆盖前提示"将覆盖当前代码修改"，确认后覆盖。diff snapshot 识别手改部分 |
| spec 与代码不同步（用户手改了代码结构，模式 3） | `.studio/specs/` 存的是最后生成的 spec，前端标注"代码可能已偏离 spec" |

---

## §8 测试策略

### 核心原则

**全部使用真实 LLM 调用，不 mock provider。** 测试需要真实 API key（从 `.env` 读取），CI 通过环境变量注入。

### Rust 后端

**studio-core 单元测试**：
| 模块 | 测试重点 |
|---|---|
| `spec.rs` | spec 校验：完整 spec 通过、缺字段失败、agent_type 与 workflow 字段一致性（纯数据逻辑，无 LLM） |
| `coding_agent.rs` | 工具实现（write_file / read_file / ast_check 等）的单元测试。LLM 调用部分用 `#[ignore]` 标记（纯工具逻辑，无 LLM） |
| `project.rs` | 创建/读取/写入项目目录、路径安全（无 LLM） |
| `runner.rs` | subprocess 启动/超时/退出码捕获、events.jsonl 读取解析（无 LLM） |

**元 agent 测试（真实 LLM，`#[ignore]` 标记）**：
- 对话 agent：给真实用户消息（如"我想做一个能查订单的分类助手"），验证 agent 最终调用 `emit_spec` 且 spec JSON 通过 `Spec::validate()` 校验。**断言用结构化字段而非具体内容**：`agent_type` ∈ 合法枚举、`tools` 数组长度 ≥ 0（允许零工具）、`workflow` 结构合法（entry_step 在 steps 中、edges 引用存在的 step）。不断言 LLM 输出的具体文案或工具数量。
- coding agent：用预制合法 spec fixture，运行 coding agent，验证产出的 Python 文件 `ast.parse` 通过。**生成后 smoke test**：`python -c "import ast; ast.parse(open('main.py').read()); import senza"` 验证语法 + import 可用（拦截 LLM 幻觉导致的 nonexistent API 调用）。验证产出的 main.py 包含 Studio 双模式接入代码（`_emit` / `_get_input` 等函数存在）。
- 增量 spec 修改：给当前 spec + 用户反馈（如"加一个搜索工具"），验证对话 agent 调用 `emit_spec_diff` 且 diff 格式合法（JSON Patch ops）。coding agent 应用 diff 后的新 spec 通过 `Spec::validate()`。

**集成测试（真实 LLM，`#[ignore]` 标记）**：
- 端到端：创建项目 → 真实对话（描述一个简单 agent）→ 生成代码 → 运行（真实 Python + 真实 LLM 调用户 agent）→ 读 trace（验证 events.jsonl 格式合法）
- 这条链路是冒烟测试，不是常规回归测试。每次跑可能几分钟 + 消耗 token。CI 中仅在 PR 标签含 `run-e2e` 时触发。

**常规回归测试（无 LLM）**：
- spec 校验逻辑、subprocess 管理、帧协议解析、文件 CRUD、coding agent 工具实现——这些是确定性的，每次 `cargo test` 都跑。
- LLM 测试只验证"LLM 输出能被系统正确消费"（spec 解析、coding agent 产出语法合法），不验证 LLM 输出本身的正确性。

**studio-server 集成测试**：
- REST API：每个端点 happy path + 错误路径（无 LLM 的路径如文件 CRUD 用普通测试；涉及 LLM 的路径用 `#[ignore]` 真实调用）
- WebSocket：对话 streaming 事件序列（`#[ignore]`，真实 LLM，断言收到至少一个 `text_delta` + 最终 `settled`）

### 前端

- 组件测试（Vitest + Testing Library）：对话面板消息渲染、代码编辑器加载/保存、trace 事件列表渲染（用 fixture 数据，不涉及 LLM）
- 状态管理：Zustand store 状态转换（idle → streaming → emitted_spec → generated → running → completed）

### 测试环境要求

- `STUDIO_API_KEY` — 元 agent 的 LLM API key
- `STUDIO_MODEL` — 元 agent 用的模型（如 gpt-4o）
- `OPENAI_API_KEY`（或等价）— 用户 agent 运行时的 LLM key
- `python3` + `senza-sdk` 已安装（`pip install senza-sdk`）
- LLM 测试标记 `#[ignore]`，通过 `cargo test -- --ignored` 单独跑，避免每次 `cargo test` 都消耗 token
