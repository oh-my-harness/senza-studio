"""把项目打包成一个不依赖 Studio 的独立目录（Phase 7 切片二）。

产物：

    <project>/exports/<slug>/
    ├── run.sh              生成：一条命令跑起来（建 venv + 装依赖 + 起服务）
    ├── pipeline.yaml       编辑态 spec（组件保持引用，运行时再展开）
    ├── agent.json          展示信息（名字等），给界面用
    ├── tools/              registry.py + generated/ + custom/，整个拷贝
    ├── plugins/            整个拷贝
    ├── webui/dist/         Agent 界面构建产物（studio_frontend/dist-agent）
    ├── requirements.txt    生成：run.sh 装依赖用
    ├── pyproject.toml      生成：同一份依赖清单的 pip 包形态
    ├── .env.example        从 settings.SETTINGS_SCHEMA 生成
    └── README.md           生成：怎么跑、要配什么

带的是 **Agent 界面**（studio_frontend/agent/）而不是 Studio 本身的构建产物。
导出的是做好的 agent，不是做它用的工具——DAG、Inspector、Play/Pause/Step 属于
开发期，交付物里不该有（Unity 导出的游戏里没有场景编辑器）。两者是两次独立的
vite build，编辑器的代码根本没打进这个包里。

pipeline.yaml 刻意存**编辑态**（`component:` 引用没有展开）：导出项目跑的是同
一个 preprocess_spec，而不是一份烘焙好的快照。展开逻辑以后改了，导出项目跟着
变；存展开后的结果就等于把当时的实现固化进产物里了。

`.env.example` 从 SETTINGS_SCHEMA 生成而不是手写——手写的那份必然和设置面板
问的东西对不上（面板加一项，模板忘了改，用户照着配就是少一个）。
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .preprocess import PreprocessError, preprocess_spec
from .project import Project
from .settings import SETTINGS_SCHEMA, SETTINGS_SECTIONS
from .spec import Spec, SpecError


class ExportError(Exception):
    """导出失败——spec 不合法、组件展不开、目标路径不安全等。"""


# 复制时跳过的东西：缓存、本机 venv、以及 Studio 自己的工作区
_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".venv", ".DS_Store", "*.egg-info"
)


def slugify(name: str, fallback: str = "senza-agent") -> str:
    """项目名 → 能当目录名和 pypi 包名用的 slug。

    pyproject 的 name 必须匹配 PEP 508 的字符集，而项目名经常是中文（"研究
    agent"），直接拿来用会生成一个装不上的包。所以只保留 ASCII 字母数字和
    连字符，全被过滤掉就退回 fallback——人类可读的那个名字留在 README 和
    description 里，不丢。
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    # 截断：项目名没有长度上限，而目录名有（多数文件系统 255 字节）。不截的
    # 话导出一个名字很长的项目会在 mkdir 上抛 OSError——调用方拿到的是
    # traceback 和 500，而不是一句能看懂的话。
    slug = slug[:64].strip("-")
    return slug or fallback



# senza-studio-runtime 和 senza-studio-components 没有发布到 PyPI，所以把它们
# 打成 wheel 放进 vendor/：导出目录因此能整个拷给别人，而不是只能在装了
# Studio 源码的这台机器上跑。
#
# senza-sdk **在 PyPI 上**（1.3.0），所以不 vendor 它——照常当普通依赖装就行。
# 这还顺带避开了平台问题：它是编译产物，交给 pip 去解析能拿到对方平台的
# wheel，而我们硬拷一份只会是打包这台机器的架构。
REPO_ROOT = Path(__file__).resolve().parent.parent
_VENDORED_PACKAGES = ("senza-studio-runtime", "senza-studio-components")
WHEEL_BUILD_TIMEOUT = 180


def build_vendor_wheels(target: Path) -> tuple[list[str], list[str]]:
    """把未发布的依赖打成 wheel 放进 ``<target>/vendor/``。

    返回 (成功的 wheel 文件名, 没搞定的包名)。**不抛异常**：打包失败不该让整
    个导出失败——用户照样可以拿到目录，只是得自己解决依赖，由调用方把缺了
    什么说清楚。
    """
    vendor = target / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []

    for name in _VENDORED_PACKAGES:
        source = REPO_ROOT / name
        if not source.is_dir():
            missing.append(name)
            continue
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "wheel", "--no-deps",
                 "--wheel-dir", str(vendor), str(source)],
                capture_output=True,
                timeout=WHEEL_BUILD_TIMEOUT,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            missing.append(name)

    return sorted(p.name for p in vendor.glob("*.whl")), missing


def _locked_sdk_version() -> str | None:
    """Studio 验证过的 senza-sdk 版本（senza-sdk.lock）。导出项目钉同一个版本
    ——"行为和 Studio 里一致"里也包含引擎版本一致，让对方随便装个最新的
    并不安全。"""
    lock = REPO_ROOT / "senza-sdk.lock"
    try:
        return json.loads(lock.read_text(encoding="utf-8")).get("senza_version")
    except (OSError, ValueError):
        return None


# 导出项目跑起来至少要有模型和 key。SETTINGS_SCHEMA 没有"必填"这一维（设置
# 面板里全都是选填的，因为 SMTP 那几项只有用到 send_email 才需要），所以在这里
# 单独说明；每个元组是"这几个环境变量里有一个非空就行"——和 serve.py 读环境
# 变量的顺序一致（SENZA_STUDIO_* 优先，回落到 OPENAI_*）。
# tests/test_export.py 会校验这些 key 确实还在 SETTINGS_SCHEMA 里，改名不会
# 悄悄留下一个永远检查不到的脚本。
REQUIRED_ENV_GROUPS: tuple[tuple[str, ...], ...] = (
    ("SENZA_STUDIO_MODEL", "OPENAI_MODEL"),
    ("SENZA_STUDIO_API_KEY", "OPENAI_API_KEY"),
)


def _dependencies() -> list[tuple[str, str]]:
    """(依赖, 说明)。pyproject.toml 和 requirements.txt 都从这里生成——两份
    清单各写各的，迟早会有一份漏掉新依赖，而且是"装上了但跑起来才炸"那种漏。"""
    version = _locked_sdk_version()
    return [
        (
            f"senza-sdk=={version}" if version else "senza-sdk",
            "工作流引擎本体（PyPI 上有；版本钉成 Studio 验证过的那个）",
        ),
        (
            "senza-studio-runtime",
            "executor / judge / spec 预处理器（和 Studio 里跑的是同一份实现）",
        ),
        (
            "senza-studio-components",
            "预制件工具与能力组件（spec 里按名字引用的那些）",
        ),
    ]


def _generate_requirements() -> str:
    """run.sh 装依赖用的清单。

    不用 `pip install .`：那会触发一次构建（要联网拉 setuptools、跑 build
    backend），而我们要装的只是三个依赖，没有任何本地代码需要编译。直接给
    requirements.txt 少一个会失败的环节。
    """
    lines = ["# 从 Senza Studio 导出。run.sh 会用它装依赖。", ""]
    for requirement, note in _dependencies():
        lines.append(f"# {note}")
        lines.append(requirement)
    return "\n".join(lines) + "\n"


def _generate_pyproject(package_name: str, display_name: str) -> str:
    deps = "\n".join(
        f"    # {note}\n    \"{requirement}\","
        for requirement, note in _dependencies()
    )
    return f'''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{package_name}"
version = "0.1.0"
description = "{display_name} — exported from Senza Studio"
requires-python = ">=3.12"
dependencies = [
{deps}
]

# 导出目录不是一个 Python 包，只是"一份依赖清单 + 一堆数据文件"。不写这一行
# 的话 setuptools 会去自动发现包，把 plugins/ 和 webui/ 当成两个顶级包，然后
# 直接报 "Multiple top-level packages discovered in a flat-layout" 装不上。
# tools/ 和 plugins/ 是运行时按路径加载的，不需要被打包。
[tool.setuptools]
packages = []
'''


RUN_SH_TEMPLATE = r'''#!/usr/bin/env bash
# __AGENT_NAME__ —— 一条命令跑起来。
#
#     ./run.sh
#
# 把 README 里那几步（找 Python、建 venv、装依赖、配 .env、挑端口、起服务）
# 合成一条。重复运行是廉价的：venv 和依赖只在缺了或变了的时候才重新装，第二
# 次之后基本是秒起。
#
# 这个脚本是导出时生成的，可以随便改；重新导出会覆盖掉。
set -eu

cd "$(dirname "$0")"

AGENT_NAME=__AGENT_NAME_QUOTED__
PORT=8000
PORT_EXPLICIT=0
OPEN_BROWSER=1

while [ "$#" -gt 0 ]; do
  case "$1" in
    --port) PORT="${2:-}"; PORT_EXPLICIT=1; shift 2 ;;
    --port=*) PORT="${1#*=}"; PORT_EXPLICIT=1; shift ;;
    --no-open) OPEN_BROWSER=0; shift ;;
    -h|--help)
      cat <<'USAGE'
用法: ./run.sh [--port 8000] [--no-open]

  --port N    指定端口。不指定时用 8000，被占用就自动往后找；显式指定了就
              不换（你指定端口多半是因为别的东西要连它）。
  --no-open   不自动打开浏览器。
USAGE
      exit 0 ;;
    *) printf '未知参数: %s（--help 看用法）\n' "$1" >&2; exit 2 ;;
  esac
done

say() { printf '%s\n' "$*"; }
die() { printf '\n%s\n' "$*" >&2; exit 1; }

# ── 1. 找一个够新的 Python ──────────────────────────────────────────
# 不写死 python3：系统自带的那个经常是 3.9，而 senza-sdk 要 3.12+。
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3 python; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "$PYTHON" ]; then
  die "需要 Python 3.12 或更新的版本，但 PATH 里没找到。
装好之后再跑一次这个脚本即可（macOS: brew install python@3.12）。"
fi

# ── 2. 虚拟环境 ────────────────────────────────────────────────────
VENV=".venv"
VENV_PY="$VENV/bin/python"
if [ ! -x "$VENV_PY" ]; then
  # 变量一律用 ${} 包起来：紧跟在 $VAR 后面的多字节字符（这里原来是全角
  # 括号）会被 bash 当成变量名的一部分，报 "VENV?: unbound variable"。
  say "· 建虚拟环境 ${VENV}"
  "$PYTHON" -m venv "$VENV"
fi

# ── 3. 依赖 ────────────────────────────────────────────────────────
# 装完记一个指纹（requirements.txt 的内容 + vendor 里的 wheel 文件名）。下次
# 指纹没变就整段跳过——装依赖占了首次启动的绝大部分时间，每次都装会让"一条
# 命令跑起来"变成"一条命令等一分钟"。
STAMP="$VENV/.senza-deps"
FINGERPRINT="$("$VENV_PY" - <<'FINGERPRINT_PY'
import hashlib, pathlib

digest = hashlib.sha256(pathlib.Path("requirements.txt").read_bytes())
for wheel in sorted(pathlib.Path("vendor").glob("*.whl")):
    digest.update(wheel.name.encode())
print(digest.hexdigest())
FINGERPRINT_PY
)"
NEED_INSTALL=1
if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$FINGERPRINT" ]; then
  NEED_INSTALL=0
fi
if [ "$NEED_INSTALL" = 1 ]; then
  say "· 装依赖（第一次会久一点，需要联网）"
  if [ -d vendor ]; then
    # vendor/ 里是还没发布到 PyPI 的那两个包，--find-links 让 pip 从本地找；
    # senza-sdk、fastapi 这些公共依赖照常走 PyPI。
    "$VENV_PY" -m pip install --quiet --disable-pip-version-check \
      --find-links vendor -r requirements.txt
  else
    "$VENV_PY" -m pip install --quiet --disable-pip-version-check \
      -r requirements.txt
  fi
  printf '%s\n' "$FINGERPRINT" > "$STAMP"
fi

# ── 4. 配置 ────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  say "· 已从 .env.example 生成 .env"
fi
set -a
. ./.env
set +a

MISSING=""
__REQUIRED_ENV_CHECKS__
if [ -n "$MISSING" ]; then
  printf '\n还差几项配置没填。请编辑 .env，填好这些：\n' >&2
  printf '%b' "$MISSING" >&2
  printf '填完再跑一次 ./run.sh 就行（.env 里有密钥，别提交进版本库）。\n' >&2
  exit 1
fi

# ── 5. 端口 ────────────────────────────────────────────────────────
if [ "$PORT_EXPLICIT" = 0 ]; then
  PORT="$("$VENV_PY" - "$PORT" <<'PICK_PORT_PY'
import socket, sys

first = int(sys.argv[1])
for port in range(first, first + 20):
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            continue
    print(port)
    break
else:
    sys.exit(1)
PICK_PORT_PY
)" || die "从 8000 起连续 20 个端口都被占用了。用 --port 指定一个别的。"
fi

URL="http://127.0.0.1:$PORT"

# ── 6. 起服务 ──────────────────────────────────────────────────────
if [ "$OPEN_BROWSER" = 1 ]; then
  OPENER=""
  for candidate in open xdg-open; do
    if command -v "$candidate" >/dev/null 2>&1; then
      OPENER="$candidate"
      break
    fi
  done
  if [ -n "$OPENER" ]; then
    # 等端口真的能连上再开浏览器。直接开的话多半会撞上"服务还没起来"的错误
    # 页，而且在用户手动刷新之前一直停在那儿。
    (
      if "$VENV_PY" - "$PORT" <<'WAIT_PY'
import socket, sys, time

port = int(sys.argv[1])
deadline = time.time() + 30
while time.time() < deadline:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            sys.exit(0)
    except OSError:
        time.sleep(0.2)
sys.exit(1)
WAIT_PY
      then
        "$OPENER" "$URL" >/dev/null 2>&1 || true
      fi
    ) &
  fi
fi

say ""
say "  $AGENT_NAME"
say "  $URL"
say "  Ctrl+C 停止"
say ""

exec "$VENV_PY" -m senza_studio_runtime.cli serve pipeline.yaml --port "$PORT"
'''


def _generate_run_script(display_name: str) -> str:
    """一条命令跑起来的脚本。

    导出目录本来要用户自己走五步（建 venv、pip install、cp .env、source .env、
    serve），每一步都能出错，而且错的方式对第一次拿到这个目录的人毫无提示。
    脚本把五步合成一条，并且把"还没填 key"这种最常见的情况变成一句能照着做的
    提示，而不是跑起来之后第一次调模型才炸。
    """
    checks = []
    for group in REQUIRED_ENV_GROUPS:
        # 一组里有任意一个非空就算填了——直接把它们拼起来判空，比写一串
        # -a/-o 短。
        joined = "".join("${" + key + ":-}" for key in group)
        checks.append('if [ -z "' + joined + '" ]; then')
        checks.append('  MISSING="$MISSING  ' + group[0] + '\\n"')
        checks.append("fi")
    # 项目名是用户随手输入的，别指望它单行。先压平再用：
    # - 头部那行注释里，换行会把名字的后半截顶成一行**可执行**的脚本；
    # - 启动横幅里，换行只是显示成两行，不危险但难看。
    # 引号、反引号之类交给 shlex.quote。
    safe_name = " ".join(display_name.split())
    return (
        RUN_SH_TEMPLATE.replace("__AGENT_NAME_QUOTED__", shlex.quote(safe_name))
        .replace("__AGENT_NAME__", safe_name)
        .replace("__REQUIRED_ENV_CHECKS__", "\n".join(checks))
    )


def _generate_env_example() -> str:
    """按 SETTINGS_SCHEMA 分组生成，注释直接用设置面板的分区说明。"""
    lines = [
        "# 从 Senza Studio 导出。复制成 .env 并填好下面的值。",
        "# 这些就是 Studio 设置面板里的那些项，名字一一对应。",
        "",
    ]
    seen_groups: list[str] = []
    for field in SETTINGS_SCHEMA:
        if field["group"] not in seen_groups:
            seen_groups.append(field["group"])
    for group in seen_groups:
        lines.append(f"# ── {group} ──")
        note = SETTINGS_SECTIONS.get(group)
        if note:
            lines.append(f"# {note}")
        for field in SETTINGS_SCHEMA:
            if field["group"] != group:
                continue
            # 注释单独占一行，不写成 `KEY=  # 说明`：行尾注释在各家 dotenv
            # 解析器里行为不一致，有的会把 "# 说明" 整段当成值读进去。放在
            # 上一行则所有解析器都一致。
            hint = field.get("placeholder") or ""
            label = field["label"] + (f"（{hint}）" if hint else "")
            lines.append(f"# {label}")
            if field["secret"]:
                lines.append("# 密钥，不要提交进版本库")
            lines.append(f"{field['key']}=")
        lines.append("")
    return "\n".join(lines)


def _generate_readme(
    display_name: str,
    package_name: str,
    step_count: int,
    missing_wheels: list[str] | None = None,
) -> str:
    version = _locked_sdk_version()
    sdk_requirement_version = f"senza-sdk=={version}" if version else "senza-sdk"
    missing_note = (
        ""
        if not missing_wheels
        else (
            "\n> ⚠️ 打包时没能把 "
            + "、".join(missing_wheels)
            + " 放进 vendor/，"
            "装的时候需要自己解决这几个依赖。\n"
        )
    )
    return f"""# {display_name}

从 Senza Studio 导出的独立 Agent 项目，共 {step_count} 个 step。
**不需要安装 Senza Studio 就能运行。**
{missing_note}

## 运行

```bash
./run.sh
```

就这一条。脚本会自己建虚拟环境、装依赖、生成 `.env`、挑一个空闲端口、起服务
并打开浏览器。**不需要安装 Senza Studio，也不需要拿到它的源码**——这个目录拷
到哪台机器都能跑。

第一次跑会停下来让你填配置：按提示编辑 `.env`（至少要有模型和 API key），再跑
一次 `./run.sh` 就起来了。之后每次都是秒起——依赖只在变了的时候才重装。

```
./run.sh --port 9000   # 指定端口（不指定时 8000 被占用会自动往后找）
./run.sh --no-open     # 不自动打开浏览器
```

界面上：填输入、点开始、看结果，需要人工决定时会出现选项。

界面里**没有** DAG、Inspector、Play/Pause/Step——那些是在 Studio 里做这个
agent 时用的调试工具，不属于做好的 agent 本身。它们的代码也没有打进这个
包里（Agent 界面是一次独立的构建）。要改流程、要单步调试，回 Studio 打开
项目，那才是它们的地方。

> Windows 用 Git Bash 跑 `./run.sh`；或者照下面"手动跑"那一节来。

## 手动跑

不想用脚本的话：

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install --find-links vendor -r requirements.txt
cp .env.example .env    # 然后填好里面的值
set -a && source .env && set +a
senza-studio-runtime serve pipeline.yaml --port 8000
```

两类依赖的区别：`senza-studio-runtime` / `senza-studio-components` 还没发布到
PyPI，wheel 直接放在 `vendor/` 里（`--find-links` 就是让 pip 从那里找）；
`senza-sdk`（钉成 Studio 验证过的 {sdk_requirement_version}）和 fastapi 之类
的公共依赖照常从 PyPI 装，所以**装的时候需要联网**，之后运行就不用了。

配置全部通过环境变量读，没有额外的配置文件加载逻辑——和 Studio 那边完全一致
（`set -a` 是让后面 source 进来的变量自动 export）。

## 目录结构

| 路径 | 说明 |
|---|---|
| `run.sh` | 一条命令跑起来。生成的，可以随便改；重新导出会覆盖 |
| `requirements.txt` | 依赖清单，`run.sh` 用它装 |
| `pipeline.yaml` | 流程定义。能力组件保持引用形态，运行时才展开 |
| `agent.json` | 展示信息（界面标题用的名字） |
| `tools/registry.py` | 手动注册的工具 |
| `tools/generated/` | 元 agent 生成的工具 |
| `tools/custom/` | 开发人员手写的工具（同名时覆盖 generated/） |
| `plugins/` | 项目插件集，给 agent step 的 harness 添加工具/hook |

改这些文件之后重启 `serve` 即可生效。

## 和 Studio 里的行为一致吗

一致。executor、judge、spec 预处理器都来自同一个 `senza-studio-runtime` 包，
Studio 的 Play 和这里跑的是同一份实现，不是两份拷贝。
"""


def _copy_tree(src: Path, dst: Path) -> bool:
    if not src.is_dir():
        return False
    shutil.copytree(src, dst, ignore=_IGNORE, dirs_exist_ok=True)
    return True


def export_project(
    project: Project,
    spec: Spec,
    name: str | None = None,
    webui_dist: Path | None = None,
    vendor: bool = True,
) -> tuple[Path, bool, list[str]]:
    """导出到 ``<project>/exports/<slug>/``，返回
    (目录, 是否带上了 webui, 没打进 vendor 的依赖)。

    没构建过前端不算错误——照样能导出，只是跑起来没有网页界面，由调用方
    提示用户。

    spec 由调用方传进来（而不是从 pipeline.yaml 读）——用户要导出的是他现在
    屏幕上那份，不是上次存盘的那份。

    导出前先 validate + preprocess：spec 有问题就地报错，比让用户把一个跑不起
    来的目录交给别人、再在对方机器上炸掉要好得多。
    """
    try:
        spec.validate()
    except SpecError as exc:
        raise ExportError(f"spec 不合法，先修好再导出：{exc}") from exc
    spec_dict = spec.get_current_spec()
    try:
        # 只为校验能不能展开，展开结果不写进产物——产物里存编辑态。
        preprocess_spec(spec_dict)
    except PreprocessError as exc:
        raise ExportError(f"能力组件展不开，导出的项目跑不起来：{exc}") from exc

    display_name = str(project.meta.get("name") or "senza-agent")
    package_name = slugify(name or display_name)

    exports_root = (project.path / "exports").resolve()
    target = (exports_root / package_name).resolve()
    # name 可能来自 HTTP 请求——挡住 ../ 跑出 exports/ 的情况
    if not target.is_relative_to(exports_root) or target == exports_root:
        raise ExportError(f"导出目录名不合法：{name!r}")

    # 重复导出就整个重写，但**留下用户自己的东西**：`.env`（他填的模型和
    # key）和 `.venv`（run.sh 装好的依赖，重装一次要一分多钟）。改 spec 之后
    # 重新导出是常规操作，每次都让人重填 key、重装依赖的话，"一条命令跑起来"
    # 就只有第一次成立。
    #
    # 只动 exports/ 底下这一个子目录，删之前上面刚校验过它确实在 exports/ 里。
    PRESERVED = {".env", ".venv"}
    if target.exists():
        for entry in target.iterdir():
            if entry.name in PRESERVED:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    target.mkdir(parents=True, exist_ok=True)

    (target / "pipeline.yaml").write_text(spec.to_yaml(), encoding="utf-8")
    # 人类可读的名字单独存，不塞进 pipeline.yaml——那是流程定义，不是展示
    # 元数据。界面的标题和浏览器标签页用它。
    (target / "agent.json").write_text(
        json.dumps({"name": display_name}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _copy_tree(project.path / "tools", target / "tools")
    _copy_tree(project.path / "plugins", target / "plugins")

    copied_webui = False
    if webui_dist is not None and webui_dist.is_dir():
        copied_webui = _copy_tree(webui_dist, target / "webui" / "dist")

    (target / "pyproject.toml").write_text(
        _generate_pyproject(package_name, display_name), encoding="utf-8"
    )
    (target / "requirements.txt").write_text(_generate_requirements(), encoding="utf-8")
    (target / ".env.example").write_text(_generate_env_example(), encoding="utf-8")
    run_script = target / "run.sh"
    run_script.write_text(_generate_run_script(display_name), encoding="utf-8")
    # 不给执行位的话用户得先 chmod 或者记得写 `bash run.sh`——那就又变成两步了
    run_script.chmod(0o755)
    missing_wheels: list[str] = []
    if vendor:
        _, missing_wheels = build_vendor_wheels(target)

    (target / "README.md").write_text(
        _generate_readme(
            display_name,
            package_name,
            len(spec_dict.get("stages", [])),
            missing_wheels,
        ),
        encoding="utf-8",
    )

    project.meta["last_export_dir"] = str(target)
    project.meta["last_exported_at"] = datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    project._save_meta()

    return target, copied_webui, missing_wheels
