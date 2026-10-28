# Agent Team integration 快速开始（WSL / Linux，2026-10-19 核对）

目标：从空目录安装，在 Senza Studio 的 **Agent Teams** 中创建团队并完成一次小任务。
入口为 Runtime 的 `agent-studio` 加 Studio 的 `dev.sh`，不是仅运行 `dev.sh`。
这是源码开发启动路径；原生 Windows/Electron 安装包不在本轮首次安装验证范围内。

## 1. 仓库及构建身份

下表和检出命令保留上一轮本机审查的可复现基线，不等于当前远端审查分支已验收。
当前审查候选及其历史依赖版本见[审查记录](v0-doc-audit-20261019.md#当前远端审查候选)。
本轮文档提交不更改任何依赖固定版本，也不将候选分支标为已发布。

四个核心仓库都属于本次审查范围。前三个同级放置，目录名大小写如下；适配器由 Cargo 自动获取，不必手工克隆。

| 仓库 | 本次核对的提交 | 作用 |
| --- | --- | --- |
| `llm-harness-runtime` | `dcb15db9e42e3a66ddc98792b7de116e8de7ed57` | 团队、模型请求、工具、受控工作流 |
| `Senza` | `f10efec71cb3e8d7311e6226edbcd8ebe75ef587` | Studio 所用 Python SDK，构建 wheel 安装包 |
| `senza-studio` | `741a5a193d3b80b5fbb17bf287eb0f1b0dfdfcba` | 浏览器前端、后端代理 |
| `llm-api-adapter` | `864050882254e12cbda33359debae40a03a4b35f` | Runtime 锁定的 Rust HTTP／模型适配器 |

需具备这些 GitHub 仓库的读取权限。可按组织认证方式把 HTTPS 换成 SSH。

```bash
mkdir -p "$HOME/v0-work"
cd "$HOME/v0-work"
git clone https://github.com/oh-my-harness/llm-harness-runtime.git
git clone https://github.com/oh-my-harness/Senza.git
git clone https://github.com/oh-my-harness/senza-studio.git
git -C llm-harness-runtime checkout dcb15db9e42e3a66ddc98792b7de116e8de7ed57
git -C Senza checkout f10efec71cb3e8d7311e6226edbcd8ebe75ef587
git -C senza-studio checkout 741a5a193d3b80b5fbb17bf287eb0f1b0dfdfcba
```

`packaging/agent-team-runtime.json` 和 `senza-sdk.lock` 是 Studio 的固定版本，
`Senza/senza-pkg/runtime.lock` 指向同一 Runtime。Runtime `Cargo.toml` 和
`Cargo.lock` 锁适配器。不要把四仓库各自的最新 main 混装，也不需要保留维护者的
`*-v0-integration`、`studio-v011-clean-integration` 等临时工作树。
上面是代码验证基线；本说明随当前 Agent Team integration 审查 PR 提交，应连同说明使用，不能用各仓库当前默认分支替代这些固定提交。

## 2. 一次性准备

以 Ubuntu 24.04 / WSL Ubuntu 为操作示例。需要 Bash、Git、curl、C/C++ 编译和链接工具、
pkg-config、CA、Python 3.12（含虚拟环境、开发库）、uv、Rust/Cargo、Node.js/npm、Perl、lsof、procps。
Rust 代码使用 edition 2024；当前核对机是 Rust 1.98.1、Node 22.22.1、uv 0.12.13，
没有声明或验证更低的完整工具链下限。已有合适版本时无需重装。

```bash
sudo apt-get update
sudo apt-get install -y build-essential pkg-config git curl ca-certificates \
  python3.12 python3.12-venv python3.12-dev perl lsof procps
# 已装好的工具可直接确认版本：
cargo --version
rustc --version
node --version
npm --version
uv --version
python3.12 --version
```

缺少 Rust/uv 时，可按 [Rust 官方安装](https://rust-lang.org/tools/install/) 和
[uv 官方安装](https://docs.astral.sh/uv/getting-started/installation/) 在 WSL 内执行：

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
source "$HOME/.cargo/env"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

Node/npm 使用 [Node 官方下载页](https://nodejs.org/en/download) 选择 Node 22、Linux 及本机架构，
按其安装说明安装到 WSL（不是仅在 Windows 安装）。如组织提供内部安装源，以组织方式为准。
安装后重新执行版本检查；本次只核对官方安装指引，未在空系统执行这些安装器。

若没有上述包，先确认 Ubuntu 发行版及软件源。下载依赖需要访问 GitHub、Cargo 软件包仓库、
Python 包源及 npm；内网代理/CA 按[网络配置说明](v0-network.md)选择设置。
Git 检出、构建、运行全部在 WSL 内完成；Windows 浏览器打开前端。

**首次显式准备 Python 环境**（当前脚本所需，不能省略成一句“运行 dev.sh”）：

```bash
cd "$HOME/v0-work/senza-studio"
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install 'maturin>=1.7,<2' fastapi uvicorn pydantic pyyaml websockets
# 共用此 venv，绕过 Senza _venv.sh 仅默认探测 macOS 路径的问题：
(cd ../Senza && VENV="$VIRTUAL_ENV" ./scripts/build_wheel.sh)
uv pip install ../Senza/dist/senza_sdk-*.whl
uv pip install -e ./senza-studio-components -e ./senza-studio-runtime
python -c "import importlib.metadata as m; print(m.version('senza-sdk'))"
# 预期 1.4.0
cd studio_frontend
npm ci
cd ..
```

仅适用于新环境，已有 `.venv` 不要盲目覆盖。构建 wheel 安装包必须走
`Senza/scripts/build_wheel.sh`，它从 runtime.lock 替换 Cargo.toml 的 PLACEHOLDER 后还原。
直接 `pip install -e ../Senza` 会绕过该步骤。
`dev.sh` 只有在 `.venv` 不存在时才构建 SDK，已有目录会跳过；切换版本后需显式重新构建安装。
其首次分支也会重写 `senza-sdk.lock`，不能把“版本锁定文件被重写”视为版本正确的证据。
本路径预先安装依赖，保留仓库固定版本。

## 3. 启动：两个终端

终端 A：

```bash
cd "$HOME/v0-work/llm-harness-runtime"
cargo build --locked -p llm-harness-agent-team-studio --bin agent-studio
cargo run --locked -p llm-harness-agent-team-studio --bin agent-studio
```

等待 `STUDIO_PANEL_DESCRIPTOR=.../panel.json`。默认数据根为
`$HOME/.harness/agent-team-studio`；可在启动前 `export STUDIO_DATA_ROOT=...` 使用独立目录。
端口默认随机分配，`STUDIO_PORT` 优先于兼容变量 `CT_PORT`；连接描述文件是权威地址。
另一入口 `./scripts/studio.sh` 会按发布模式构建并打印 `agent-team-studio ready: <descriptor>`；
脚本用 `PORT` 指定端口，勿与直接运行可执行文件的变量混淆。

终端 B：

```bash
cd "$HOME/v0-work/senza-studio"
SENZA_STUDIO_AGENT_TEAM_DESCRIPTOR="$HOME/.harness/agent-team-studio/panel.json" ./dev.sh
```

若 A 的连接描述文件不同，替换 B 的路径。打开 `http://localhost:5173`，后端为
`http://127.0.0.1:7878`；`curl --fail http://127.0.0.1:7878/api/health` 应成功。
`dev.sh` 会清理 7878/5173 的占用进程、匹配的 Studio 后端和 Vite 进程；共享机器先确认没有其他开发服务。
不要在已有业务任务的机器上重新运行它做安装验证。

连接描述文件包含私有 Runtime Bearer 令牌，不要复制到文档或聊天。
Studio 自己生成的浏览器 API 令牌与 Runtime 令牌、模型 API 密钥是三种不同凭据。
不设置连接描述文件时 Senza 工作台仍可启动，但 Agent Teams 会 503。
更改连接描述文件配置后需要重启 Studio 后端。

## 4. 配模型，再建团队

选择 **Agent Teams** 的全局设置（齿轮），填写 strong / main / cheap 三档模型 ID、
兼容 OpenAI 协议的 **基础地址（Base URL）** 和 API 密钥。第一次可将三档都设为同一个已获准使用、
支持流式响应和工具调用的模型。`GLM-5.3-Flash` 是本机历史验证值，不是所有人的默认要求。

基础地址（Base URL） 是服务根地址，例如组织提供的 `https://gateway.example.com`；当前适配器会追加
`/v1/chat/completions`，不要填写完整接口或再加 `/v1`。具体协议、域名和密钥向团队获取，
不要照抄本机诊断中的 HTTP 地址。留空会走官方 OpenAI 默认地址。

| 配置面 | 生效规则 |
| --- | --- |
| Agent Teams 模型 | 成员 `provider_override.model`（非空）优先，否则成员的模型引用解析全局三档；固定模型 ID 必须有对应模型客户端 |
| Agent Teams 密钥 | 成员私有密钥（非空）优先，否则 Runtime 数据根下全局密钥文件 |
| Agent Teams 基础地址（Base URL） | 成员覆盖配置若存在则使用（空串表示官方地址），否则 Runtime `settings.json` 的 `base_url` |
| Agent Teams 环境变量 | 不用 `SENZA_STUDIO_MODEL/API_BASE/API_KEY` 配团队；`OPENAI_MODEL/API_KEY` 也不是此入口的团队配置来源。启动时 `OPENAI_API_BASE` 只参与旧模型客户端工厂后备路径，不应作为替代面板的配置方法 |
| Senza 工作台（另一模式） | 每项显式 `SENZA_STUDIO_MODEL/API_BASE/API_KEY` > `$SENZA_STUDIO_HOME/settings.json`（默认 `~/.senza-studio`）> 对应 `OPENAI_*` > 默认值；模型默认 deepseek-chat。显式环境项在面板只读 |

Runtime 设置存入 `STUDIO_DATA_ROOT/settings.json`，全局密钥单独存入 `STUDIO_DATA_ROOT/apikey`；
成员配置存入 `teams/<id>/team.json`，成员密钥存入 `teams/<id>/secrets/<agent-id>`。保存全局设置只影响后续创建/重建的团队，
不会更新已运行团队的模型客户端；先等待任务停止，再重启团队，或在成员设置中修改并重建。
角色设定可热更新，成员模型、密钥或基础地址 改动会重建执行环境。

创建一个可丢弃的小工作区：

```bash
mkdir -p "$HOME/v0-work/smoke-workspace"
git -C "$HOME/v0-work/smoke-workspace" init
printf '# V0 smoke\n' > "$HOME/v0-work/smoke-workspace/README.md"
```

新建团队：ID `v0-smoke`、模板 `coding-team`、工作区填写上面目录的**实际绝对 Linux 路径**
（`printf '%s\n' "$HOME/v0-work/smoke-workspace"` 查看）。确认 UI 针对此目录的访问授权。
不要原样输入 `$HOME`、`~`、维护者 `/home/liyufeng/...` 或 Windows `C:\...`。
空白团队没有成员，工作区留空会使用数据目录兜底，都不适合作为这次首次任务路径。
创建后应有 orchestrator、coder、reviewer 三个成员。

**已有团队/导入**：当前 UI 没有通用“上传团队 JSON”入口。
自定义模板放到 `<STUDIO_DATA_ROOT>/templates/<template-id>/team.json`，包含 id/version/name/members，
persona_file 相对该模板目录；格式参照 Runtime 的 `templates/coding-team`，同 ID 会覆盖内置模板。
再在模板列表中创建新实例。迁移已保存实例须在双方 Runtime 停止时备份/复制数据根，
校正team.json 中机器相关路径、重新检查工作区授权和私有密钥权限；新机不会自动拥有旧机目录。
首次使用建议内置模板；模板导入和跨机迁移尚未做干净环境实测。

## 5. 最小任务、观察和停止

在团队群聊提交一次：

> 请让 Coder 在工作区创建 hello.txt，内容只有 V0_OK 和换行；让 Reviewer 独立读取验证。
> 完成后报告文件路径和验证结果。不安装额外依赖，不提交、不推送。

验收：出现用户消息、Orchestrator 决策、Coder 派发/结果、Reviewer 派发/结果、最终工作流结论；
本地 `cat "$HOME/v0-work/smoke-workspace/hello.txt"` 为 `V0_OK`。
收到 `202`／`workflow_id` 或普通模型回复文本只代表受理/过程，不代表完成。
受控 coding-team 的普通聊天无论选择群聊还是成员，均经 Orchestrator 入口；
不要把点击 coder 私聊当成绕过工作流的消息测试。泛用 P2P SDK 的委派示例是另一模式。

要提前结束，点击 **停止工作流**，等待停止终态和成员静止，保留文件及证据。
API 为 `POST /api/team/workflow/stop?project=v0-smoke`（通过已认证的运行入口调用）。
“打断 Agent”不是完整工作流停止的替代；停止后不会自动续跑，重新发目标是一个新运行。
全部任务完成后，先在 B 按 Ctrl+C 停 Studio，再在 A 按 Ctrl+C 正常退出 Runtime。
正常退出删除连接描述文件，但团队数据保留，下次启动会恢复；不要用删除团队来代替停止。

## 6. 排错与验证边界

| 现象 | 检查/处理 |
| --- | --- |
| PLACEHOLDER / 找不到 maturin / no linkable Python | 重看第 2 节；显式 VENV、安装 maturin；独立 Senza 构建可指定 BASE_PYTHON 的实际 3.12 路径 |
| SDK 固定版本不符 / 沙箱字段编译错误 | 核对四仓库提交、三个固定版本和已安装 wheel 安装包；不要直接改版本锁定文件掩盖漂移；PyPI 1.3.0 不是本说明的 git 1.4.0 构建链 |
| 503 Agent Teams | Runtime 是否就绪；连接描述文件路径及读取权限；后端是否带变量启动 |
| 401 / WS 断开 | 刷新前端，核对是否连接当前进程的 连接描述文件／浏览器令牌；不要把模型密钥当本地令牌 |
| 单例锁冲突 | 同数据根已有 Runtime；使用独立 STUDIO_DATA_ROOT 或等待原实例退出 |
| workspace unauthorized / 启动降级 | 确认目录存在、授权准确，检查 `/api/team/startup` 和 UI 恢复横幅；不要直接复制别人的授权记录 |
| 404 模型请求 | 基础地址（Base URL） 是否误加 `/v1`，组织网关是否支持当前固定聊天路径 |
| 502 / 空 `server error` / TLS | 见网络说明，区分代理/直连与 CA；保存时间、HTTP 状态、运行／工作流 ID，不能从空正文断言模型或工具不兼容 |
| 一直运行 / 409 | 先看现有工作流，不要重复提交；停止并等终态，再处理密钥、权限、模型或网络 |
| .pipeline / 存储租约错误 | 检查工作区写权限、磁盘和并发使用；Agent Team integration 会报告 Escalated 终态（离线回归验证；真实任务未复验），修复后显式发送新目标 |

诊断文件在 Runtime 数据根：`logs/runtime.jsonl`（生命周期）、`logs/crash.jsonl`（panic）、
`teams/<id>/chat.sqlite3`、成员会话／快照。不是所有上游 HTTP 细节都会保留；共享日志前去除令牌、密钥和任务内容。

本次验证记录与剩余限制见[审查记录](v0-doc-audit-20261019.md)。
Blender、ffmpeg、素材下载/许可证、看图模型、Windows Blender 路径只属于演示依赖，
不需要为这个最小任务安装。浏览器工作台不要求 Blender、Docker 或 Firecracker。

Blender 的专用依赖、外部任务包和跨系统路径见 [Blender 演示说明](blender-demo/README.md)。
