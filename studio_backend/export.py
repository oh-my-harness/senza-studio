"""把项目打包成一个不依赖 Studio 的独立目录（Phase 7 切片二）。

产物：

    <project>/exports/<slug>/
    ├── pipeline.yaml       编辑态 spec（组件保持引用，运行时再展开）
    ├── tools/              registry.py + generated/ + custom/，整个拷贝
    ├── plugins/            整个拷贝
    ├── webui/dist/         Studio 前端构建产物（有就带上，见 copy_webui）
    ├── pyproject.toml      生成：senza-sdk + runtime + components
    ├── .env.example        从 settings.SETTINGS_SCHEMA 生成
    └── README.md           生成：怎么装、怎么跑、要配什么

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


def _generate_pyproject(package_name: str, display_name: str) -> str:
    version = _locked_sdk_version()
    sdk_requirement = f"senza-sdk=={version}" if version else "senza-sdk"
    return f'''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "{package_name}"
version = "0.1.0"
description = "{display_name} — exported from Senza Studio"
requires-python = ">=3.12"
dependencies = [
    # 工作流引擎本体（PyPI 上有；版本钉成 Studio 验证过的那个）
    "{sdk_requirement}",
    # executor / judge / spec 预处理器（和 Studio 里跑的是同一份实现）
    "senza-studio-runtime",
    # 预制件工具与能力组件（spec 里按名字引用的那些）
    "senza-studio-components",
]

# 导出目录不是一个 Python 包，只是"一份依赖清单 + 一堆数据文件"。不写这一行
# 的话 setuptools 会去自动发现包，把 plugins/ 和 webui/ 当成两个顶级包，然后
# 直接报 "Multiple top-level packages discovered in a flat-layout" 装不上。
# tools/ 和 plugins/ 是运行时按路径加载的，不需要被打包。
[tool.setuptools]
packages = []
'''


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
    sdk_requirement = f"senza-sdk=={version}" if version else "senza-sdk"
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

## 安装

```bash
python -m venv .venv && source .venv/bin/activate
pip install --find-links vendor \\
  senza-studio-runtime senza-studio-components {sdk_requirement}
```

**不需要安装 Senza Studio，也不需要拿到它的源码**——这个目录拷到哪台机器都能装。

两种来源的区别：

- `senza-studio-runtime` / `senza-studio-components` 还没发布，wheel 直接放在
  `vendor/` 里，`--find-links` 就是让 pip 从那里找。
- `senza-sdk` 和 fastapi 之类的公共依赖照常从 PyPI 装，所以**安装时需要联网**
  （之后运行就不需要了）。senza-sdk 的版本钉成了 Studio 验证过的那个，免得
  引擎版本不一致导致行为和 Studio 里不一样。

## 配置

```bash
cp .env.example .env
```

按 `.env.example` 里的注释填好——至少要有模型和 API key。`.env` 里有密钥，
别提交进版本库。

## 运行

```bash
set -a && source .env && set +a
senza-studio-runtime serve pipeline.yaml --port 8000
```

`.env` 需要自己 source（`set -a` 让后面 source 进来的变量自动 export）。
这些配置是通过环境变量读的，没有额外的配置文件加载逻辑——和 Studio 那边
完全一致。

然后打开 http://127.0.0.1:8000 。界面和 Studio 里的 Play 视图一样：DAG、
step 卡片、Pause/Step、人工审批，但没有对话面板，也不能改 spec——这是一个
跑流程的项目，不是编辑器。

## 目录结构

| 路径 | 说明 |
|---|---|
| `pipeline.yaml` | 流程定义。能力组件保持引用形态，运行时才展开 |
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

    # 重复导出就整个重写。只删 exports/ 底下这一个子目录，删之前上面刚校验过
    # 它确实在 exports/ 里面。
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    (target / "pipeline.yaml").write_text(spec.to_yaml(), encoding="utf-8")
    _copy_tree(project.path / "tools", target / "tools")
    _copy_tree(project.path / "plugins", target / "plugins")

    copied_webui = False
    if webui_dist is not None and webui_dist.is_dir():
        copied_webui = _copy_tree(webui_dist, target / "webui" / "dist")

    (target / "pyproject.toml").write_text(
        _generate_pyproject(package_name, display_name), encoding="utf-8"
    )
    (target / ".env.example").write_text(_generate_env_example(), encoding="utf-8")
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
