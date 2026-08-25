# Senza Studio — 设计文档 v2.0

> 日期：2026-08-25
> 状态：设计文档（已 review）
> 分类：Architectural
> 前序：v1.0（`docs/infra/design-doc.md`），v2.0 基于 5 仓库基础设施调研后重新设计

---

## §1 定位与使命

**Senza Studio** 是一个面向业务人员的 Agent 开发工作台。业务人员不需要写代码、不需要理解 Senza API，通过对话和文档输入描述业务需求，Studio 帮助他们快速产出可运行的 Agent。

Studio 建立在 Senza SDK 之上。Senza 是 oh-my-harness Rust runtime 的 Python SDK，支持 AgentHarness（单 agent）和 WorkflowEngine（多步工作流）两种模式。Studio 聚焦工作流模式——工作流可视化是核心卖点。

### 目标用户

**业务人员**——不写代码，懂业务逻辑（如运营、产品经理、行业工程师）。输入形态包括论文、图表、结构化文档（SOP/规则表/Excel）和对话讨论。产出物是可直接运行和部署的 Agent 项目，用户完全不碰代码。

### 核心价值闭环

```
对话/文档 → 元 agent 生成 spec（pipeline.yaml）
    ↓
画布确认 workflow 结构
    ↓
Play = Studio 内直接运行（不导出代码）
    ↓
用户在 Studio 内测试（Game 视图交互 + Scene 视图监控）
    ↓
不满意 → 回 Studio 对话修改 → 重新 Play
满意 → Export = 打包完整项目，部署到目标机器
```

### 与 v1.0 设计的关键差异

| 维度 | v1.0 | v2.0 |
|---|---|---|
| Play | 导出完整项目 + 本地启动 | Studio 内直接运行（WorkflowEngine） |
| Export | Play 的副作用 | 独立动作，打包部署 |
| 试跑 | 生成代码 → 跑 Python 进程 | 直接 `stages_to_workflow` → `run()` |
| 决策记忆 | SQLite + FTS5（参考 Folumi） | 去掉，用文档替代 |
| UI 配置 | 独立 `ui_config.yaml` | 合并进 `pipeline.yaml` 的 `ui` 字段 |
| 能力组件 | 元 agent 展开成裸 step（不可逆） | spec 保留组件引用，运行时展开 |
| 前后端通信 | 未明确 | 统一本地 web server + WebSocket |
| Scene 视图 | "复用 Studio 画布代码" | 同一套 ReactFlow 组件，edit/run 两种模式 |
| 运行时 streaming | 未讨论 | 改 runtime：WorkflowEvent 加 TextDelta |
| 导出模式 | 未区分 | 统一 Web 模式 |
| 工具代码保护 | Play 覆盖 + 提示框 | generated/ + custom/ 目录分离 |

### 不做的事（v1）

- 拖拽编辑 DAG（LLM 生成 + 对话微调，不手动拖拽）
- 非工作流 agent（聚焦 WorkflowEngine，不做单 AgentHarness 模式）
- 多 agent 协作（spawn 子 agent）
- 在 webui 里编辑 spec（Scene 视图只读，编辑回 Studio）
- 项目版本管理
- 插件市场（先做静态包 `senza-studio-components`，推广后再做市场）
- 决策记忆（用文档替代）
- Session Recall（v1 不开，SDK 能力已就绪，按需开启）
- 热加载（每次 Play 重新 import）
- CLI 导出模式（统一 Web 模式）

---

## §2 整体架构

```
┌─ Electron 前端（Studio 编辑器 + 运行时）──────────────────┐
│                                                          │
│  editing 模式:                          playing 模式:     │
│  ┌──────────┬─────────────┐  ┌────────────────┬───────┐ │
│  │ 对话面板  │ 画布(edit)   │  │ Game/Scene(切换)│Insp  │ │
│  │          │ + Inspector │  │ + 控制条        │+Cons │ │
│  └──────────┴─────────────┘  └────────────────┴───────┘ │
│  对话面板在 playing 时变为可折叠侧边栏                      │
└──────────────────────┬───────────────────────────────────┘
                       │ HTTP + WebSocket (localhost)
┌──────────────────────▼───────────────────────────────────┐
│  Python 后端（Senza SDK，dogfooding）                      │
│                                                          │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │  元 agent          │  │  Play 引擎        │             │
│  │  (AgentHarness)   │  │  (WorkflowEngine) │             │
│  │  · 对话/文档/工具   │  │  · executor       │             │
│  │  · Session 持久化  │  │  · judge          │             │
│  │                   │  │  · 事件流          │             │
│  └──────────────────┘  └──────────────────┘             │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ spec 管理  │ │ 预处理器  │ │ 预制件库  │ │ Export   │   │
│  │ (内存dict)│ │ (展开组件)│ │ (注册表) │ │ (打包)   │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘   │
└──────────────────────────────────────────────────────────┘
         │ Export（独立动作）
┌────────▼─────────────────────────────────────────────────┐
│  导出项目（独立可运行）                                     │
│                                                          │
│  my-agent/                                               │
│  ├── pipeline.yaml          # spec                       │
│  ├── tools/                 # 定制工具 (generated + custom)│
│  ├── plugins/               # 项目插件                    │
│  ├── webui/dist/            # senza-studio-webui 构建产物 │
│  ├── pyproject.toml         # 依赖                        │
│  ├── .env.example           # API key 模板               │
│  └── README.md              # 部署说明                   │
│                                                          │
│  依赖: senza-sdk + senza-studio-runtime                  │
│       + senza-studio-components + senza-studio-webui     │
│                                                          │
│  webui 双视图: Game + Scene + Inspector + Console         │
└──────────────────────────────────────────────────────────┘
```

### 三层职责

| 层 | 职责 | 技术 |
|---|---|---|
| **Electron 前端** | editing: 对话面板 + 画布 + Inspector；playing: Game/Scene + Inspector + Console + 控制条 | Electron + React + ReactFlow |
| **Python 后端** | 元 agent + Play 引擎 + spec 管理 + 预处理器 + 预制件注册表 + Export | Senza SDK（dogfooding） |
| **导出项目** | 完整可运行的 Agent 项目，自带 Web webui | FastAPI + React + Senza SDK + senza-studio-runtime |

### 关键设计决策

1. **Play 内置**——Studio 内直接运行 spec，不生成代码。`spec → preprocess → stages_to_workflow → WorkflowEngine → run()`。
2. **Export 独立**——Export 是打包部署动作，和 Play 解耦。Play 是"试"，Export 是"部署"。
3. **spec 是 single source of truth**——pipeline 逻辑和 UI 配置（`ui` 字段）共存于一个文件。对话面板、画布、Play 引擎都从同一个 spec 渲染。
4. **元 agent 用 Senza 自身构建**（dogfooding）——元 agent 是一个 AgentHarness，带 Session 持久化。
5. **统一通信协议**——Studio 和导出项目都用本地 web server + WebSocket。一套组件，两种壳（Electron / 浏览器）。
6. **预制件是引用**——工具/能力组件在 spec 里引用名字，运行时和导出时从注册表查找实现。

---

## §3 数据模型

### 项目目录结构

```
~/.senza-studio/projects/<project-id>/
├── .studio/                        # Studio 管理数据
│   ├── meta.json                   # 项目元数据 + 活跃 session
│   ├── docs/                       # 用户上传文档 + 元 agent 写的笔记
│   │   ├── paper.pdf
│   │   ├── flowchart.png
│   │   └── design-notes.md
│   ├── specs/                      # spec 快照历史
│   │   └── <spec-id>/
│   │       └── pipeline.yaml
│   └── sessions/                   # 元 agent 对话历史（Senza Session JSONL）
│       ├── <session-1>.jsonl
│       └── <session-2>.jsonl
├── pipeline.yaml                   # 当前活跃 spec（含 ui 配置）
├── tools/                          # 定制工具
│   ├── registry.py                 # get_tools() → {name: Tool}
│   ├── generated/                  # 元 agent 生成
│   └── custom/                     # 开发者手写
├── plugins/                        # 项目插件集
└── exports/                        # 导出包输出目录
    └── my-agent-v1/
```

### meta.json

```json
{
  "id": "proj-abc123",
  "name": "订单处理流程",
  "created_at": "2026-08-25T...",
  "updated_at": "2026-08-25T...",
  "status": "editing",
  "model": "deepseek-chat",
  "active_session": "<session-2>",
  "sessions": ["<session-1>", "<session-2>"],
  "last_played_at": null,
  "last_export_dir": null
}
```

`status` 枚举：`editing` / `playing` / `exported`

### pipeline.yaml（spec）

使用 Senza 原生声明式格式，内嵌 `ui` 字段和 `component` 引用。元 agent 通过工具 API 增量构建，不直接写 YAML。

```yaml
stages:
  - name: classify
    type: agent
    prompt_template: |
      你是订单分类助手。根据订单内容分类到：退货/投诉/咨询/正常。
      订单内容：{order_content}
      输出 JSON：{"category": "退货|投诉|咨询|正常"}
    output_key: classify_result
    ui:
      display: chat
    next_on_success: route

  - name: route
    type: checker
    tool: route_by_category
    ui:
      display: status
    next_on_return: return_process
    next_on_complaint: complaint_process
    next_on_normal: normal_process

  - name: return_process
    type: agent
    prompt_template: "处理退货流程：{order_content}"
    ui:
      display: chat
    next_on_success: approval_section

  - name: approval_section                # 能力组件引用
    component: approval_flow
    params:
      title: "退货审批"
      approver: "{order.manager}"
    next_on_approve: notify_warehouse
    next_on_reject: notify_customer

  - name: notify_warehouse
    type: tool
    tool: send_email
    ui:
      display: status
    next_on_success: success

  - name: notify_customer
    type: tool
    tool: send_email
    ui:
      display: status
    next_on_success: success

  - name: success
    type: terminal
    message: "处理完成"
```

### `ui` 字段

内嵌在 step 里，不影响流程语义，只管怎么展示。`stages_to_workflow` 不认识 `ui`，保留在 step config 里不解析也不报错。

`display` 类型枚举：

| 类型 | 用途 | 渲染 |
|------|------|------|
| `chat` | LLM step 的输出 | 聊天气泡，streaming |
| `status` | tool/checker 的执行结果 | 状态标记 + 详情展开 |
| `table` | 结构化结果 | 表格渲染 |
| `chart` | 数值结果 | 图表（Plotly） |
| `approval_form` | 人工审批 | 表单 + 按钮 |
| `none` | 不展示 | 无 UI |

### `component` 字段

能力组件引用。spec 预处理器在编译前展开：遇到 `component:` → 查注册表 → 用 params 填充模板 → 生成实际 step + edge（带 `_component` 元数据）→ 展开后的 spec 再走 `stages_to_workflow`。

---

## §4 元 Agent 层

元 agent 是 Studio 的核心。它是一个 `AgentHarness`，用 Senza SDK 自身构建（dogfooding）。

### 4.1 元 agent 与 Play 引擎的关系

两个独立的 AgentHarness 实例：

| Harness | 工具来源 | 生命周期 |
|---|---|---|
| 元 agent | Studio 注册的 spec 构建工具 + 文档工具 + 预制件工具 + 生成工具 | 长期，带 Session 持久化 |
| Play agent step | `tools/registry.py` 里 spec 引用的工具 + 项目插件集 | 单 step，用完释放 |

元 agent 不注入 Play 的工具，Play 不注入元 agent 的工具。两者隔离。

### 4.2 元 agent 的能力

| 能力 | 说明 |
|---|---|
| 文档理解 | `ingest_document` 解析用户上传的文档（确定性解析 + vision 兜底） |
| 对话 | 理解意图，反问澄清，生成/更新 spec |
| spec 构建 | 通过工具 API 增量构建 spec（`add_step`/`add_edge` 等） |
| 预制件推荐 | 优先推荐预制件，覆盖不了才生成定制工具 |
| 定制工具生成 | `generate_tool` 生成 + 静态验证（import + 调用 `get_tools()`） |
| 文档笔记 | `write_document` 写设计笔记/决策记录为文档 |

### 4.3 文档理解（多模态输入）

策略：确定性解析为主，vision 兜底。

| 文档类型 | 解析方式 | 工具 |
|---------|---------|------|
| Excel/CSV | pandas → 结构化 JSON | `pandas.read_excel` / `read_csv` |
| PDF | 文本提取 + 图片提取 | `pypdf` / `pdfplumber` |
| 图片 | Vision 模型理解 | LLM 多模态能力 |
| 纯文本/Markdown | 直接读取 | 文件读取 |
| JSON/YAML | 直接解析 | `json` / `yaml` |

文档原文存 `.studio/docs/`，元 agent 后续可通过 `read_document` 按需读取。

### 4.4 spec 构建

元 agent 不直接写 pipeline.yaml，通过工具 API 增量构建。Studio 后端维护 spec 为内存中的 Python dict，工具调用修改它。YAML 只是序列化输出。

元 agent 的 system prompt 指导：
- 多轮对话理解用户想构建什么 workflow
- 信息不足时反问澄清（步骤数量、条件分支、工具需求、审批节点等）
- 信息充分后调用 `add_step` / `add_edge` 增量构建
- 优先 `search_prefabs` / `recommend_prefabs`，覆盖不了才 `generate_tool`
- 完成后调 `validate_spec`

### 4.5 system prompt 策略

动态组装：

- **固定段**：角色定义、对话规则、spec 构建规范
- **动态段**：当前 spec 摘要、已安装的预制件清单、项目文档列表

元 agent 每轮对话看到的 system prompt 包含最新上下文，不依赖对话历史恢复项目状态。

### 4.6 Session 管理

多 session 模型：

- 一个项目可以有多个对话 session
- 用户可以打开任意旧 session 继续对话
- 新 session 开始时，system prompt 动态段注入当前 spec 摘要 + 文档列表
- 旧 session 归档在 `.studio/sessions/`，不删除
- Session Recall（v1 不开，SDK 能力已就绪）

### 4.7 元 agent 的工具集

**文档工具：**

| 工具 | 说明 |
|------|------|
| `ingest_document(file_path)` | 解析文档，返回结构化内容 |
| `read_document(doc_id, section?)` | 读取已上传文档 |
| `list_documents()` | 列出项目文档 |
| `write_document(name, content)` | 写笔记/设计记录 |

**spec 构建工具：**

| 工具 | 说明 |
|------|------|
| `add_step(name, description, type, prompt_template)` | 添加步骤 |
| `add_edge(from, to, condition)` | 添加连线/条件分支 |
| `set_step_property(step, key, value)` | 设置步骤属性 |
| `bind_tool(step, tool_ref)` | 绑定预制工具 |
| `set_ui_config(step, display, fields)` | 设置 UI 展示 |
| `get_current_spec()` | 读取当前 spec |
| `validate_spec()` | 校验 spec 完整性 |
| `remove_step(name)` | 删除步骤 |
| `remove_edge(from, to, condition)` | 删除连线 |

**预制件工具：**

| 工具 | 说明 |
|------|------|
| `list_prefabs(kind?)` | 列出可用预制件 |
| `search_prefabs(query)` | 按关键词搜索 |
| `recommend_prefabs(description)` | 根据需求推荐 |

**定制工具生成：**

| 工具 | 说明 |
|------|------|
| `generate_tool(name, description, implementation_spec)` | 生成定制工具代码 + 静态验证 |

静态验证：`ast.parse` → import 模块 → 调用 `get_tools()` → 检查返回的 Tool name 与 spec 引用一致 → 检查 parameters 是合法 JSON Schema。失败则 retry（最多 2 次），仍失败标记为 stub。

### 4.8 元 agent 的 plugin 栈

参考 senza-agent 的 `create_agent()` 最佳实践：

```python
builder = (
    senza.HarnessBuilder(config.model)
    .provider("*", provider)
    .system_prompt(dynamic_system_prompt(spec, prefabs, docs))
    .env(env)
    .plugin(senza.create_fs_tools_plugin())
    .plugin(senza.strategy.safety_defaults())
    .plugin(senza.strategy.loop_safety())
    .plugin(senza.strategy.tool_output_guard(env))
    .plugin(senza.strategy.injection_filter())
    .auto_compact(True)
    .retry(3, 1000)
    .tools(studio_spec_tools)       # add_step/add_edge/...
    .tools(studio_doc_tools)        # ingest/read/list/write
    .tools(studio_prefab_tools)     # list/search/recommend
    .tools(studio_gen_tools)        # generate_tool
)
```

每个工具注册有 try/except 保护，单个组件失败不阻塞整体。

---

## §5 预制件系统

### 三层预制件

| 层 | 是什么 | 例子 | 进 spec 的方式 |
|---|---|---|---|
| **工具** | 一个 Senza `create_tool` 定义 | `db_query`、`send_email` | step 里 `tool: db_query` |
| **能力组件** | 一组工具 + workflow 片段 | "审批流"（pause + resume + 通知） | step 里 `component: approval_flow` + `params` |
| **UI 组件** | 前端渲染组件 | "表格展示"、"审批表单" | step 里 `ui.display: approval_form` |

### 引用模式

spec 里只写预制件名字，不写实现。运行时和导出时从注册表查找。

### 能力组件：引用而非展开

spec 里保留 `component` 引用，预处理器在编译前展开：

```yaml
- name: approval_section
  component: approval_flow
  params:
    title: "退货审批"
  next_on_approve: notify_warehouse
  next_on_reject: notify_customer
```

能力组件定义在 `senza-studio-components` 包里：

```python
# senza-studio-components/components/approval_flow.py
COMPONENT = {
    "name": "approval_flow",
    "steps": [
        {"name": "{prefix}_pause", "type": "checker", "tool": "request_approval",
         "ui": {"display": "approval_form"}},
        {"name": "{prefix}_notify", "type": "tool", "tool": "send_email"},
    ],
    "edges": [
        {"from": "{prefix}_pause", "to": "{prefix}_notify", "condition": "approve"},
    ],
    "ports": {
        "entry": "{prefix}_pause",
        "approve": "{prefix}_notify",
        "reject": None,
    }
}
```

展开时生成的 step 带 `_component` 和 `_component_instance` 元数据字段，Scene 视图据此画 group 容器。

### 定制工具

预制件覆盖通用能力，覆盖不了的场景元 agent 生成定制工具：

- 元 agent 通过 `generate_tool` 生成 Python 实现
- 生成到 `tools/generated/`，在 `tools/registry.py` 追加注册
- 生成后立即静态验证
- 如果太复杂，标记为 stub，提示需要开发人员补充
- 开发人员手写工具放 `tools/custom/`，按同样格式注册
- `tools/registry.py` 统一返回 `{name: Tool}` 字典

### senza-studio-components 包

```
senza-studio-components/
├── tools/               # 工具预制件
│   ├── db_query.py
│   ├── send_email.py
│   └── web_search.py
├── components/          # 能力组件定义
│   ├── approval_flow.py
│   └── data_pipeline.py
└── ui/                  # UI 组件（或 npm 包 senza-studio-webui）
```

---

## §6 spec 预处理器

编辑态 spec 和 `stages_to_workflow` 消费的运行态 spec 不同。预处理器是纯 Python 函数，在 Studio 应用层：

```
编辑态 spec (dict) → preprocess(spec, components_dir) → 运行态 spec (dict) → stages_to_workflow
```

### 预处理步骤

| 步骤 | 做什么 |
|---|---|
| 1. 组件展开 | `component: approval_flow` → 查注册表 → params 填充模板 → 生成 step + edge，加 `_component` 元数据 |
| 2. type 保留 | `type: agent/checker/tool` 保留在 step config 里，executor callback 读它分派 |
| 3. ui 保留 | `ui` 字段保留在 step config 里，前端读它渲染 Game 视图 |
| 4. 校验 | entry_step 存在、edges 引用有效 step、terminal 可达 |

### 为什么在应用层

组件展开、type 语义、ui 字段都是 Studio 的概念，不是 SDK 通用概念。预处理器依赖 `senza-studio-components` 包。Studio 和导出项目用同一个预处理器（打包在 `senza-studio-runtime` 里）。

---

## §7 Play 内置运行时

### 运行流程

```
Play 按钮
  ↓
1. 加载 pipeline.yaml → spec dict
2. preprocess(spec, components_dir="plugins/") → runtime spec
3. stages_to_workflow(runtime_spec) → Workflow
4. WorkflowEngine(workflow, provider, model, executor, judge)
5. engine.run() → 事件流 → WebSocket → 前端
```

### executor callback 的 type 分派

所有非 terminal step 被 `stages_to_workflow` 映射为 `Step::Executor`。Studio 注册一个 executor callback，按 `type` 字段分派：

```python
def studio_executor(ctx):
    step = ctx.current_step
    step_type = step.config.get("type")

    if step_type == "agent":
        # 创建短生命周期 Harness，执行 prompt
        # streaming tokens 通过 WorkflowEvent.TextDelta 推送
        harness = build_step_harness(step, project_plugins)
        result = harness.prompt_and_collect(step.config["prompt_template"].format(**ctx.variables))
        return StepResult(output=result, structured={"route_key": "success"})

    elif step_type == "checker":
        # 检查 context variables 里有没有审批结果
        # 没有 → 返回 route_key 找不到对应边 → judge 返回 Pause
        # 有 → 返回 route_key → judge 路由
        tool = tools_registry[step.config["tool"]]
        result = tool.invoke(ctx)
        return StepResult(output=result, structured={"route_key": result["route"]})

    elif step_type == "tool":
        tool = tools_registry[step.config["tool"]]
        result = tool.invoke(ctx)
        return StepResult(output=result, structured={"route_key": "success"})
```

### 审批的 pause/resume（现有机制，不需要改 runtime）

1. checker step 执行 → context 里没有 `approval_result` → 返回 `route_key: "pending_approval"`
2. judge 找不到 `next_on_pending_approval` 边 → `Transition::Pause("等待审批")`
3. `apply_transition` push StepRecord（带 `transition: Pause`），status 置 Paused
4. `run_loop` 发 `Paused` 事件，返回
5. **`current_step` 不变**——仍然是这个 checker step
6. 前端 Game 视图渲染审批表单
7. 用户填表提交 → Studio 后端写 context variable: `approval_result = "approve"`
8. `engine.resume()` → step 重新执行 → executor 读到 `approval_result` → 返回 `route_key: "approve"`
9. judge 匹配 `next_on_approve` → `Transition::To(next_step)`

### 事件流

改 runtime：WorkflowEvent 加 `TextDelta { step_id, delta }` 变体。

| 事件 | 渲染目标 |
|---|---|
| `StepStarted` | Scene 视图: 节点高亮 |
| `StepProgress` | Inspector: 工具调用详情 |
| `TextDelta` | Game 视图: LLM streaming |
| `StepFinished` | Scene 视图: 节点完成 + Inspector: 输出/指标 |
| `Paused` / `Resumed` | 控制条状态 + Game 视图: 审批表单 |
| `Failed` | Console + Scene 视图: 节点标红 |

一个事件源（`engine.subscribe()`），一个 WebSocket，前端按事件类型分派。

broadcast channel 容量 64，text_delta 是高频事件。step 结束时 `StepFinished` 带 `StepResult` 有完整输出。容量不够时 drop TextDelta，不 drop 关键事件。

### 工具加载

同进程，`tools/registry.py` 统一注册。Play 时重新 import：

```python
import importlib
mod = importlib.import_module("tools.registry")
tools = mod.get_tools()
# executor callback: tool = tools[step.config["tool"]]
```

`generated/` 和 `custom/` 在同一个 `tools/` 目录，运行时不关心来源。每次 Play 重新 import（不做热加载）。

### 插件集隔离

| 应用 | 插件用途 | 安装位置 |
|---|---|---|
| Studio（元 agent） | 文档解析、spec 构建等 Studio 自身能力 | `~/.senza-studio/plugins/` |
| 项目（Play/Export） | 业务流程里 step 引用的工具/组件/UI | `<project>/plugins/` |

Play 时加载当前项目的插件集，不注入 Studio 插件。两者隔离。

---

## §8 运行时交互（Unity 引擎模式）

### 状态机

```
editing ←→ playing
```

- `editing`：元 agent 可修改 spec，画布可编辑，对话面板是主区域
- `playing`：WorkflowEngine 运行，画布只读，对话面板变为可折叠侧边栏
- Stop 回到 `editing`

Play 时对话仍可用但元 agent 不修改 spec（只回答观察）。用户要改 spec，先 Stop。

### 双视图

| 视图 | 对应 Unity | 用途 | 内容 |
|------|-----------|------|------|
| **Game 视图** | Game 视图 | 用户实际交互 | 时间线渲染：按 step 执行顺序从上到下追加 UI 卡片 |
| **Scene 视图** | Scene 视图 | 运行监控（只读） | DAG 节点状态高亮 + 条件分支选中标记 |

两个视图看同一个运行实例的不同渲染。Game 是时间线（聊天应用模式），Scene 是空间图（DAG）。

### Game 视图：时间线模型

按 step 执行顺序，从上到下追加 UI 卡片（聊天气泡、状态条、表格、审批表单）。branch/loop 时多次执行的 step 出现多个卡片。不需要在 spec 里维护布局信息。

### Scene 视图：折叠/展开

三个维度：

| 模式 | 数据源 | 交互 |
|---|---|---|
| edit | spec dict | 拖拽/选中/Inspector 编辑 |
| run | spec dict + WorkflowEvent 实时状态 | 选中/Inspector 只读 |

能力组件可折叠：默认显示为一个带子节点的 group，点击展开。展开后的 step 带 `_component` 元数据，ReactFlow 据此画 group 容器。

### Inspector

**编辑态：**

| 面板 | 内容 |
|---|---|
| 基本信息 | step name、type、component |
| 属性 | prompt_template、tool 引用、output_key、retry/timeout |
| UI 配置 | display 类型、fields |
| edges | 出边和条件 |

**运行态：**

| 面板 | 内容 |
|---|---|
| 基本信息 | step name、type、status |
| 输入 | context variables |
| LLM 对话 | prompt + response（含 streaming 记录） |
| 工具调用 | tool name、args、result、耗时 |
| 输出 | structured JSON + output text |
| 指标 | 耗时、token 用量、成本 |

Inspector 编辑直接改 spec dict（不经过元 agent）。元 agent 下一轮对话前 `get_current_spec()` 自然看到修改。

### 运行控制条

| 按钮 | 行为 |
|------|------|
| Play | 启动/恢复 workflow |
| Pause | 手动暂停（步边界） |
| Step | 单步执行 |
| Stop | 终止运行，回到 editing |

### Console

实时日志流，按 step 分组。step 执行日志、工具调用日志、LLM 请求/响应摘要、错误和警告。

---

## §9 前端架构

### 技术栈

Electron + React + Tailwind + ReactFlow（画布）。

### 通信

本地 web server（FastAPI）+ WebSocket。Studio 和导出项目用同一套协议。Electron 加载 `http://localhost:PORT`。

### Studio 布局

**editing 模式：**

```
┌──────────────┬───────────────────────────┐
│  对话面板     │  画布（Scene 编辑态）        │
│              │  + Inspector               │
├──────────────┴───────────────────────────┤
│  预制件库 / 状态栏                         │
└──────────────────────────────────────────┘
```

**playing 模式：**

```
┌─────────┬────────────────────────┬───────┐
│ 对话侧栏 │  Game 视图 / Scene 视图  │ Insp  │
│ (可折叠) │  (切换)                 │ +Cons │
│         ├────────────────────────┴───────┤
│         │  控制条: Play/Pause/Step/Stop    │
└─────────┴────────────────────────────────┘
```

对话面板在 playing 时变为可折叠侧边栏，默认收起。

### 导出项目 webui 布局

```
┌──────────────────────────┬──────────────┐
│  Game 视图 / Scene 视图    │  Inspector   │
│  (切换)                   │  + Console   │
├──────────────────────────┴──────────────┤
│  控制条: Play/Pause/Step/Stop             │
└──────────────────────────────────────────┘
```

### 前端状态管理

Zustand store。

- Studio editing: `idle` → `conversing` → `spec_ready` → `playing` → `conversing`（迭代）
- Studio playing / 导出项目: `idle` → `running` → `paused` → `running` → `completed` / `failed`

### senza-studio-webui

抽成独立 npm 包，Studio 和导出项目共用。一套 React 组件，两种壳（Electron / 浏览器）。Game 视图、Scene 视图、Inspector、Console、控制条都在这个包里。

---

## §10 插件系统

### 插件分层

```
插件包 (manifest.yaml)
├── 工具          → Plugin trait register_tools     (runtime)
├── Hooks         → Plugin trait register_hooks     (runtime)
├── Skills        → Plugin trait register_skills    (runtime)
├── Prompt 模板   → Plugin trait register_templates  (runtime)
├── 记忆后端      → Plugin trait register_memory     (runtime, 需扩展, v1 推迟)
├── 知识源        → Plugin trait register_knowledge  (runtime, 需扩展, v1 推迟)
├── 能力组件      → spec 预处理器展开               (Studio 层)
└── UI 组件       → 前端组件注册表                   (Studio 层)
```

前四个是 runtime Plugin trait 已有的向量。memory/knowledge 扩展推迟到有插件需求时。能力组件和 UI 组件是 Studio 应用层的，不进 runtime。

### 两个独立插件集

| 应用 | 插件用途 | 安装位置 |
|---|---|---|
| Studio | 元 agent 的能力（文档解析、spec 构建等） | `~/.senza-studio/plugins/` |
| 项目（Play/Export） | 业务流程里 step 引用的工具/组件/UI | `<project>/plugins/` |

插件市场是共享来源，但安装是独立的。Play 时用项目插件集，不注入 Studio 插件。

### 注册时机

固定集合（v1）：

- Studio 启动时扫描已安装插件，import Python 模块，缓存 Plugin 实例
- 创建 Harness（元 agent 或 Play）时把对应插件集全部 `.plugin()` 进去
- MCP 作为补充：外部工具服务器走 `builder.mcp_config_file()`，运行时发现

### v1 不做插件市场

先做静态 pip 包 `senza-studio-components`。推广后再做市场（三层模型：Registry → Package with manifest.yaml → Runtime）。

---

## §11 Export 与打包

### Export = 独立动作

Export 和 Play 解耦。Play 是"试"，Export 是"部署"。

### 全量打包

导出项目自包含（除 MCP server 外）：

| 内容 | 打包方式 |
|---|---|
| pipeline.yaml | 拷贝 |
| tools/ (generated + custom + registry.py) | 拷贝 |
| plugins/ | 拷贝 |
| webui/dist/ | senza-studio-webui 构建产物 |
| pyproject.toml | 生成（senza-sdk + senza-studio-runtime + senza-studio-components + 专属依赖） |
| .env.example | 生成 |
| README.md | 生成 |

### 导出项目结构

```
my-agent/
├── pipeline.yaml
├── tools/
│   ├── registry.py
│   ├── generated/
│   └── custom/
├── plugins/
├── webui/
│   └── dist/               # senza-studio-webui 构建产物
├── pyproject.toml
├── .env.example
└── README.md
```

### 导出项目依赖

| 包 | 类型 | 内容 |
|---|---|---|
| `senza-sdk` | pip | AgentHarness + WorkflowEngine + stages_to_workflow |
| `senza-studio-runtime` | pip | executor + judge + preprocessor |
| `senza-studio-components` | pip | 预制工具 + 能力组件定义 |
| `senza-studio-webui` | npm | 前端组件（构建进 dist/） |

### main.py runner

导出项目的 `main.py` 是固定 runner，从 `senza-studio-runtime` 入口：

```python
# senza-studio-runtime 提供 CLI 入口
# senza-studio-runtime serve pipeline.yaml --port 8000
```

runner 职责：加载 spec → preprocess → stages_to_workflow → WorkflowEngine → 启动 FastAPI webui server。

不生成 Studio 相关的接入代码——导出项目是独立的，不依赖 Studio 运行时。

---

## §12 迭代模式

用户测试后发现需要修改，回 Studio 对话修改 spec：

### 三种修改方式

1. **对话修改**（主要路径）：用户在对话面板描述修改需求 → 元 agent 读取当前 spec → 通过工具 API 增量修改 → 画布实时更新 → 重新 Play
2. **画布选中 + 对话**：用户在画布选中节点 → Inspector 显示属性 → 在对话面板说"把这步拆成两步" → 元 agent 修改 spec
3. **Inspector 直接编辑**：用户在 Inspector 改属性（prompt、tool、ui 配置）→ 直接改 spec dict → 画布刷新
4. **重新对话**（大改）：用户描述全新需求 → 元 agent 重新构建 spec（旧 spec 存入 `.studio/specs/` 作为快照）

### spec 快照

每次元 agent 完成一轮 spec 修改，存一份快照到 `.studio/specs/<spec-id>/pipeline.yaml`。可追溯演化历史。

### spec 变更与代码同步

- spec 变更后重新 Play，不需要重新生成代码——Play 内置直接运行 spec
- 定制工具：如果 spec 引用的工具没变，不重新生成；如果新增 step 需要新工具，元 agent 生成
- `tools/generated/` 由元 agent 管理，`tools/custom/` 由开发者管理，互不覆盖

---

## §13 错误处理与边界情况

### 元 Agent 层

| 场景 | 处理 |
|---|---|
| 元 agent LLM 调用失败 | 对话面板显示错误，对话历史保留 |
| 元 agent 输出的 spec 不合法 | `validate_spec` 失败 → 返回错误给元 agent，让它修正 |
| 元 agent 生成的定制工具语法错误 | `ast.parse` 验证 → 失败则 retry（最多 2 次），仍失败标记为 stub |
| 元 agent 生成的定制工具 import 失败 | 静态验证（import + `get_tools()`）捕获 → retry |

### 项目运行

| 场景 | 处理 |
|---|---|
| Python 未安装 / senza-sdk 未安装 | Play 时环境检测失败，提示安装或选择 Export |
| workflow 运行时崩溃 | webui Console 显示错误，DAG 标记失败节点 |
| 审批节点超时 | workflow pause 状态保持，等待用户操作 |
| API key 未配置 | 运行时 LLM 调用失败，Console 显示错误 |
| 条件路由 LLM 输出不合规 JSON | step 标记 failed，Console 显示原始输出 |

### 迭代循环

| 场景 | 处理 |
|---|---|
| spec 与工具代码不同步 | 以 spec 为准，Play 时缺失工具报错，元 agent 补生成 |
| 开发者在 `tools/custom/` 写的工具 | Play 直接加载，不被覆盖 |
| 元 agent 重新生成 `tools/generated/` | 只覆盖 generated/，不碰 custom/ |

---

## §14 测试策略

### 核心原则

涉及 LLM 的测试用真实调用（标记 `@pytest.mark.llm`），不 mock provider。确定性逻辑用常规测试。

### Python 后端

| 模块 | 测试重点 |
|---|---|
| spec 构建工具 | add_step/add_edge/validate_spec 的纯逻辑测试（无 LLM） |
| spec 预处理器 | 组件展开、type 保留、ui 保留、校验（无 LLM） |
| executor callback | type 分派逻辑（mock tools，无 LLM） |
| 定制工具验证 | ast.parse + import + get_tools() 验证（无 LLM） |
| Export | 全量打包生成（无 LLM） |

### 元 Agent 测试（真实 LLM）

- 文档理解：给真实 PDF/Excel/图片，验证 `ingest_document` 返回结构化内容
- spec 生成：给真实用户消息，验证元 agent 调用 spec 构建工具且 `validate_spec` 通过
- 定制工具生成：给需要定制工具的场景，验证生成的 Python 代码静态验证通过

### 集成测试（真实 LLM）

- 端到端：创建项目 → 对话描述需求 → 生成 spec → Play → 运行 workflow → 验证事件流
- 标记 `@pytest.mark.e2e`，CI 中仅在特定标签触发

### 前端

- 组件测试（Vitest + Testing Library）：对话面板、画布渲染、Inspector、Game 视图时间线

---

## §15 技术栈总览

| 组件 | 技术 | 参考 |
|------|------|------|
| Studio 后端 | Python + Senza SDK | dogfooding |
| Studio 前端 | Electron + React + Tailwind + ReactFlow | — |
| 导出项目 webui 后端 | FastAPI + WebSocket | arcgensenza |
| 导出项目 webui 前端 | React + Tailwind + ReactFlow（senza-studio-webui） | arcgensenza |
| spec 格式 | pipeline.yaml（Senza 原生声明式 + ui 字段 + component 引用） | arcgensenza + Studio 扩展 |
| 文档解析 | pandas + pypdf + LLM vision | — |
| 打包 | 全量打包 | arcgensenza pack_python.sh |
| 预制件包 | senza-studio-components（pip） | — |
| 运行时包 | senza-studio-runtime（pip） | — |
| 前端组件包 | senza-studio-webui（npm） | — |

---

## §16 runtime 改动

### v1 必须

| 改动 | 说明 |
|---|---|
| WorkflowEvent 加 `TextDelta { step_id, delta }` | streaming tokens 透传到事件流，Game 视图需要 |

### v1 推迟

| 改动 | 说明 |
|---|---|
| Plugin trait 加 `register_memory` / `register_knowledge` | 插件系统统一，有插件需求时再做 |

### 不需要改

| 能力 | 现有机制 |
|---|---|
| pause/resume | `Transition::Pause`（judge 发出）+ `resume()` 重新执行同一步 + context variables 传递用户输入 |
| 审批 | checker step 返回未匹配 route_key → judge 返回 Pause → 用户提交 → resume |
| 事件流 | `engine.subscribe()` → broadcast channel，加 TextDelta 后完整 |
| 持久化 | `JsonlTaskStore` + `JsonlSessionRepo` |

---

## §17 参考实现

| 项目 | 参考内容 |
|------|---------|
| arcgensenza | pipeline.yaml 声明式 spec → `stages_to_workflow` 编译；executor/judge 分派模式；webui（FastAPI + React + WebSocket + DAG）；Electron 壳；打包部署（pack_python.sh） |
| Folumi | 记忆模型设计（v2 不用，但架构可参考）；Tauri/Electron 桌面壳 |
| senza-agent | 完整 plugin 栈组装（`create_agent()`）；try/except 条件装配；Behavior 模式（Advisor + Acceptance Gate）；工具函数与注册分离；Per-run persistence；aiohttp WebServer；AGENTS.md 运行规范 |
| Senza SDK | AgentHarness（元 agent）；WorkflowEngine（运行时）；Session 持久化；`stages_to_workflow`（spec 编译） |
| llm-harness-runtime | WorkflowEvent（加 TextDelta）；Transition::Pause（审批 pause/resume）；Plugin trait（四向量）；MCP（运行时工具发现） |
