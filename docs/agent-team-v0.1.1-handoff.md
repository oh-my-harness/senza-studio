# Agent Team V0.1.1 内部交付说明

面向内部同事的 V0.1.1 交付记录。首次使用统一从 [快速开始](v0-quickstart.md) 进入；
Runtime 的 `docs/agent-team-guide.md` 同时包含通用 P2P SDK 示例，不能直接当作受控 V0 操作步骤。

## 历史集成版本链（当前已回退，候选仍待审查）

下表描述此前集成时的身份，不代表当前 main 已包含 V0。现有审查候选为 Runtime #290
（依赖基础审查 #289）、Senza #44、Studio #24；固定版本保持原样，不在本次文档提交中调整。
完整提交身份及历史实测基线见[审查记录](v0-doc-audit-20261019.md#当前远端审查候选)。

| 仓库 | 分支 / Tag | SHA |
|---|---|---|
| Runtime | `main`，PR #287 → #286 squash | `154eccadce161951ddac92f1e64867a6b8073c05` |
| Senza | `main`，PR #42 squash | `4c2d4ef827640ceb708c55e6a26318bac98e6b5e` |
| Studio | PR #22 / `main` | 以 PR #22 的实际 squash commit 为准（含本文件与双 pin） |

依赖方向：Studio `packaging/agent-team-runtime.json` pin Runtime `154ecca`；
Studio `senza-sdk.lock` pin Senza `4c2d4ef`；Senza `senza-pkg/runtime.lock`
pin Runtime `154ecca`。本地 wheel 安装包按此链构建。`dev.sh` 不启动 Runtime，也不会在已有 `.venv` 时重建 SDK。
Runtime 还固定依赖适配器提交 `864050882254e12cbda33359debae40a03a4b35f`。

已有 `agent-team-runtime-v0.1.1` tag 仍指向原始 `dcb15db`，未移动；它不包含
当时 main 集成后的完整修复。旧 Runtime/Studio tag 均不作为当前组合的源码身份。

v0.1.0 tag（Runtime `cb287af`、Studio `a92d71a`）保持不动，不要 checkout。

## 与 v0.1.0 的差异

1. **Runtime**：受控工作流新增 `POST /api/team/workflow/stop?project=`
   （此前只能拆掉整个 team 才能停止运行中的工作流）；快照存储租约
   获取失败（权限/`.pipeline` 异常等真实 IO 错误）现在会落 Escalated
   终态并在 chat 中给出结论，不再"已接受却永远无响应"。
2. **Runtime**：`StepProgress` 暴露 `TurnStart`/`CompactionStart`/
   `CompactionEnd` 事件（执行控制台可显示 turn/压缩进度）。
3. **Senza**：Python 沙箱适配 runtime v0.1.1 的 `trust_profile`/`host_binds`
   字段；`runtime.lock` 对齐 Runtime v0.1.1。
4. **Studio**：聊天面板新增"停止工作流"按钮（走上面的 stop 端点）；
   双 pin 文件更新；`dev.sh` 不再误杀无关进程名字含 "vite" 的进程。

## 已知限制（V0.1.1 未解决，属预期）

- 受控工作流停止后，本次任务目标 不会自动续跑；需要重新发送目标。
- `packaging/desktop-python.in` 的 PyPI `senza-sdk==1.3.0` 通道与
  `senza-sdk.lock`（1.4.0 语义、git 构建）是两条链；内部交付统一走
  `./dev.sh` 的本地 wheel 路径，desktop-python 打包链未在本轮验证。
- Runtime `agent-team-runtime-v0.1.0` tag 内含少量研究材料
  （`configs/research/*`、`tools/experiments/*`、`docs/e2e-evals/runs/*`
  中的个人绝对路径），不影响使用，V0.1.x 再清理。
- 正式范围为 WSL/Linux Coding Team Runtime、本地 Senza wheel 和 Studio
  `dev.sh` 开发运行链；不承诺原生 Windows/macOS、Novel V1、公开安装包或生产部署。
- `USER_MANUAL_SMOKE_PENDING`：真实模型三角色协作由用户稍后在 Web UI 验收；
  本地 mock、真实 Bwrap 和基本 Team 创建验证不等于真实模型闭环通过。
- 已披露的范围外 CI 失败仍然存在，未关闭检查，也未因此发布 PyPI 包。

## 同事启动步骤（WSL/Linux）

跟随 [V0 快速开始](v0-quickstart.md) 完成完整路径：

1. 获取同级 Runtime、Senza、Studio，检出记录的完整提交；适配器由 Cargo 获取。
2. 显式准备 Python 3.12 虚拟环境、maturin 和 SDK wheel 安装包、前端 npm 依赖。
3. 终端 A 在 Runtime 执行 `cargo run --locked -p llm-harness-agent-team-studio --bin agent-studio`，等待连接描述文件。
4. 终端 B 在 Studio 设置 `SENZA_STUDIO_AGENT_TEAM_DESCRIPTOR` 为实际连接描述文件路径再运行 `./dev.sh`。
5. Agent Teams 全局设置中配置模型三档、基础地址（Base URL） 和密钥，再创建 coding-team、授权工作区，跑 hello.txt 最小任务。
6. 中止使用“停止工作流”；正常退出先停 Studio，再停 Runtime。

`SENZA_STUDIO_MODEL/API_BASE/API_KEY` 是另一 Senza 工作台的设置，不是 Agent Teams 的团队模型配置。
本机按域名绕过代理只在指定启动封装脚本生效，不是全员要求；见 [网络说明](v0-network.md)。

无模型依赖的质量检查（从 Runtime 根运行）：

```bash
cargo test -p llm-harness-agent-team -p llm-harness-agent-team-studio --lib
python3 tools/eval/offline_grader.py --help
```

验证范围和新环境尚待验收项目见 [本次审查记录](v0-doc-audit-20261019.md)。
构建身份以提交为准，不要求 Senza 必须处于某个分支名称。
