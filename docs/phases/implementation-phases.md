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

**状态**：已实现（checker + 审批、tool step 执行、Inspector 运行态、
按 ui.display 分类型渲染卡片、Pause/Step/Play Paused 全部落地）

---

## Phase 4: 预制件 + 能力组件

**仓库**：`senza-studio`（`senza-studio-components` 是它的子目录包，不是单独的仓库——见下方说明）

**目标**：spec 能引用预制件和能力组件，画布能看到组件 group。

**交付内容**：
- `senza-studio-components` pip 包：基础工具预制件（send_email/db_query/lookup_topic 等）+ 能力组件定义（approval_flow 等）。
  住在 `senza-studio/senza-studio-components/`，自带 pyproject.toml。**包**必须独立可安装（Phase 7 导出的项目 pip install 它就能脱离 Studio 独立运行），但**仓库**没必要拆——目前两者是同节奏开发的，同一个改动经常同时动 Studio 和预制件，拆仓库只会让这类改动没法原子提交、也没东西钉住版本对应关系。等以后真要做插件市场（§10，v1 不做）再 `git subtree split` 拆出去，带着历史一起走。
- 预处理器加组件展开：`component: approval_flow` → 查注册表 → params 填充模板 → 生成 step + edge（带 `_component` 元数据）
- 预制件工具实现：list_prefabs/search_prefabs/recommend_prefabs 返回实际内容
- Scene 视图加组件折叠/展开：`_component` 元数据 → ReactFlow group 容器
- 项目插件集加载（`<project>/plugins/`）

**验收**：
- 元 agent 推荐预制件 → spec 引用 → Play 能运行
- spec 引用能力组件 → 画布显示 group → 展开看内部 step → Play 能运行展开后的 step
- Scene 视图折叠/展开组件

**状态**：已实现（四个切片全部落地，每片单独验证）

| 切片 | 内容 | 状态 |
|---|---|---|
| 1. 工具预制件库 | senza-studio-components 包（db_query/lookup_topic/send_email）+ list/search/recommend 返回真实内容 + play.py 合并预制件与项目工具 | 已实现 |
| 2. 能力组件 + 预处理器 | approval_flow / approval_with_notice 组件定义、preprocess.py 组件展开（参数、端口、`_component` 元数据）、add_component 工具、组件感知的 validate_spec | 已实现 |
| 3. 画布组件折叠/展开 | 读切片 2 产出的 `_component` 元数据画 ReactFlow group 容器；GET /expanded_spec 让编辑态也能展开 | 已实现 |
| 4. 项目插件集加载 | `<project>/plugins/*.py` 暴露 `get_plugins()`，Play 时装进 agent step 的 harness；与 Studio 元 agent 的插件集隔离 | 已实现 |

切片 2 未竟事项：元 agent 在**真实对话**里自主选用 add_component 这一条
验收还没跑通——三次尝试都挡在 LLM 供应商 upstream 故障上（工具注册、schema、
系统提示词、中英文检索都已单独验证）。供应商恢复后补跑。

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

**状态**：已实现

实现上有一处对 roadmap 的**刻意偏离**：注册方式没有做成"往 `tools/registry.py`
里追加注册"，而是自动发现 `tools/generated/*.py` 和 `tools/custom/*.py`（各自暴露
一个 `TOOL` dict）。机器去改用户手写的 registry.py 是整个方案里最容易出事的一步，
不改它，"重新生成不覆盖手写"就从"小心翼翼保证"变成结构性成立；顺带补上了
`tools/custom/` 以前根本不会被自动加载的缺口。加载优先级：预制件 < generated/ <
custom/ < registry.py。

未跑通的验收：**元 agent 在真实对话里自主调用 generate_tool** ——LLM 供应商
（glm 中转）连续多日 `upstream error`/空响应，同 Phase 4 的 add_component 那条。
工具注册、schema、系统提示词、校验与降级路径均已单独验证，缺的只是"模型会不会
自己选它"。供应商恢复后补跑。

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

**状态**：已实现（不含图片）

**图片（vision）本阶段未做**，原因是硬的：当前钉住的 SDK 里
`AgentHarness.prompt(self, text)` 只收文本，runtime 的多模态支持（`1e4b37b`，
8/29）比钉住的 rev（`1997636`，8/28）晚一天，不在这个构建里。要做得先升 runtime
pin + 重建 wheel + 重跑 compat，是独立的一件事。上传图片会得到一句明确的"暂不
支持，等 SDK 升到支持多模态的版本"，而不是一个看不懂的解析错误。

依赖没按 roadmap 用 pandas，改用 openpyxl + 标准库 csv + pypdf：只需要"把行列读成
JSON"，pandas+numpy（~50MB）的 dataframe 能力完全用不上。

上传即解析：`POST /api/projects/{id}/documents` 存原文到 `.studio/docs/`、立刻
ingest、摘要缓存到 `.studio/ingest/`、并 `agent.rebuild()`（system prompt 的文档
清单是动态段，不重建新文档进不了模型视野）。文档清单带一行摘要，元 agent 不必先
盲调一次工具才知道文件里有什么。

未跑通的验收：**元 agent 拿着文档构建 spec** ——glm 中转连续多日 `upstream error`
/空响应，同 Phase 4 的 add_component、Phase 5 的 generate_tool。解析、上传、缓存、
system prompt 注入、read_document 均已单独验证（含真实 xlsx/csv/pdf 和浏览器实测）。

---

## Phase 7: Export 打包

**仓库**：`senza-studio`（`senza-studio-runtime` 是它的子目录包，同
`senza-studio-components`；不抽 `senza-studio-webui` npm 包，理由见下方"与原计划的
两处偏离"）

**目标**：能导出完整项目，导出项目能独立运行。

**交付内容**：
- `senza-studio-runtime` pip 包提取：executor + judge + preprocessor（从 Studio 后端代码抽出）
- 全量打包：pipeline.yaml + tools/ + plugins/ + webui/dist/ + pyproject.toml + .env.example + README.md
- 导出项目结构生成
- 导出项目能独立运行：`senza-studio-runtime serve pipeline.yaml`

**验收**：
- Studio 里构建 spec → Play 测试通过 → Export → 导出项目独立运行，行为和 Studio 里一致
- 导出项目不依赖 Studio

**状态**：已实现（四个切片全部落地）

切片 2 一开始只做了后端端点，没有任何界面入口——当时按切片描述逐条验证，
每条都过，但「用户怎么触发导出」在四条切片描述里一条都没写到，于是整个
Phase 被标成了已实现而实际上点不到。补成 2 + 2b 两行，免得以后再看不出来。

| 切片 | 内容 | 状态 |
|---|---|---|
| 1. 抽取 runtime 包 | executor/judge/模板渲染/工具与插件加载/PlaySession/预处理器搬进 `senza-studio-runtime`，接口去 Studio 化（收 root + spec dict + model + provider），**Studio 自己也改成 import 它**，不留第二份实现 | 已实现（`65b716f`） |
| 2. 导出打包（后端） | `export.py` + `POST /api/projects/{id}/export`，拷贝 tools/plugins、生成 pyproject.toml / .env.example / README.md；导出前先 validate + preprocess，spec 有问题就地拦住 | 已实现 |
| 2b. 导出按钮（前端） | 控制条上的「⬇ 导出」，成功显示落盘路径、失败显示后端给的原因（不是一串 JSON）；export 模式下不显示 | 已实现 |
| 3. serve + 前端 export 模式 | `senza-studio-runtime serve`、Play 那部分路由（project id 固定 `default`）、WS 生命周期提到 App、`/api/mode` 探测、Inspector 只读、dist 打进导出包 | 已废弃，见切片 5 |
| 4. 行为一致性验证 | 同一个 spec 两边各跑一遍，比对 step 序列、route_key、输出、终态（tests/test_export_equivalence.py，approve/reject 两条路径） | 已实现 |
| 5. 导出产物改成 Agent 本身 | 独立的 Agent 界面（`studio_frontend/agent/` → `dist-agent/`，另一次 vite build）、runtime 的接口换成产品契约（`GET /api/agent` + `WS /ws/run`）、Studio 前端里的 export 模式代码删干净 | 已实现 |
| 6. 一条命令跑起来 | 生成 `run.sh`：找 Python、建 venv、按指纹装依赖、生成并校验 `.env`、挑空闲端口、起服务并开浏览器；重新导出保留 `.env` / `.venv` | 已实现 |

切片 1 之所以对外看不出变化：它是纯重构，原有 411 个测试一个不改地全绿，
用户可见的 Export 功能在切片 2/3。切片 4 是这一阶段真正的验收，跑通了才算完。

### 切片 5：导出的应该是 agent，不是编辑器

切片 3 让导出包直接带上 Studio 的构建产物，跑起来就是一个"只读的 Studio"：
DAG、Inspector、Play / Play Paused / Stop / Pause / Step、工具调用面板，全在。
用户指出这是错的——**Studio 是引擎，导出的是作品**；Unity 导出的游戏里没有
场景编辑器、没有 Animator 面板，那些是做游戏时用的，不是玩游戏时用的。

这个错误的根源在我提问的方式：当时给的三个选项（复用 Studio dist / 抽 npm 包 /
先做 headless）全是围绕**打包方式**的，没有一条说明"复用 dist 等于把整个编辑器
一起发出去"。选项本身没有错，是问题问错了，所以答案也就只能选错。

改法：

- 新增 `studio_frontend/agent/`，一次**独立的** vite build（`vite.agent.config.ts`
  → `dist-agent/`）。不是运行时藏起来——reactflow、zustand store、Inspector /
  Canvas / ControlBar 的代码根本没打进这个包（310 kB vs Studio 的 568 kB）。
- runtime 的 HTTP 接口换成**产品契约**：`GET /api/agent` 只回渲染界面要的东西
  （入口输入、每个 step 的 `ui.display` / 展示字段 / 停下来时的选项），spec 的
  图结构一个字都不回；`WS /ws/run` 只有 start / decision / cancel 三个动词，
  pause / resume / step 是调试器的动词，产品里没有。前端因此在结构上就画不出
  DAG，而不是"画得出但我们不画"。
- `ui.display` 的分派规则和 Studio 的 Game view 完全一致（默认 chat，`none` 不
  展示）——作者在 Studio 里看到的效果就是最终用户看到的效果。
- Studio 前端里的 export 模式代码（`/api/mode` 探测、`isExport`、Inspector
  `readOnly`）全部删除：导出包已经不跑这份前端了，留着只会误导。

### 切片 6：交付物要能被跑起来，不只是能被装起来

导出目录原本要用户自己走五步（建 venv、pip install、cp .env、source、serve），
每一步都能出错，而且错的方式对第一次拿到这个目录的人毫无提示——最典型的是
key 没填，跑起来一切正常，直到第一次调模型才炸。现在是 `./run.sh` 一条。

设计上值得记的几点：

- **依赖指纹**：装完把 `requirements.txt` 的内容 + `vendor/` 里的 wheel 文件名
  哈希一下记在 `.venv/.senza-deps`。没变就整段跳过——不然"一条命令跑起来"会
  变成"一条命令等一分钟"。
- **配置检查前置**：`.env` 缺 key 时直接停下来，把缺的变量名列出来。检查的
  变量组（`SENZA_STUDIO_MODEL` / `OPENAI_MODEL` 等）和 `serve.py` 实际读的顺序
  一致，测试会校验这些 key 还在 `SETTINGS_SCHEMA` 里——改名不会悄悄留下一个
  永远检查不到的脚本。
- **重新导出保留 `.env` 和 `.venv`**：改 spec 之后重导是常规操作，每次都删掉
  等于让"一条命令"只在第一次成立。
- `requirements.txt` 和 `pyproject.toml` 从同一个依赖列表生成，测试比对两者
  一致。

一个只有真跑才会发现的坑：`say "· 建虚拟环境（$VENV）"` 里全角括号的字节会被
bash 吸进变量名，报 `VENV?: unbound variable`，脚本第 60 行就退出。注释和提示
文案全是中文，这个坑离得很近，所以加了条测试禁止裸 `$VAR` 紧跟多字节字符。
项目名注入（引号、反引号、换行）也补了测试，直接跑 `run.sh --help` 验证，
而不是读文本猜。

顺带修掉一个用真机跑才能发现的问题：`stream.py` 靠 timeout 哨兵醒来时检查后台
线程是否还活着来判断"跑完了"，间隔 5s，于是结果卡片已经显示出来了、底下按钮
还有 5.4 秒写着"取消"而不是"再来一次"。间隔改成 250ms、次数同比放大（静默预算
不变，仍是 ≈83 分钟），实测 5.4s → 0.3s。

**与原计划的偏离**（已确认）：

- **不抽 `senza-studio-webui` npm 包**。那五个组件全部深挂在 `useStudioStore`
  上（17 个字段，含 `setSpec`/`setStatus`/`ws` 这些 Studio 专有的），抽包等于把
  ~1360 行改成 props 传参。结论仍然成立，但理由变了：导出产物现在压根不复用
  那五个组件，而是另写了一套只有三件事（填输入、看进展、做决定）的界面。
- **`senza-studio-runtime` 是子目录包不是独立仓库**，沿用
  `senza-studio-components` 已经确立的先例：包独立可安装（导出项目要装它），
  仓库不拆，改动保持原子。

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

---

## 遗留事项

单独列在这里，是为了"还剩什么"这个问题能从文档里得到答案，而不是靠翻记忆和
commit log。

### 挂在 LLM 供应商上的验收（三条，各阶段内已分别记录）

| 阶段 | 没跑通的验收 |
|---|---|
| Phase 4 | 元 agent 在真实对话里自主调用 `add_component` |
| Phase 5 | 元 agent 在真实对话里自主调用 `generate_tool` |
| Phase 6 | 元 agent 拿着上传的文档构建 spec |

共同原因：`OPENAI_API_BASE` 指向的局域网网关（New API 风格）本身很快（~110ms
就返回），但它的上游一直 `upstream error: do request failed`，裸 curl 同样复现，
与 Studio 无关。三条都**不是**代码没写，而是没法验证"模型会不会自己选它"——
工具注册、schema、系统提示词、中英文检索、降级路径均已单独验证。网关恢复后
补跑即可，每条几分钟。

### Phase 6 的图片（vision）

没做。当前钉住的 SDK 里 `AgentHarness.prompt(self, text)` 只收文本，runtime 的
多模态支持（`1e4b37b`，8/29）比钉住的 rev（`1997636`，8/28）晚一天，不在这个
构建里。要做得先升 runtime pin + 重建 wheel + 重跑 compat，是独立的一件事。
现在上传图片会得到一句明确的"暂不支持，等 SDK 升级"，不是看不懂的解析错误。

### 不在本路线图内的工作

Agent Team 代理、本地 API 认证、桌面端打包（`e909d9d`、`3652f3c`、`ad207f1`、
`04da48c` 等）是独立推进的功能线，本文档没有对应阶段，状态也不由这里维护。
提一句是为了避免有人对着这份路线图以为"Phase 7 做完就全做完了"。
