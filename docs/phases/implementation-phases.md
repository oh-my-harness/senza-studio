# Senza Studio — 实现分阶段计划

> 日期：2026-08-25
> 状态：已确认
> 设计文档：`docs/senza-studio-design-v2.md`

## 分阶段原则

- 每个阶段可独立测试、可运行
- 阶段之间有清晰的依赖关系
- 最早的阶段交付最薄的端到端切片，后续阶段逐步加厚
- 先走通核心闭环，再补外围功能

## 阶段总览

```
Phase 0 (Runtime TextDelta)
  ↓
Phase 1 (Spec 构建 + 对话 + 画布)
  ↓
Phase 2 (Play 最薄切片) ← 第一个完整闭环
  ↓
Phase 3 (完整 executor + 审批)
  ↓
Phase 4 (预制件 + 能力组件) ← 可和 Phase 5/6 并行
  ↓
Phase 5 (定制工具生成)
  ↓
Phase 6 (文档理解)
  ↓
Phase 7 (Export 打包)
```

---

## Phase 0: Runtime TextDelta

**仓库**：`llm-harness-runtime`

**目标**：让 WorkflowEngine 的 `subscribe()` 事件流包含 LLM step 的 streaming text delta。

**改动**：
- `event.rs`：WorkflowEvent 加 `TextDelta { step_id, text }` 变体
- `runner.rs`：`run_llm_step` 的事件消费循环里，收到 `AgentEvent::TextDelta` 时发出 `WorkflowEvent::TextDelta`
- channel 满时 send 错误忽略，不阻塞

**不改**：`step_progress_from`、`ExecutorCtx`、`StepExecutor` trait、channel 容量

**验收**：subscribe 能收到 TextDelta 事件；现有测试无回归

**需求文档**：`docs/phases/phase-0-textdelta-requirements.md`

**状态**：已实现

---

## Phase 1: Spec 构建 + 对话 + 画布

**仓库**：`senza-studio`

**目标**：用户能和元 agent 对话，构建 spec，画布实时显示 DAG。还不能运行 spec。

**交付内容**：

### 后端
- spec 内存 dict 数据结构 + CRUD 操作（add_step/add_edge/remove_step/remove_edge/set_step_property/get_current_spec/validate_spec）
- 元 agent AgentHarness 组装（参考 senza-agent create_agent 模式）：provider + system_prompt + strategy 插件栈 + spec 工具 + Session 持久化
- 动态 system prompt 组装（固定段 + 当前 spec 摘要动态段）
- 项目管理：创建/打开/列出项目，meta.json，pipeline.yaml 序列化
- Session 管理：多 session，打开旧 session，active_session 记录
- FastAPI web server 基础框架 + WebSocket（元 agent streaming 推给前端）

### 前端
- Electron 壳 + 本地 web server 加载
- 对话面板：消息列表 + streaming 输出 + 底部输入框
- 画布（Scene 编辑态）：ReactFlow 渲染 spec 的 DAG，节点显示 step name/type，边显示条件
- Inspector 编辑态：选中节点显示属性（name/type/prompt_template/tool/ui），可编辑
- 状态管理：Zustand store（idle → conversing → spec_ready）

### 工具集（注册到元 agent）
- spec 构建工具：add_step/add_edge/set_step_property/bind_tool/set_ui_config/get_current_spec/validate_spec/remove_step/remove_edge
- 文档工具：write_document（简单文件写入，ingest_document 在 Phase 6）
- 预制件工具：list_prefabs/search_prefabs/recommend_prefabs（先返回空列表，Phase 4 填充）
- 定制工具生成：generate_tool（先返回 stub，Phase 5 实现）

### 不做
- Play / 运行 spec
- 预制件实际内容
- 文档解析
- Export

**验收**：
- 用户创建项目 → 和元 agent 对话描述需求 → 元 agent 调用 add_step 等工具构建 spec → 画布实时显示 DAG
- 关闭项目重新打开 → spec 和 session 恢复
- 打开旧 session 继续对话
- Inspector 能编辑 step 属性，画布实时刷新

**状态**：已实现

---

## Phase 2: Play 最薄切片

**仓库**：`senza-studio` + `llm-harness-runtime`

**目标**：第一个完整闭环——对话构建 spec → Play → 看到 LLM streaming + DAG 高亮。

**交付内容**：

### 后端
- spec 预处理器（只做 type/ui 保留 + 基础校验，不含组件展开）
- executor callback（只实现 `type: agent` + `type: terminal`）
- judge callback（`next_on_*` 路由）
- `ExecutorCtx` 加 event sender 字段（让 Studio executor callback 能推送 TextDelta）
- WorkflowEngine 生命周期管理：Play 时创建，Stop 时销毁
- 事件流：engine.subscribe() → WebSocket → 前端
- editing ↔ playing 状态机

### 前端
- Game 视图：时间线渲染，chat 类型卡片（LLM streaming）
- Scene 视图运行态：DAG 节点状态高亮（pending/running/done），只读
- 控制条：Play / Stop（Pause/Step 在 Phase 3）
- playing 模式布局：对话面板变侧边栏（可折叠）
- 状态管理扩展：spec_ready → playing → editing

### runtime 改动
- `ExecutorCtx` 加 `event_tx` 字段（broadcast::Sender<WorkflowEvent>）
- `StepExecutor::execute` 的 ctx 里能拿到 sender，executor callback 内部创建的 AgentHarness 的 TextDelta 事件回流到 engine broadcast channel

**验收**：
- 用户对话构建一个纯 agent step 的 spec → 点 Play → Game 视图显示 LLM streaming 输出 + Scene 视图节点高亮
- 点 Stop 回到 editing
- 修改 spec 后重新 Play

**状态**：已实现（后端+前端全部落地，自动化测试 + WebSocket 级别端到端验证通过；
真实 LLM 输出的浏览器可视化验证尚未做——本环境没有可用的 API key/浏览器工具，
建议用户用 `dev.sh` 配真实 key 跑一遍人工确认观感）

---

## Phase 3: 完整 executor + 审批

**仓库**：`senza-studio`

**目标**：spec 能用 tool step 和 checker step，审批流程能跑通。

**交付内容**：
- executor 实现 `type: checker`（检查 context variables，没有审批结果则触发 Pause）
- executor 实现 `type: tool`（从 tools/registry.py 加载工具并执行）
- 审批 pause/resume：checker 返回未匹配 route_key → judge Pause → 前端渲染审批表单 → 用户提交写 context variable → resume
- `tools/registry.py` 加载机制（importlib，每次 Play 重新 import）
- Inspector 运行态：输入/输出/工具调用/指标
- 控制条加 Pause / Step
- Console：实时日志流
- Game 视图加 status 类型卡片（tool/checker 结果）和 approval_form 类型卡片

**验收**：
- spec 含 tool step → Play → 工具执行 → 结果显示在 Game 视图
- spec 含审批 checker step → Play → pause → 审批表单出现 → 用户 approve → resume → 路由到下一步
- Inspector 运行态显示 step 的输入/输出/工具调用
- Pause/Step 控制条工作

**状态**：待实现

---

## Phase 4: 预制件 + 能力组件

**仓库**：`senza-studio` + `senza-studio-components`（新包）

**目标**：spec 能引用预制件和能力组件，画布能看到组件 group。

**交付内容**：
- `senza-studio-components` pip 包：基础工具预制件（send_email/db_query/web_search 等）+ 能力组件定义（approval_flow 等）
- 预处理器加组件展开：`component: approval_flow` → 查注册表 → params 填充模板 → 生成 step + edge（带 `_component` 元数据）
- 预制件工具实现：list_prefabs/search_prefabs/recommend_prefabs 返回实际内容
- Scene 视图加组件折叠/展开：`_component` 元数据 → ReactFlow group 容器
- 项目插件集加载（`<project>/plugins/`）

**验收**：
- 元 agent 推荐预制件 → spec 引用 → Play 能运行
- spec 引用能力组件 → 画布显示 group → 展开看内部 step → Play 能运行展开后的 step
- Scene 视图折叠/展开组件

**状态**：待实现

---

## Phase 5: 定制工具生成

**仓库**：`senza-studio`

**目标**：元 agent 能生成定制工具代码，Play 时能加载。

**交付内容**：
- `generate_tool` 实现：元 agent 生成 Python 工具代码
- 静态验证：ast.parse → import 模块 → 调用 get_tools() → 检查 Tool name → 检查 parameters JSON Schema
- 验证失败 retry（最多 2 次），仍失败标记为 stub
- `tools/registry.py` 自动维护：generate_tool 生成文件到 `tools/generated/` + 追加注册
- `tools/generated/` 和 `tools/custom/` 目录分离

**验收**：
- 元 agent 为无法用预制件覆盖的 step 生成定制工具 → 静态验证通过 → Play 能加载并执行
- 开发者在 `tools/custom/` 手写工具 → Play 能加载
- 重新生成 `tools/generated/` 不覆盖 `tools/custom/`

**状态**：待实现

---

## Phase 6: 文档理解

**仓库**：`senza-studio`

**目标**：用户上传文档，元 agent 解析并用于构建 spec。

**交付内容**：
- `ingest_document` 实现：按文件类型分派（Excel/CSV → pandas，PDF → pypdf/pdfplumber，图片 → vision，文本 → 直接读，JSON/YAML → 解析）
- `read_document`/`list_documents` 实现
- 文档存储到 `.studio/docs/`
- 前端：对话面板加上传文档按钮

**验收**：
- 用户上传 Excel → 元 agent 解析出结构 → 用于构建 spec
- 用户上传流程图图片 → vision 模型描述 → 元 agent 据此构建 DAG
- 元 agent 通过 read_document 按需读取文档内容

**状态**：待实现

---

## Phase 7: Export 打包

**仓库**：`senza-studio` + `senza-studio-runtime`（新包）+ `senza-studio-webui`（新 npm 包）

**目标**：能导出完整项目，导出项目能独立运行。

**交付内容**：
- `senza-studio-runtime` pip 包提取：executor + judge + preprocessor（从 Studio 后端代码抽出）
- `senza-studio-webui` npm 包提取：Game/Scene/Inspector/Console/控制条 React 组件
- 全量打包：pipeline.yaml + tools/ + plugins/ + webui/dist/ + pyproject.toml + .env.example + README.md
- 导出项目结构生成
- 导出项目能独立运行：`senza-studio-runtime serve pipeline.yaml`

**验收**：
- Studio 里构建 spec → Play 测试通过 → Export → 导出项目独立运行，行为和 Studio 里一致
- 导出项目不依赖 Studio

**状态**：待实现

---

## 依赖关系与并行性

```
Phase 0 ──→ Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4 ──→ Phase 7
                                              ↘ Phase 5 ↗
                                              ↘ Phase 6 ↗
```

- Phase 0 和 Phase 1 可以并行（Phase 0 改 runtime，Phase 1 建 Studio）
- Phase 4/5/6 之间无强依赖，可以并行或调整顺序
- Phase 7 依赖前面所有阶段
