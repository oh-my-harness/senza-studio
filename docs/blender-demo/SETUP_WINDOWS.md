# Blender 演示包：Windows / WSL 安装

> 本目录只收录演示说明。文中 `scripts/`、`prompts/`、素材及任务文件位于另行取得的 Blender 任务包，
> 不随本次文档 PR 上传；下方命令须在该任务包的实际根目录执行。

这是 Blender 动画演示的任务包配置，不是 V0 核心安装步骤。
先跟随 [V0 快速开始](../v0-quickstart.md) 跑通 hello.txt。
ZIP 文件需要另行取得；本仓库文档不提供下载凭据，也不保证该 ZIP 已在 Downloads。

在 PowerShell 中将发行版名、Linux 用户名和 ZIP 文件名换成自己的值：

```powershell
$zip = Join-Path $env:USERPROFILE 'Downloads\blender_animation_v0_starter.zip'
# 在 WSL 运行 whoami 查看 Linux 用户名；wsl -l -q 查看发行版名。
$distro = 'Ubuntu'
$linuxUser = 'your-linux-user'
$dest = "\\wsl.localhost\$distro\home\$linuxUser\v0-work\blender_animation"
New-Item -ItemType Directory -Force -Path $dest | Out-Null
Expand-Archive -LiteralPath $zip -DestinationPath $dest -Force
```

ZIP 文件应直接从顶层展开到此目录；如果 ZIP 自带一层目录，先核对实际结构。
然后在对应 WSL 终端执行：

```bash
cd "$HOME/v0-work/blender_animation"
bash scripts/preflight.sh
cat prompts/01_V0_USER_PROMPT.md
```

先检查预检输出中的 `MISSING`／`BLOCKED`，再配置 Blender/ffmpeg/ffprobe、模型看图与素材权限。
若 Blender 装在 Windows，按 README 设置实际的 BLENDER_BIN；不能假定所有人都安装 Blender 5.2 默认路径。

任务文本和历史证据中的 `/home/liyufeng/...` 是旧机路径。提交前将任务中输入与输出路径改为
当前工作区实际路径，在 Agent Teams 创建团队时授权该目录。WSL Runtime 使用 `/home/<user>/...`，
不要给它 Windows 的 `C:\...` 路径。检查无误后才把任务文本提交到 V0 Orchestrator；
不要把它作为安装测试重复提交到已有运行中的 Blender 团队。

首次新 Windows/WSL 解压、Blender 跨系统文件访问和最终动画未在本次文档审查中重验。
