# Senza Studio

首次使用 Agent Team integration 请从 [快速开始](docs/v0-quickstart.md) 进入，包含四仓库版本、首次依赖准备、
Runtime 与 Studio 双终端启动、模型配置、最小任务和排错。[文档审查记录](docs/v0-doc-audit-20261019.md)
区分已经验证、历史证据和仍待干净环境验收的步骤。

Senza Studio 是构建和运行 AI 智能体的本地工作台。Senza 工作区支持通过聊天描述流程，
在画布中检查和修改步骤，通过 Play 运行，并导出智能体项目；执行依赖 Senza SDK。
**Agent Teams** 是同一应用中的独立工作区，提供团队、成员、聊天与 Runtime 设置界面。
团队运行于同级 `llm-harness-runtime` 仓库，Studio 后端通过本地代理连接。

Agent Team 使用受控工作流：Orchestrator 决定下一步，Runtime 负责派发、关联、
边界和工作流状态，执行成员在该边界内工作。更广泛的规划文档不等于 Studio 已实现全部目标。

## 本地网页启动

需要 Python 3.12、`uv`、Node.js/npm、Rust/Cargo 和同级 `Senza`、`llm-harness-runtime` 仓库。
先按快速开始准备虚拟环境、maturin、SDK wheel 安装包和前端依赖；
`dev.sh` 的首次分支不会补齐全部构建工具，已有 `.venv` 则会跳过 SDK 重建。

在终端 A，从本仓库根目录进入 Runtime 并启动：

```bash
cd ../llm-harness-runtime
cargo run -p llm-harness-agent-team-studio --bin agent-studio
```

等待 `STUDIO_PANEL_DESCRIPTOR=...`，保持进程运行。在终端 B，从本仓库根目录启动：

```bash
SENZA_STUDIO_AGENT_TEAM_DESCRIPTOR="$HOME/.harness/agent-team-studio/panel.json" ./dev.sh
```

若 Runtime 输出的连接描述文件路径不同，应替换示例路径。浏览器打开 `http://localhost:5173`，
后端监听 `http://127.0.0.1:7878`。`dev.sh` 不会自动设置连接描述文件变量，缺少该变量时
Agent Teams 接口返回 503。配置修改后的后端重启应安排在所有任务停止后；本次文档发布不执行重启。

Senza 工作区通过设置面板或 `SENZA_STUDIO_MODEL`、`SENZA_STUDIO_API_BASE`、
`SENZA_STUDIO_API_KEY` 配置模型，Agent Teams 使用独立的 Runtime 设置。
Studio 浏览器令牌、Runtime 描述文件令牌和模型 API 密钥不是同一种凭据。

## 仓库结构

| 路径 | 用途 |
| --- | --- |
| `studio_frontend/` | React/Vite 界面与 Electron 桌面宿主 |
| `studio_backend/` | Senza 项目、Play、导出及团队代理的 FastAPI 服务 |
| `senza-studio-components/` | Studio 与导出智能体共用的组件 |
| `senza-studio-runtime/` | Studio 与导出智能体共用的流程执行代码 |
| `docs/` | 配置、运行、设计和集成说明 |

## 进一步阅读

- [网络、代理和公司 CA](docs/v0-network.md)
- [Blender 演示说明](docs/blender-demo/README.md)：专用依赖与任务包，不是核心安装要求。
- [Senza Studio 设计](docs/senza-studio-design-v2.md)：设计内容需结合当前代码判断是否已实现。
- [团队 Runtime 接口约定](docs/agent-team-runtime-contract.md)
- [桌面宿主](docs/desktop-host.md)
- [本地接口认证](docs/local-api-auth.md)
- [桌面打包](docs/desktop-packaging.md)：不属于本次干净环境验证通过范围。
