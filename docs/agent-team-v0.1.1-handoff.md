# Agent Team V0.1.1 内部交付说明

面向内部同事的最小启动说明。V0.1.0 的 `docs/agent-team-guide.md` 仍然适用；
本文件只记录 v0.1.1 的版本链、已知限制与启动步骤。

## 版本链（全部已推送远端，main 未动）

| 仓库 | 分支 / Tag | SHA |
|---|---|---|
| Runtime | `feat/agentic-coding-team/v0.1.1` / `agent-team-runtime-v0.1.1` | `dcb15db9e42e3a66ddc98792b7de116e8de7ed57` |
| Senza | `feat/v0.1.1-release`（无 tag，commit A 即构建身份） | `f10efec71cb3e8d7311e6226edbcd8ebe75ef587` |
| Studio | `feat/agent-team/v0.1.1` / `agent-team-studio-v0.1.1` | 见 tag（含本文件与双 pin） |

依赖方向：Studio `packaging/agent-team-runtime.json` pin Runtime `dcb15db`；
Studio `senza-sdk.lock` pin Senza `f10efec`；Senza `senza-pkg/runtime.lock`
pin Runtime `dcb15db`。三者互相校验，`dev.sh` 会按此链构建。

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
- 不合并 GitHub main；main 与 feature 分支的关系见 v0.1.0 审计报告。

## 同事启动步骤（WSL/Linux）

```bash
# 1. 获取三仓库并切到发布版本
git clone git@github.com:oh-my-harness/llm-harness-runtime.git
git -C llm-harness-runtime checkout agent-team-runtime-v0.1.1   # tag 推送后
git clone git@github.com:oh-my-harness/Senza.git
git -C Senza checkout feat/v0.1.1-release        # commit A = f10efec
git clone git@github.com:oh-my-harness/senza-studio.git
git -C senza-studio checkout agent-team-studio-v0.1.1           # tag 推送后

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

注意事项：Runtime 必须用 tag 对应的 commit（Studio 按
`packaging/agent-team-runtime.json` 校验）；Senza 必须在
`feat/v0.1.1-release` 分支上（其 `senza-pkg/runtime.lock` 指向 Runtime
v0.1.1），不要用 main——main 的 sandbox 结构对不上。
