# Blender 动画 — V0 自主动画端到端测试

> 本目录只收录演示说明。文中 `scripts/`、`prompts/`、素材及任务文件位于另行取得的 Blender 任务包，
> 不随本次文档 PR 上传；下方命令须在该任务包的实际根目录执行。

所述 Blender 任务包用于 V0 的**演示任务与证据**，不属于核心安装依赖。先完成
[核心快速开始](../v0-quickstart.md) 的 hello.txt 任务，再按本目录配置 Blender。

历史执行路径是 `/home/liyufeng/Projects/blender_animation`，仅用于对应已有证据。
新同事使用自己的目录；提交任务前核对 `TASK.md`、`prompts/`、脚本参数中的绝对路径，
把任务中的输入/输出路径替换为当前工作区，不能直接使用维护者路径。

专用依赖：Blender 可执行文件、Python 3、动画交付所需 ffmpeg/ffprobe；
下载任务另需 curl/wget、可达素材源和许可证，视觉审查另需能读取图片的模型/工具。
Windows Blender 跨 WSL 调用需要 wslpath 和文件访问权限。这些都不是 V0 hello.txt 的要求。
`preflight.sh` 只打印可执行文件检查，发现 BLOCKED 也可能返回 0，不能只凭退出码验收。

## 要验证什么

让现有 V0（Orchestrator → Coder → Reviewer）从**自主发现并合法获取 3D 模型**开始，到制作**实际动起来**的高达风格机甲动画、渲染 MP4、独立审查、修订及交付，全程尽可能不需要人类中途协调。

**不是**只验证 Python 脚本运行成功，也**不是**让 Reviewer 只看源码。Reviewer 必须独立检查实际 `.blend`、`mp4` 与抽帧证据。检测不到/看不到的质量维度必须标 `UNVERIFIED`，不得伪称 PASS。

本项目是一个**任务与证据包**，不是新的 Agent 架构；沿用 V0 已有的角色、调度及超时规则。

## 文件入口

1. `prompts/01_V0_USER_PROMPT.md` — 复制到现有 V0 的用户对话框，作为任务指令。
2. `prompts/02_REVIEWER_DISPATCH.md` — 如现有 Orchestrator 不会把审查要求完整传给 Reviewer，可并入 Reviewer 的任务描述（由 Orchestrator 派发，**不要**绕过调度）。
3. `prompts/03_CODEX_READINESS_PROMPT.md` — 可选：任务开始前用 Codex 只读检查环境和 Reviewer 工具；**不代表**先让 Codex 替 V0 做实现。
4. `prompts/04_RESUME_AFTER_TIMEOUT.md` — 仅在 V0 超时/中断后从已有文件和证据恢复任务。
5. `TASK.md` — 目标、边界、成功定义。
6. `REVIEW_CONTRACT.md` — 独立审查办法及签收/拒收标准。
7. `ASSET_POLICY.md` — 素材来源、许可证与下载限制。
8. `DELIVERY_CONTRACT.md` — 交付与证据目录。
9. `scripts/preflight.sh` — 检测运行环境。
10. `scripts/run_scene_audit.sh` — 从**交付的** `.blend` 自动产出审查报告及五张独立渲染帧；只操作内存中的场景，不覆盖项目，保留每次审查运行记录。
11. `scripts/delivery_check.py` — 独立核查资产清单、`.blend`、MP4、审查证据，并解码及抽取最终 MP4 关键帧供 Reviewer 观察。

可在 Windows 上按 [`SETUP_WINDOWS.md`](SETUP_WINDOWS.md) 解压。

## 最少操作

在 WSL 中：

```bash
cd "$HOME/v0-work/blender_animation"  # 换成实际解压目录
bash scripts/preflight.sh
# 把 prompts/01_V0_USER_PROMPT.md 的全文提交给 V0 的 Orchestrator
# V0 提交成果后，Reviewer 应运行（不得只采用 Coder 的自述）：
bash scripts/run_scene_audit.sh deliverables/final.blend
python3 scripts/delivery_check.py
```

### 注意 Blender 路径

优先使用 WSL 的 `blender`。没有时脚本会尝试 `BLENDER_BIN` 指定的可执行文件，或 Windows Blender 5.2 默认安装位置。WSL 调用 Windows Blender 时会用 `wslpath -w` 将路径变成 Windows 能识别的形式。如果本机 Blender 路径不相同：

```bash
BLENDER_BIN='/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe' bash scripts/preflight.sh
BLENDER_BIN='/mnt/c/Program Files/Blender Foundation/Blender 5.2/blender.exe' bash scripts/run_scene_audit.sh deliverables/final.blend
```

Windows 原生 Blender 读取 `\\wsl.localhost\\Ubuntu\\...` 可能受 Windows/WSL 文件访问限制；如果失败必须如实记录，而不能声称验证成功。也可以安装 WSL 原生 Blender 再验证。

## 验收原则

- 必须有**来自合法记录来源**的可打开模型；不能只把一张照片贴到平面上。
- 视频中**机甲自身必须有可见动作**（至少头部 + 一只手臂/武器动作）；只有摄像机环绕不及格。
- 目标动画约 10 秒，至少 720p、24 fps；可根据机器成本降低预览品质，但最终输出需满足指标，无法达到则报告偏差。
- `.blend` 可重新打开、关键帧可编辑，素材贴图无丢失；实际视频可解码；能看到主要动作，没有明显关节穿插、镜头裁切、材质丢失。
- Reviewer 独立打开源场景、抽取证据、检查画面与动作，按证据对照 rubric，不因 Coder 报告“PASS”即通过。
- 审查失败时回传明确缺陷、证据路径/帧号和修订建议，由现有 Orchestrator 决定如何派发。

## 不会自动发生的事情

这些文件不会自动为 V0 创建网页搜索、身份认证、GUI 视觉理解或 Blender 权限。若 Reviewer 没有看图能力，自动脚本只能验证结构和输出图片供人检查，不能替代视觉评审；应报告 `UNVERIFIED` 并上报阻塞，而不是捏造视觉 PASS。
