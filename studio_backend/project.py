"""项目管理：创建/打开/列出项目，meta.json 维护。"""
from __future__ import annotations

import copy
import json
import secrets
import shutil
import sys
import time
from pathlib import Path

import yaml

from .config import StudioConfig
from .spec import Spec, SpecError
from .storage import atomic_write_text


class ProjectDataError(Exception):
    """项目文件存在但内容损坏/不可解析；绝不自动重建用户数据。"""


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _gen_id(prefix: str = "proj") -> str:
    # 时间戳(毫秒) + 6 位随机后缀，避免同一毫秒内创建多个项目时 ID 碰撞
    return f"{prefix}-{int(time.time() * 1000)}-{secrets.token_hex(3)}"


# play.py 的 load_tool_registry() 每次 Play 都会 import 这个文件的
# get_tools()——新项目一创建就给一份能直接 import 成功的起始文件，
# 而不是等 tool step 第一次运行时才因为文件不存在而报错。
_TOOL_REGISTRY_STARTER = '''\
"""Play 模式的工具注册表 —— get_tools() 返回 {tool 名: 回调函数}。

回调签名: def my_tool(args: dict) -> dict | str
  也支持 def my_tool(args: dict, ctx: dict) -> dict | str

- args 来自 spec 里这个 tool step 的 tool_args（对 context 做过 {{var}}
  替换）。
- 返回值可以是纯文本（直接作为这个 step 的输出显示），也可以是 dict——
  dict 里除 "route" 外的字段会被写入 workflow 的共享 context，供后续
  step 用 {{var}} 引用；如果这个 tool step 有多条 next_on_* 路由，dict
  需要带上 "route": "<label>" 字段来选路由。

在这里 import 你在 tools/custom/ 或 tools/generated/ 里写的函数，
组装进下面的字典，然后用 bind_tool(step, "tool_name") 把 step 绑定过去。
"""


def get_tools():
    return {}
'''


# plugins/ 的说明文件——目录是空的话没人知道该往里放什么、按什么约定写。
# 用 .md 而不是 .py 示例：plugins/*.py 会被真的加载，放一个示例文件进去
# 等于给每个新项目塞一个空插件。
_PLUGINS_README = """# 项目插件集

放在这里的 `*.py` 会在 Play 时加载，给 agent step 的 harness 添加工具/hook。

约定：每个文件暴露一个 `get_plugins()`，返回 senza Plugin 列表。

```python
import senza

def _now(args):
    from datetime import datetime
    return datetime.now().isoformat()

def get_plugins():
    clock = senza.create_tool(
        name="now",
        description="返回当前时间（ISO 格式）",
        parameters={"type": "object", "properties": {}},
        callback=lambda args, ctx: _now(args),
    )
    return [senza.create_plugin("clock", tools=[clock])]
```

说明：

- 下划线开头的文件会被跳过，可以放公共代码。
- 每次 Play 重新加载，改完不用重启 Studio 后端。
- 单个文件出错不影响其它插件，错误会显示在日志面板里。
- 这里的插件**只**作用于本项目的 Play 和导出，跟 Studio 元 agent 自己的
  插件完全隔离——导出之后行为一致。
- 只想加几个工具而不需要 hook 的话，写 `tools/registry.py` 更简单；插件
  适合需要打包一组工具 + hook 的场景。
"""


# tools/generated 和 tools/custom 的说明文件——两个目录都是自动发现的，
# 目录空着的话没人知道该按什么形状写。用 .md 不用 .py 示例：这两个目录里的
# *.py 会被真的当工具加载，放示例等于给每个新项目塞一个假工具。
_TOOL_DIR_README = """# tools/{dir}/

{who}。

这里的每个 `*.py` 在 Play 时自动加载，不需要在 `tools/registry.py` 里手动
import。约定：暴露一个 `TOOL` dict。

```python
def fetch_order(args):
    # args 来自 spec 里这个 tool step 的 tool_args（已做 {{{{var}}}} 替换）
    return {{"status": "shipped"}}      # 返回 dict 或字符串

TOOL = {{
    "name": "fetch_order",              # 必须和文件名一致才好找
    "description": "按订单号查询订单",   # 给元 agent 看的
    "parameters": {{                     # JSON Schema
        "type": "object",
        "properties": {{"order_id": {{"type": "string"}}}},
        "required": ["order_id"],
    }},
    "callback": fetch_order,
}}
```

说明：

- 下划线开头的文件会跳过，可以放公共代码。
- 每次 Play 重新加载，改完不用重启后端。
- 单个文件出错只丢它自己，错误会显示在日志面板里。
- 加载优先级（后者覆盖前者）：预制件 < generated/ < custom/ < registry.py。
- 真正的工作要放在 callback 里，不要放模块顶层——模块会在校验时被 import。
- {note}
"""


class Project:
    """单个 Studio 项目。"""

    def __init__(self, config: StudioConfig, meta: dict, path: Path) -> None:
        self.config = config
        self.meta = meta
        self.path = path

    # ── 创建/打开/列出 ────────────────────────────────────

    @classmethod
    def create(cls, config: StudioConfig, name: str) -> Project:
        proj_id = _gen_id("proj")
        path = config.projects_dir / proj_id
        path.mkdir(parents=True, exist_ok=True)

        # 创建目录结构 (design-v2 §3)
        (path / ".studio" / "docs").mkdir(parents=True, exist_ok=True)
        (path / ".studio" / "specs").mkdir(parents=True, exist_ok=True)
        (path / ".studio" / "sessions").mkdir(parents=True, exist_ok=True)
        (path / "tools" / "generated").mkdir(parents=True, exist_ok=True)
        (path / "tools" / "custom").mkdir(parents=True, exist_ok=True)
        (path / "tools" / "generated" / "README.md").write_text(
            _TOOL_DIR_README.format(
                dir="generated",
                who="元 agent 通过 generate_tool 生成的工具",
                note="这个目录由元 agent 管理，重新生成会覆盖同名文件——手写的"
                "工具请放 tools/custom/，那边不会被覆盖，而且同名时优先级更高。",
            ),
            encoding="utf-8",
        )
        (path / "tools" / "custom" / "README.md").write_text(
            _TOOL_DIR_README.format(
                dir="custom",
                who="开发人员手写的工具",
                note="这个目录元 agent 不碰。同名工具这里的实现会覆盖 "
                "tools/generated/ 里的，可以用来接管一个生成得不理想的工具。",
            ),
            encoding="utf-8",
        )
        (path / "tools" / "registry.py").write_text(_TOOL_REGISTRY_STARTER, encoding="utf-8")
        (path / "plugins").mkdir(parents=True, exist_ok=True)
        (path / "plugins" / "README.md").write_text(
            _PLUGINS_README, encoding="utf-8"
        )
        (path / "exports").mkdir(parents=True, exist_ok=True)

        meta = {
            "id": proj_id,
            "name": name,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "status": "editing",
            "model": config.model,
            "active_session": None,
            "sessions": [],
            "last_played_at": None,
            "last_export_dir": None,
        }

        # 初始空 spec
        spec = Spec()
        atomic_write_text(path / "pipeline.yaml", spec.to_yaml())

        proj = cls(config, meta, path)
        proj._save_meta()
        return proj

    @classmethod
    def open(cls, config: StudioConfig, project_id: str) -> Project:
        path = (config.projects_dir / project_id).resolve()
        if not path.is_relative_to(config.projects_dir.resolve()):
            raise FileNotFoundError(f"project {project_id} not found")
        meta_path = path / ".studio" / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"project {project_id} not found")
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectDataError(
                f"项目元数据损坏，未自动重建：{meta_path} ({exc})"
            ) from exc
        if not isinstance(meta, dict):
            raise ProjectDataError(f"项目元数据格式无效：{meta_path}")
        if meta.get("id") not in (None, project_id):
            raise ProjectDataError(f"项目元数据 id 不匹配：{meta_path}")
        return cls(config, meta, path)

    @classmethod
    def delete(cls, config: StudioConfig, project_id: str) -> None:
        """删除项目目录。路径安全检查与 open() 一致，防止越界删除。"""
        path = (config.projects_dir / project_id).resolve()
        if not path.is_relative_to(config.projects_dir.resolve()):
            raise FileNotFoundError(f"project {project_id} not found")
        if not path.exists():
            raise FileNotFoundError(f"project {project_id} not found")
        shutil.rmtree(path)

    @classmethod
    def list_all(cls, config: StudioConfig) -> list[dict]:
        projects_dir = config.projects_dir
        if not projects_dir.exists():
            return []
        result = []
        for p in sorted(projects_dir.iterdir()):
            meta_path = p / ".studio" / "meta.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if not isinstance(meta, dict):
                    raise ValueError("meta.json is not an object")
                if meta.get("id") not in (None, p.name):
                    raise ValueError("meta.json id does not match directory")
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                # 一个损坏项目不能拖垮整个项目列表；原始文件保持原样，
                # 记录路径供用户手工修复。
                print(
                    f"skipping corrupt project meta {meta_path}: {exc}",
                    file=sys.stderr,
                )
                continue
            result.append(meta)
        return result

    # ── Spec 持久化 ───────────────────────────────────────

    def save_spec(self, spec: Spec) -> None:
        yaml_path = self.path / "pipeline.yaml"
        # pipeline.yaml 的 replace 是提交点。meta.updated_at 没有业务消费者，
        # 它失败不应把已经安全落盘的 spec 报成失败。
        atomic_write_text(yaml_path, spec.to_yaml())
        self.meta["updated_at"] = _utc_now()
        try:
            self._save_meta()
        except Exception as exc:  # noqa: BLE001
            print(f"warning: spec saved but meta.json update failed: {exc}", file=sys.stderr)

    def load_spec(self) -> Spec:
        yaml_path = self.path / "pipeline.yaml"
        if not yaml_path.exists():
            return Spec()
        try:
            text = yaml_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ProjectDataError(f"pipeline.yaml 不可读：{exc}") from exc
        if not text.strip():
            raise ProjectDataError("pipeline.yaml 为空；拒绝当作空 spec 打开")
        try:
            raw = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ProjectDataError(f"pipeline.yaml 解析失败：{exc}") from exc
        # 必须在 Spec.from_yaml()/Spec() 默认化之前看原始结构。Spec 会把
        # 缺失的 stages 补成 []，那份宽容只适合作者显式写出 `stages: []`
        # 的项目；`null`、只有注释、顶层不是 mapping、缺字段或 stages 畸形
        # 都意味着文件损坏，不能静默当成空项目再被下一次保存覆盖。
        if raw is None:
            raise ProjectDataError("pipeline.yaml 是 null/只有注释；拒绝当作空 spec 打开")
        if not isinstance(raw, dict):
            raise ProjectDataError("pipeline.yaml 顶层必须是 mapping")
        if "stages" not in raw:
            raise ProjectDataError("pipeline.yaml 缺少 stages 字段")
        stages = raw.get("stages")
        if not isinstance(stages, list):
            raise ProjectDataError("pipeline.yaml 的 stages 必须是 list")
        if any(not isinstance(stage, dict) for stage in stages):
            raise ProjectDataError("pipeline.yaml 的每个 stage 必须是 mapping")
        try:
            return Spec(raw)
        except (SpecError, TypeError, ValueError) as exc:
            raise ProjectDataError(f"pipeline.yaml 解析失败：{exc}") from exc

    # ── Session 管理 ──────────────────────────────────────

    def new_session_id(self) -> str:
        """只生成 id，不写 meta/目录。调用方准备成功后再 commit_session()。"""
        return _gen_id("sess")

    def commit_session(self, session_id: str, *, add: bool) -> None:
        """原子提交 sessions/active_session，并把 meta 写盘。

        先在内存副本上改，写盘成功后才替换 self.meta；写失败则恢复旧
        meta。这样调用方可以在“目录/harness 已准备好”之后才调用它，
        失败时旧 session 和旧 meta 仍然一致。
        """
        old_meta = copy.deepcopy(self.meta)
        try:
            sessions = self.meta.setdefault("sessions", [])
            if add and session_id not in sessions:
                sessions.append(session_id)
            if session_id not in sessions:
                raise ValueError(f"session {session_id} not found")
            self.meta["active_session"] = session_id
            self._save_meta()
        except BaseException:
            # 保留 meta 对象身份：调用方/测试可能持有 project.meta 引用，
            # 回滚时不能只替换属性。
            self.meta.clear()
            self.meta.update(old_meta)
            raise

    def create_session(self) -> str:
        sid = self.new_session_id()
        self.commit_session(sid, add=True)
        return sid

    def set_active_session(self, session_id: str) -> None:
        self.commit_session(session_id, add=False)

    @property
    def sessions_dir(self) -> Path:
        return self.path / ".studio" / "sessions"

    # ── 内部 ──────────────────────────────────────────────

    def _save_meta(self) -> None:
        meta_path = self.path / ".studio" / "meta.json"
        atomic_write_text(
            meta_path,
            json.dumps(self.meta, ensure_ascii=False, indent=2),
        )
