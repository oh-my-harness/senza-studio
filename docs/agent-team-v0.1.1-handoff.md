# Agent Team V0.1.1 内部交付说明

面向内部同事的最小启动说明。V0.1.0 的 `docs/agent-team-guide.md` 仍然适用；
本文件只记录 v0.1.1 的版本链、已知限制与启动步骤。

## 正式集成版本链

| 仓库 | 分支 / Tag | SHA |
|---|---|---|
| Runtime | `main`，PR #287 → #286 squash | `154eccadce161951ddac92f1e64867a6b8073c05` |
| Senza | `main`，PR #42 squash | `4c2d4ef827640ceb708c55e6a26318bac98e6b5e` |
| Studio | PR #22 / `main` | 以 PR #22 的实际 squash commit 为准（含本文件与双 pin） |

依赖方向：Studio `packaging/agent-team-runtime.json` pin Runtime `154ecca`；
Studio `senza-sdk.lock` pin Senza `4c2d4ef`；Senza `senza-pkg/runtime.lock`
pin Runtime `154ecca`。本地 wheel 按此链构建。

已有 `agent-team-runtime-v0.1.1` tag 仍指向原始 `dcb15db`，未移动；它不包含
本次 main 集成后的完整修复。旧 Runtime/Studio tag 均不作为当前组合的源码身份。

v0.1.0 tag（Runtime `cb287af`、Studio `a92d71a`）保持不动，不要 checkout。

## 与 v0.1.0 的差异

1. **Runtime**：受控工作流新增 `POST /api/team/workflow/stop?project=`
   （此前只能拆掉整个 team 才能停止运行中的工作流）；snapshot lease
   获取失败（权限/`.pipeline` 异常等真实 IO 错误）现在会落 Escalated
   终态并在 chat 中给出结论，不再"已接受却永远无响应"。
2. **Runtime**：`StepProgress` 暴露 `TurnStart`/`CompactionStart`/
   `CompactionEnd` 事件（执行控制台可显示 turn/压缩进度）。
3. **Senza**：pysandbox 适配 runtime v0.1.1 的 `trust_profile`/`host_binds`
   字段；`runtime.lock` 对齐 Runtime v0.1.1。
4. **Studio**：聊天面板新增"停止工作流"按钮（走上面的 stop 端点）；
   双 pin 文件更新；`dev.sh` 不再误杀无关进程名字含 "vite" 的进程。

## 已知限制（V0.1.1 未解决，属预期）

- 受控工作流停止后，本次 objective 不会自动续跑；需要重新发送目标。
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

```bash
# 1. 获取三仓库并切到发布版本
git clone git@github.com:oh-my-harness/llm-harness-runtime.git
git -C llm-harness-runtime checkout 154eccadce161951ddac92f1e64867a6b8073c05
git clone git@github.com:oh-my-harness/Senza.git
git -C Senza checkout 4c2d4ef827640ceb708c55e6a26318bac98e6b5e
git clone git@github.com:oh-my-harness/senza-studio.git
git -C senza-studio checkout main  # 确认包含 PR #22；固定身份见其 squash commit

# 2. 启动 Studio（自动构建并安装 Senza wheel、记录 senza-sdk.lock）
cd senza-studio && ./dev.sh

# 3. 浏览器打开前端（dev.sh 输出的地址）→ 新建 Agent Team
#    （模板 coding-team）→ 配置 provider key → 发送目标。

# 4. 需要中途停止受控工作流时：聊天面板「停止工作流」按钮，
#    或 POST /api/team/workflow/stop?project=<team_id>。

# 5. 无模型依赖的 QA 工具自测（不调 GLM）：
cd llm-harness-runtime && cargo test -p llm-harness-agent-team -p llm-harness-agent-team-studio --lib
python3 tools/eval/offline_grader.py --help   # 见 tools/eval/README
```

注意事项：使用上表及 pin 文件中的实际 commit，不用旧 tag 替代。
已有 `.venv` 时，`dev.sh` 不会自动重建/升级 Senza；请先在已锁定的 Senza
源码中运行 `scripts/build_wheel.sh`，再将新 wheel 显式安装到 Studio 的 `.venv`。
保留原环境和数据，不通过删除现有 `.venv` 或数据根来升级。
