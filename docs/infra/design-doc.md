# Senza Studio — 设计文档

> 日期：2026-08-25
> 状态：设计草案 v1.0
> 分类：Architectural

---

## §1 定位与使命

**Senza Studio** 是一个面向业务人员的 Agent 开发工作台。业务人员不需要写代码、不需要理解 Senza API，通过对话和文档输入描述业务需求，Studio 帮助他们快速产出可运行的 Agent。

Studio 建立在 Senza SDK 之上。Senza 是 oh-my-harness Rust runtime 的 Python SDK，支持 AgentHarness（单 agent）和 WorkflowEngine（多步工作流）两种模式。Studio 聚焦工作流模式——工作流可视化是核心卖点。

### 目标用户

**业务人员**——不写代码，懂业务逻辑（如运营、产品经理、行业工程师）。输入形态包括论文、图表、结构化文档（SOP/规则表/Excel）和对话讨论。产出物是可直接运行和部署的 Agent 项目，用户完全不碰代码。

### 核心价值闭环

```
对话/文档 → 元 agent 生成 spec + ui_config + 定制工具
    ↓
画布确认 workflow 结构
    ↓
Play = 一键导出完整项目 + 本地启动
    ↓
用户在 webui 里测试（Game 视图交互 + Scene 视图监控）
    ↓
不满意 → 回 Studio 对话修改 → 重新 Play
满意 → 打包部署到目标机器
```

### 与旧 senza-studio 的关键差异

| 维度 | 旧 senza-studio | 本设计 |
|---|---|---|
| 用户 | 开发者（会 Python） | 业务人员（不写代码） |
| 技术栈 | Rust + React | Python + Electron |
| 产出 | Python 项目代码 | 一键导出+启动的完整项目 |
| 工作流编辑 | spec diff 规则引擎 | 元 agent 通过工具 API 增量构建 |
| 试跑 | 生成代码 → 跑 Python 进程 | Play = 导出+本地启动，无独立试跑环境 |
| 元 agent 记忆 | 无 | 三层记忆（Session + 决策记忆 + 文档） |
| 运行时交互 | 简单 trace 渲染 | Unity 引擎模式（双视图 + Inspector + Play/Pause/Step） |

### 不做的事（v1）

- 拖拽编辑 DAG（LLM 生成 + 对话微调，不手动拖拽）
- 非工作流 agent（聚焦 WorkflowEngine，不做单 AgentHarness 模式）
- 多 agent 协作（spawn 子 agent）
- 在 webui 里编辑 spec（Scene 视图只读，编辑回 Studio）
- 项目版本管理
- 非技术用户零代码体验的全部覆盖（v1 仍需要业务人员理解流程概念）

---

## §2 整体架构

```
┌─ Electron 前端（Studio 编辑器）──────────────────────────┐
│                                                          │
│  ┌──────────────┬───────────────────────────────────┐   │
│  │  对话面板     │  画布（Scene 视图，编辑态）          │   │
│  │              │                                   │   │
│  │  传文档/图片   │   [分类]──→[质检]──→[报告]         │   │
│  │  描述需求     │      ↓失败                        │   │
│  │  提修改       │   [修复]←──┘                      │   │
│  │  看元agent回复 │                                   │   │
│  │              │   选中节点 → Inspector（属性面板）   │   │
│  └──────────────┴───────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────┐   │
│  │  底部：预制件库 │ Play 按钮 │ 项目列表              │   │
│  └──────────────────────────────────────────────────┘   │
└──────────────────────┬───────────────────────────────────┘
                       │ IPC（Electron ↔ Python 后端）
┌──────────────────────▼───────────────────────────────────┐
│  Python 后端（Senza SDK，dogfooding）                      │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │  元 agent（AgentHarness + Session 持久化）          │    │
│  │                                                   │    │
│  │  · 文档理解：ingest_document（确定性解析 + vision） │    │
│  │  · 对话：理解意图，反问澄清，生成/更新 spec          │    │
│  │  · 记忆：决策记忆（SQLite）+ 文档索引（工具读取）    │    │
│  │  · 预制件推荐：根据需求推荐工具/能力/UI 组件         │    │
│  │  · spec 构建：通过工具 API 增量构建 pipeline.yaml   │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────┐     │
│  │  决策记忆     │  │  项目组装器    │  │  预制件库   │     │
│  │  (SQLite)    │  │  (spec→项目)  │  │  (注册表)   │     │
│  └──────────────┘  └──────────────┘  └────────────┘     │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │  Play 引擎    │  │  打包器       │                     │
│  │  (导出+启动)  │  │  (→可部署包)  │                     │
│  └──────────────┘  └──────────────┘                     │
└──────────────────────────────────────────────────────────┘
                       │ Play 导出
┌──────────────────────▼───────────────────────────────────┐
│  导出项目（独立可运行）                                     │
│                                                          │
│  my-agent/                                               │
│  ├── pipeline.yaml          # spec                       │
│  ├── ui_config.yaml         # UI 配置                    │
│  ├── main.py                # 入口                       │
│  ├── webui/                 # 双视图 webui               │
│  │   ├── server/            # FastAPI                    │
│  │   └── frontend/dist/     # React                      │
│  ├── tools/                 # 定制工具                   │
│  ├── pyproject.toml         # 依赖                       │
│  ├── .env.example           # API key 模板               │
│  └── README.md              # 部署说明                   │
│                                                          │
│  webui 双视图：                                           │
│  · Game 视图：用户交互（聊天/表单/表格，由 ui_config 渲染）│
│  · Scene 视图：DAG 监控 + Inspector + Console（只读）     │
│  · Play/Pause/Step 控制条                                 │
└──────────────────────────────────────────────────────────┘
```

### 三层职责

| 层 | 职责 | 技术 |
|---|---|---|
| **Electron 前端** | 对话面板 + 画布（编辑态 Scene）+ Inspector + 预制件库 + Play 按钮 | Electron + React + ReactFlow |
| **Python 后端** | 元 agent（含记忆）+ 项目组装 + 预制件注册表 + Play/打包 | Senza SDK（dogfooding：元 agent 自身是 AgentHarness） |
| **导出项目** | 完整可运行的 Agent 项目，自带双视图 webui | FastAPI + React + Senza SDK + senza-studio-components |

### 关键设计决策

1. **元 agent 用 Senza 自身构建**（dogfooding）——元 agent 是一个 `AgentHarness`，带 Session 持久化。Studio 用自己要推广的能力来构建自己。
2. **spec 是 single source of truth**——对话面板和画布都从同一个 pipeline.yaml 渲染。元 agent 更新 spec → 画布实时刷新。
3. **Play = 导出+启动**——不存在独立试跑环境。Play 组装完整项目并启动本地 webui，用户在导出项目的 webui 里测试。运行环境和部署环境是同一个项目。
4. **预制件是引用**——工具/能力组件在 spec 里引用名字，运行时和导出时从 `senza-studio-components` 包查找实现。
5. **webui 双视图**——Game 视图（用户交互）+ Scene 视图（DAG 监控 + Inspector + Console），参考 Unity 引擎的 Scene/Game 双视图模式。

---

## §3 数据模型

### 项目目录结构

每个项目是一个自包含目录：

```
~/.senza-studio/projects/<project-id>/
├── .studio/                        # Studio 管理数据
│   ├── meta.json                   # 项目元数据
│   ├── memory.sqlite3              # 决策记忆（SQLite + FTS5）
│   ├── docs/                       # 用户上传的原始文档
│   │   ├── paper.pdf
│   │   ├── flowchart.png
│   │   └── rules.xlsx
│   ├── specs/                      # spec 快照历史
│   │   └── <spec-id>/
│   │       └── pipeline.yaml       # 生成时的 spec 快照
│   └── sessions/                   # 元 agent 对话历史（Senza Session JSONL）
│       └── <session-id>.jsonl
├── pipeline.yaml                   # 当前活跃 spec
├── ui_config.yaml                  # UI 配置
├── main.py                         # 入口（Play 导出时生成）
├── webui/                          # webui（Play 导出时生成）
├── tools/                          # 定制工具（元 agent 生成）
├── pyproject.toml                  # 依赖配置
├── .env.example                    # API key 模板
└── README.md                       # 部署说明
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
  "last_played_at": null,
  "last_export_dir": null
}
```

`status` 枚举：`editing`（对话/编辑中）/ `played`（已 Play 导出）/ `exported`（已打包导出）

### pipeline.yaml（spec）

使用 Senza 原生声明式格式（与 arcgensenza 的 `stages_to_workflow` 一致）。元 agent 通过工具 API 增量构建，不直接写 YAML。

示例：

```yaml
stages:
  - name: classify
    type: agent
    prompt_template: |
      你是订单分类助手。根据订单内容分类到：退货/投诉/咨询/正常。
      订单内容：{order_content}
      输出 JSON：{"category": "退货|投诉|咨询|正常"}
    output_key: classify_result
    next_on_success: route

  - name: route
    type: checker
    tool: route_by_category
    next_on_return: return_process
    next_on_complaint: complaint_process
    next_on_normal: normal_process

  - name: return_process
    type: agent
    prompt_template: "处理退货流程：{order_content}"
    next_on_success: approval

  - name: approval
    type: checker
    tool: request_approval
    next_on_approve: notify_warehouse
    next_on_reject: notify_customer

  - name: notify_warehouse
    type: tool
    tool: send_email
    next_on_success: success

  - name: notify_customer
    type: tool
    tool: send_email
    next_on_success: success

  - name: success
    type: terminal
    message: "处理完成"
```

### ui_config.yaml

平行的 UI 描述，不进 pipeline 逻辑，只管怎么展示：

```yaml
steps:
  classify:
    display: chat              # 聊天式展示 LLM 输出
  route:
    display: status            # 只显示路由结果
  return_process:
    display: chat
  approval:
    display: approval_form     # 审批表单
    fields:
      - name: decision
        type: choice
        options: [approve, reject]
      - name: comment
        type: text
    actions: [approve, reject]
  notify_warehouse:
    display: status            # 显示发送结果
  notify_customer:
    display: status
```

`display` 类型枚举：

| 类型 | 用途 | 渲染 |
|------|------|------|
| `chat` | LLM step 的输出 | 聊天气泡，streaming |
| `status` | tool/checker 的执行结果 | 状态标记 + 详情展开 |
| `table` | 结构化结果 | 表格渲染 |
| `chart` | 数值结果 | 图表（Plotly） |
| `approval_form` | 人工审批 | 表单 + 按钮 |
| `none` | 不展示 | 无 UI |

### 设计要点

- **项目自包含**：所有数据在项目目录内，可复制/移动/分享
- **`.studio/` 隐藏目录**：管理数据与运行时代码分离
- **spec 是快照**：每次元 agent 输出都存一份到 `.studio/specs/`，可追溯演化历史
- **pipeline.yaml 和 ui_config.yaml 平行**：流程逻辑和 UI 展示分离，互不耦合

---

## §4 元 Agent 层

元 agent 是 Studio 的核心。它是一个 `AgentHarness`，用 Senza SDK 自身构建（dogfooding）。

### 4.1 元 agent 的能力

元 agent 做四件事：

1. **文档理解**：通过 `ingest_document` 工具解析用户上传的文档
2. **对话**：理解意图，反问澄清，生成/更新 spec
3. **记忆**：读写决策记忆，跨对话恢复项目上下文
4. **预制件推荐**：根据需求推荐合适的工具/能力/UI 组件

### 4.2 文档理解（多模态输入）

用户可输入论文、图表、结构化文档。通过 `ingest_document` 工具统一入口：

**策略：确定性解析为主，vision 兜底**

| 文档类型 | 解析方式 | 工具 |
|---------|---------|------|
| Excel/CSV | pandas 读取 → 结构化 JSON | `pandas.read_excel` / `read_csv` |
| PDF | 文本提取 + 图片提取 | `pypdf` / `pdfplumber` |
| 图片（流程图/架构图） | Vision 模型理解 | LLM 多模态能力 |
| 纯文本/Markdown | 直接读取 | 文件读取 |
| JSON/YAML | 直接解析 | `json` / `yaml` |

`ingest_document` 内部根据文件类型分派：
- 能确定性解析的 → 解析成结构化数据，返回给元 agent
- 不能的 → 用 vision 模型描述图片内容，返回描述文本

文档原文存 `.studio/docs/`，元 agent 后续可通过 `read_document` 工具按需读取。

### 4.3 spec 构建

元 agent 不直接写 pipeline.yaml，而是通过工具 API 增量构建。Studio 后端维护 pipeline.yaml 结构，工具调用修改它。

**元 agent 的 spec 构建工具**：

| 工具 | 说明 |
|------|------|
| `add_step(name, description, type, prompt_template)` | 添加步骤 |
| `add_edge(from, to, condition)` | 添加连线/条件分支 |
| `set_step_property(step, key, value)` | 设置步骤属性（retry、timeout 等） |
| `bind_tool(step, tool_ref)` | 给步骤绑定预制工具 |
| `set_ui_config(step, display, fields)` | 设置步骤的 UI 展示方式 |
| `get_current_spec()` | 读取当前 spec |
| `validate_spec()` | 校验 spec 完整性（entry_step 存在、edges 引用有效 step、terminal 节点可达） |
| `remove_step(name)` | 删除步骤 |
| `remove_edge(from, to, condition)` | 删除连线 |

元 agent 的 system prompt 指导它：
- 通过多轮对话理解用户想构建什么 workflow
- 每轮对话后判断信息是否足够生成 spec
- 信息不足时反问澄清（步骤数量、条件分支、工具需求、审批节点等）
- 信息充分后调用 `add_step` / `add_edge` 等工具增量构建 spec
- 优先推荐预制件，覆盖不了的场景生成定制工具

### 4.4 记忆系统

三层记忆，参考 Folumi 的 Saved Memory + History Recall 模式：

#### 记忆分层

| 层 | 内容 | 存储 | 机制 |
|---|------|------|------|
| 对话历史 | 单次对话的多轮交互 | runtime Session（`.studio/sessions/`） | Senza Session 持久化，`restore()` 恢复 |
| 决策记忆 | 项目级设计决策、业务约束、项目事实 | `.studio/memory.sqlite3` | SQLite + FTS5，参考 Folumi Saved Memory |
| 文档 | 用户上传的原始资料 | `.studio/docs/` | 文件系统，元 agent 用工具按需读取 |
| 历史检索（可选） | 跨对话搜索旧对话 | Session 检索投影 | Folumi History Recall 模式，按需开启 |

#### 决策记忆模型

参考 Folumi 的 Saved Memory，但面向项目级设计决策：

| 字段 | 用途 |
|------|------|
| `id` | 条目标识 |
| `kind` | `decision`（设计决策）/ `constraint`（业务约束）/ `fact`（项目事实） |
| `content` | 决策/约束内容 |
| `rationale` | 决策理由（引用文档段落或对话） |
| `topic_key` | 关联 spec 部分（如 `step:classify`、`edge:check_to_fix`） |
| `status` | `active` / `superseded` |
| `origin` | `user_explicit` / `agent_suggested` |
| `source_refs` | 指向文档或对话 turn |
| `revision` | CAS 令牌 |
| `created_at` / `updated_at` | 时间戳 |

SQLite 表结构：

```text
memory_items
  id, kind, content, rationale, topic_key,
  status, origin, source_refs,
  created_at, updated_at, revision

memory_relations
  from_id, relation_type, to_id
  -- 首版支持 supersedes

memory_history
  memory_id, revision, operation, prior_value, changed_at

memory_items_fts
  memory_id, content, rationale, topic_key
```

#### 决策记忆工作流

1. **新对话开始** → 元 agent 先读决策记忆（`recall_decisions` 工具），恢复项目上下文
2. **对话中做新决策** → 元 agent 写入决策记忆（`save_decision` 工具，用户确认或 agent 建议后写入）
3. **修改旧决策** → supersede 旧条目，记录新条目 + supersedes 关系
4. **spec 变更** → 决策记忆的 `topic_key` 关联到 spec 的 step/edge，变更时检查相关决策是否需要更新

#### 写入规则

参考 Folumi 的写入授权模型：

- 用户明确表达的决策/约束 → 直接写入
- 元 agent 建议的决策 → 提出后等用户确认，确认后写入
- 不得从模糊暗示中推断决策
- `supersede` 操作必须在同一 SQLite 事务中完成（旧条目标记 superseded + 新条目创建 + 关系记录）

---

## §5 预制件系统

预制件是现成的工具/UI 实现，可被 spec 引用。业务人员不需要写工具代码。

### 三层预制件

| 层 | 是什么 | 例子 | 进 spec 的方式 |
|---|---|---|---|
| **工具** | 一个 Senza `create_tool` 定义 | `db_query`、`send_email`、`pdf_extract`、`web_search` | spec 的 step 里 `tool: db_query` |
| **能力组件** | 一组工具 + workflow 片段 | "审批流"（pause + resume + 通知）、"数据清洗"（3 个 tool step 串联） | 元 agent 展开成多个 step + edge，step 里的工具仍是引用 |
| **UI 组件** | 前端渲染组件 | "表格展示"、"图表渲染"、"审批表单" | 不进 pipeline spec，进 `ui_config.yaml` |

### 引用模式

spec 里只写预制件名字，不写实现：

```yaml
- name: send_notification
  type: tool
  tool: send_email        # ← 引用 senza-studio-components 里的 send_email
  next_on_success: success
```

### 定制工具

预制件覆盖通用能力，但每个业务一定有定制工具。元 agent 优先推荐预制件，覆盖不了的场景：

- 元 agent 根据业务文档和对话，为无法用预制件覆盖的步骤生成 Python 工具实现
- 定制工具代码相对简单——通常是一个 `create_tool` 调用 + 一个 Python 函数
- 如果太复杂（如需要调用外部仿真器），标记为 stub，提示用户需要开发人员补充

### senza-studio-components 包

导出的项目依赖 `senza-studio-components` Python 包，包含：
- 所有预制工具的实现
- 所有能力组件的展开逻辑
- UI 组件的前端代码（或 npm 包）

```
senza-studio-components/
├── tools/               # 工具预制件
│   ├── db_query.py
│   ├── send_email.py
│   ├── pdf_extract.py
│   └── web_search.py
├── components/          # 能力组件
│   ├── approval_flow.py
│   └── data_pipeline.py
└── ui/                  # UI 组件
    ├── table/
    ├── chart/
    └── approval_form/
```

---

## §6 Play 与导出

### Play = 一键导出 + 本地启动

用户在 Studio 里点 Play，Studio 自动：

1. **组装项目**：spec（pipeline.yaml）+ ui_config.yaml + 预制件引用 + 定制工具 → 完整项目目录
2. **检测本机环境**：Python 版本、senza-sdk、senza-studio-components、项目专属依赖
3. **环境就绪** → 启动 webui（FastAPI + React），打开浏览器/Electron 窗口
4. **环境不全** → 提示缺失依赖，或选择打包导出

### 打包导出

本机不能直接运行时，Studio 打包完整项目：

- 轻量包：代码 + 依赖清单（目标机已有 Python + 依赖）
- 完整包：Python 解释器 + 标准库 + 依赖 + 项目代码（参考 arcgensenza 的 `pack_python.sh`）

### 导出项目结构

```
my-agent/
├── pipeline.yaml          # spec
├── ui_config.yaml         # UI 配置
├── main.py                # 入口：加载 spec → stages_to_workflow → WorkflowEngine → 运行
├── webui/                 # 双视图 webui
│   ├── server/            # FastAPI + WebSocket
│   └── frontend/dist/     # React 构建产物
├── tools/                 # 定制工具（元 agent 生成）
├── pyproject.toml         # 依赖：senza-sdk + senza-studio-components + 专属依赖
├── .env.example           # API key 模板
└── README.md              # 部署说明
```

### main.py 职责

导出的 `main.py` 做三件事：
1. 加载 `pipeline.yaml` → 调用 Senza `stages_to_workflow` 构建 WorkflowEngine
2. 启动 FastAPI webui server
3. webui 前端连接 WebSocket，实时推送 workflow 事件

不生成 Studio 相关的接入代码——导出项目是独立的，不依赖 Studio 运行时。

---

## §7 运行时交互（Unity 引擎模式）

导出项目的 webui 参考 Unity 引擎的双视图 + Inspector 模式。

### 双视图

| 视图 | 对应 Unity | 用途 | 内容 |
|------|-----------|------|------|
| **Game 视图** | Game 视图 | 用户实际交互 | 由 `ui_config.yaml` 渲染：聊天框、审批表单、结果表格等 |
| **Scene 视图** | Scene 视图 | 运行监控（只读） | DAG 节点状态高亮 + 连线 + 条件分支选中标记 |

两个视图看到的是同一个运行实例的不同渲染。用户平时用 Game 视图，出问题切 Scene 视图调试。

### Inspector

选中 Scene 视图中的节点，右侧显示该 step 的实时状态（参考 Unity Inspector）：

| 面板 | 内容 |
|------|------|
| 基本信息 | step name、type、status（pending/running/done/failed/skipped） |
| 输入 | 从 context variables 来的输入值 |
| LLM 对话 | prompt + response（如果是 agent step） |
| 工具调用 | 调用记录（tool name、args、result、耗时） |
| 输出 | structured JSON + output text |
| 指标 | 耗时、token 用量、成本 |

### 运行控制条

| 按钮 | 行为 |
|------|------|
| Play | 启动/恢复 workflow 执行 |
| Pause | 手动暂停（在任何节点之间） |
| Step | 单步执行下一个 node（调试模式） |
| Stop | 终止运行 |

workflow 的 pause/resume 机制：
- 审批节点天然 pause（`type: checker` + `tool: request_approval`）
- 用户在 Game 视图填写审批表单 → webui 调 `engine.resume()`
- 手动 Pause 可在任何 step 完成后暂停

### Console

实时日志流，按 step 分组。包含：
- step 执行日志
- 工具调用日志
- LLM 请求/响应摘要
- 错误和警告

### Scene 视图复用 Studio 画布代码

导出项目的 webui 的 Scene 视图复用 Studio 编辑器的画布组件（ReactFlow），保证视觉一致。区别：
- Studio 画布：编辑态（元 agent 可修改 spec）
- webui Scene 视图：只读态（只显示运行状态，不能编辑）

---

## §8 元 Agent 的工具集

元 agent 拥有以下工具：

### 文档工具

| 工具 | 说明 |
|------|------|
| `ingest_document(file_path)` | 解析文档（确定性解析 + vision 兜底），返回结构化内容 |
| `read_document(doc_id, section?)` | 按需读取已上传文档的原文/特定章节 |
| `list_documents()` | 列出项目已上传的文档 |

### spec 构建工具

| 工具 | 说明 |
|------|------|
| `add_step(name, description, type, prompt_template)` | 添加步骤 |
| `add_edge(from, to, condition)` | 添加连线/条件分支 |
| `set_step_property(step, key, value)` | 设置步骤属性 |
| `bind_tool(step, tool_ref)` | 绑定预制工具 |
| `set_ui_config(step, display, fields)` | 设置 UI 展示 |
| `get_current_spec()` | 读取当前 spec |
| `validate_spec()` | 校验 spec |
| `remove_step(name)` | 删除步骤 |
| `remove_edge(from, to, condition)` | 删除连线 |

### 记忆工具

| 工具 | 说明 |
|------|------|
| `recall_decisions(topic_key?)` | 检索决策记忆（可按 spec 部分过滤） |
| `save_decision(kind, content, rationale, topic_key)` | 保存决策（需用户确认或 agent 建议后写入） |
| `supersede_decision(old_id, new_content, rationale)` | 替代旧决策 |

### 预制件工具

| 工具 | 说明 |
|------|------|
| `list_prefabs(kind?)` | 列出可用预制件（工具/能力组件/UI 组件） |
| `search_prefabs(query)` | 按关键词搜索预制件 |
| `recommend_prefabs(description)` | 根据需求描述推荐预制件 |

### 定制工具生成

| 工具 | 说明 |
|------|------|
| `generate_tool(name, description, implementation_spec)` | 生成定制工具代码（元 agent 根据业务文档生成 Python 实现） |

---

## §9 前端架构

### 技术栈

Electron + React + Tailwind + ReactFlow（画布）。

### Studio 编辑器布局

```
┌──────────────────────────────────────────────────────────┐
│ 顶栏：项目名 | 模型 | Play 按钮 | 打包导出 | 设置         │
├──────────────┬───────────────────────────────────────────┤
│              │                                           │
│  对话面板     │  画布（Scene 视图，编辑态）                 │
│              │                                           │
│  消息列表     │   [分类]──→[质检]──→[报告]                │
│  (用户/agent) │      ↓失败                               │
│              │   [修复]←──┘                             │
│  streaming   │                                           │
│  输出        │   选中节点 → 右侧 Inspector               │
│              │   ┌─────────────────┐                    │
│  底部输入框   │   │ step: classify   │                    │
│  + 传文档按钮  │   │ type: agent      │                    │
│              │   │ prompt: ...       │                    │
│              │   │ tool: db_query    │                    │
│              │   └─────────────────┘                    │
├──────────────┴───────────────────────────────────────────┤
│ 底栏：预制件库 │ 状态 │ 决策记忆条数                        │
└──────────────────────────────────────────────────────────┘
```

### 导出项目 webui 布局

```
┌──────────────────────────────────────────────────────────┐
│ 顶栏：项目名 | Game/Scene 切换 | Play/Pause/Step/Stop     │
├──────────────────────────────────┬───────────────────────┤
│                                  │                       │
│  主面板（Game 或 Scene）          │  右侧面板              │
│                                  │                       │
│  Game 视图：                      │  Scene 选中节点时：    │
│  · 聊天气泡（LLM 输出）            │  · Inspector          │
│  · 审批表单                       │    (输入/输出/对话/    │
│  · 结果表格                       │     工具调用/指标)     │
│  · 输入框                         │                       │
│                                  │  Console 始终显示：    │
│  Scene 视图：                     │  · 日志流             │
│  · DAG 节点状态高亮               │                       │
│  · 条件分支选中标记               │                       │
│                                  │                       │
├──────────────────────────────────┴───────────────────────┤
│ 底栏：当前 step | token 用量 | 运行时长 | 成本             │
└──────────────────────────────────────────────────────────┘
```

### 前端状态管理

Studio 编辑器：Zustand store，状态转换：
`idle` → `conversing` → `spec_ready` → `playing` / `exported` → `conversing`（迭代）

导出项目 webui：独立 Zustand store，状态由 WebSocket 事件驱动：
`idle` → `running` → `paused` → `running` → `completed` / `failed`

---

## §10 迭代模式

用户测试后发现需要修改，回 Studio 对话修改 spec：

### 三种修改方式

1. **对话修改**（主要路径）：用户在对话面板描述修改需求 → 元 agent 读取当前 spec + 决策记忆 → 通过工具 API 增量修改 spec → 画布实时更新 → 重新 Play
2. **画布选中 + 对话**：用户在画布选中某个节点 → Inspector 显示当前属性 → 在对话面板说"把这步拆成两步" → 元 agent 修改 spec
3. **重新对话**（大改）：用户描述全新需求 → 元 agent 重新构建 spec（旧 spec 存入 `.studio/specs/` 作为快照）

### 迭代时决策记忆的作用

- 元 agent 开新对话时，先 `recall_decisions` 恢复项目上下文
- 不需要读旧对话历史就能知道"为什么这样设计"
- 修改 spec 时检查相关决策记忆是否需要更新（supersede 旧决策）
- 历史检索（如果开启）可以搜索旧对话找细节

### spec 变更与代码同步

- spec 变更后 Play 重新导出项目，覆盖旧文件
- 定制工具代码：如果 spec 引用的工具没变，不重新生成；如果新增 step 需要新工具，元 agent 生成
- 用户在导出项目里手改的代码（如定制工具实现）会在重新 Play 时被覆盖——Play 前提示"将覆盖当前项目代码"

---

## §11 错误处理与边界情况

### 元 Agent 层

| 场景 | 处理 |
|---|---|
| 元 agent LLM 调用失败 | 对话面板显示错误，对话历史保留 |
| 元 agent 输出的 spec 不合法 | `validate_spec` 失败 → 返回错误给元 agent，让它修正 |
| 元 agent 生成的定制工具语法错误 | `ast.parse` 验证 → 失败则 retry（最多 2 次），仍失败标记为 stub |
| 决策记忆 SQLite 损坏 | 从 `.studio/specs/` 的 spec 快照重建关键决策 |

### 项目运行

| 场景 | 处理 |
|---|---|
| Python 未安装 / senza-sdk 未安装 | Play 时环境检测失败，提示安装或选择打包 |
| workflow 运行时崩溃 | webui Console 显示错误，DAG 标记失败节点 |
| 审批节点超时 | workflow pause 状态保持，等待用户操作 |
| API key 未配置 | 运行时 LLM 调用失败，Console 显示错误 |
| 条件路由 LLM 输出不合规 JSON | step 标记 failed，Console 显示原始输出 |

### 迭代循环

| 场景 | 处理 |
|---|---|
| 用户手改了导出项目的代码后重新 Play | 提示"将覆盖当前项目代码"，确认后覆盖 |
| spec 与代码不同步 | 以 spec 为准，Play 重新生成所有代码 |
| 决策记忆与 spec 不同步 | spec 变更时检查相关决策记忆，提示更新 |

---

## §12 测试策略

### 核心原则

涉及 LLM 的测试用真实调用（标记 `@pytest.mark.llm`），不 mock provider。确定性逻辑用常规测试。

### Python 后端

| 模块 | 测试重点 |
|---|---|
| spec 构建工具 | add_step/add_edge/validate_spec 的纯逻辑测试（无 LLM） |
| 项目组装器 | spec + ui_config + 预制件 → 完整项目目录（无 LLM） |
| 决策记忆 | SQLite CRUD、FTS 检索、supersede 事务、CAS（无 LLM） |
| 文档解析 | 各文件类型解析正确性（无 LLM） |
| 打包器 | 轻量包 + 完整包生成（无 LLM） |

### 元 Agent 测试（真实 LLM）

- 文档理解：给真实 PDF/Excel/图片，验证 `ingest_document` 返回结构化内容
- spec 生成：给真实用户消息（如"做一个订单分类流程"），验证元 agent 调用 spec 构建工具且 `validate_spec` 通过
- 决策记忆：对话后验证决策被正确写入，新对话时 `recall_decisions` 返回正确内容
- 定制工具生成：给需要定制工具的场景，验证生成的 Python 代码 `ast.parse` 通过

### 集成测试（真实 LLM）

- 端到端：创建项目 → 对话描述需求 → 生成 spec → Play 导出 → 启动 webui → 运行 workflow → 验证事件流
- 标记 `@pytest.mark.e2e`，CI 中仅在特定标签触发

### 前端

- 组件测试（Vitest + Testing Library）：对话面板、画布渲染、Inspector
- 导出项目 webui：Game 视图组件、Scene 视图 DAG 渲染、控制条

---

## §13 技术栈总览

| 组件 | 技术 | 参考 |
|------|------|------|
| Studio 后端 | Python + Senza SDK | dogfooding |
| Studio 前端 | Electron + React + Tailwind + ReactFlow | — |
| 导出项目 webui 后端 | FastAPI + WebSocket | arcgensenza |
| 导出项目 webui 前端 | React + Tailwind + ReactFlow（复用 Studio 画布） | arcgensenza |
| spec 格式 | pipeline.yaml（Senza 原生声明式） | arcgensenza `stages_to_workflow` |
| 决策记忆 | SQLite + FTS5 | Folumi Saved Memory |
| 文档解析 | pandas + pypdf + LLM vision | — |
| 打包 | pack_python.sh 模式 | arcgensenza |
| 预制件包 | senza-studio-components（pip 包） | — |

---

## §14 参考实现

| 项目 | 参考内容 |
|------|---------|
| arcgensenza | pipeline.yaml 声明式 spec → `stages_to_workflow` 编译；webui（FastAPI + React + WebSocket + DAG）；Electron 壳；打包部署（pack_python.sh） |
| Folumi | 记忆模型（Saved Memory + History Recall）；SQLite + FTS5；写入授权 + CAS + supersede；Tauri/Electron 桌面壳 |
| senza-studio（旧） | 元 agent 架构（Converser + Coding Agent）；spec diff 概念；fd 3 帧协议（本设计不用，Play 直接导出项目） |
| Senza SDK | AgentHarness（元 agent）；WorkflowEngine（运行时）；Session 持久化；`stages_to_workflow`（spec 编译） |
