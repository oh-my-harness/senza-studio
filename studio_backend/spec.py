"""Spec 内存 dict + CRUD + 校验 + YAML 序列化。

Spec 是 pipeline.yaml 的内存表示，元 agent 通过工具 API 增量构建。
YAML 只是序列化输出，元 agent 不直接写 YAML。
"""
from __future__ import annotations

import copy
from typing import Any

import yaml


class SpecError(Exception):
    """Spec 操作错误。"""


_VALID_TYPES = {"agent", "checker", "tool", "terminal"}
_EDGE_PREFIX = "next_on_"


class Spec:
    """Pipeline spec 的内存表示。

    内部格式与 pipeline.yaml 一致：
        {"stages": [{"name": str, "type": str, ...}]}

    边以 next_on_<condition> 字段存储在 step 上。
    """

    def __init__(self, data: dict | None = None) -> None:
        if data is not None:
            if not isinstance(data, dict):
                raise SpecError(
                    f"spec data must be a dict, got {type(data).__name__}"
                )
            if "stages" not in data:
                data = {"stages": []}
        self._data: dict = copy.deepcopy(data) if data else {"stages": []}

    # ── 查询 ──────────────────────────────────────────────

    def get_current_spec(self) -> dict:
        """返回 spec 的深拷贝。"""
        return copy.deepcopy(self._data)

    def _find_step(self, name: str) -> dict | None:
        for step in self._data.get("stages", []):
            if step.get("name") == name:
                return step
        return None

    def _step_names(self) -> set[str]:
        return {s.get("name", "") for s in self._data.get("stages", [])}

    # ── CRUD ──────────────────────────────────────────────

    def add_step(
        self,
        name: str,
        description: str,
        type: str,
        prompt_template: str | None = None,
        **extra: Any,
    ) -> None:
        if not name or not name.strip():
            raise SpecError("step name cannot be empty")
        if type not in _VALID_TYPES:
            raise SpecError(f"invalid step type: {type}")
        if self._find_step(name):
            raise SpecError(f"step '{name}' already exists")

        step: dict[str, Any] = {"name": name, "type": type}
        if prompt_template is not None:
            step["prompt_template"] = prompt_template
        if type == "terminal":
            step.setdefault("message", description)
        step.update(extra)

        self._data.setdefault("stages", []).append(step)

    def remove_step(self, name: str) -> None:
        step = self._find_step(name)
        if step is None:
            raise SpecError(f"step '{name}' not found")
        self._data["stages"] = [
            s for s in self._data["stages"] if s.get("name") != name
        ]
        # 清理指向该 step 的边
        for s in self._data["stages"]:
            for key in list(s.keys()):
                if key.startswith(_EDGE_PREFIX) and s[key] == name:
                    del s[key]

    def add_edge(self, from_step: str, to_step: str, condition: str) -> None:
        src = self._find_step(from_step)
        if src is None:
            raise SpecError(f"step '{from_step}' not found")
        if to_step not in self._step_names():
            raise SpecError(f"step '{to_step}' not found")
        key = f"{_EDGE_PREFIX}{condition}"
        src[key] = to_step

    def remove_edge(self, from_step: str, to_step: str, condition: str) -> None:
        src = self._find_step(from_step)
        if src is None:
            raise SpecError(f"step '{from_step}' not found")
        key = f"{_EDGE_PREFIX}{condition}"
        if key in src and src[key] == to_step:
            del src[key]
        else:
            raise SpecError(
                f"edge {from_step} --{condition}--> {to_step} not found"
            )

    def set_step_property(self, step_name: str, key: str, value: Any) -> None:
        step = self._find_step(step_name)
        if step is None:
            raise SpecError(f"step '{step_name}' not found")
        step[key] = value

    # ── 校验 ──────────────────────────────────────────────

    def validate(self) -> None:
        """校验 spec 完整性。失败时 raise SpecError。"""
        stages = self._data.get("stages", [])
        if not stages:
            raise SpecError("spec has no stages")

        # 校验重名
        names = self._step_names()
        if len(names) != len(stages):
            seen: set[str] = set()
            for s in stages:
                n = s.get("name", "")
                if n in seen:
                    raise SpecError(f"duplicate step name: {n}")
                seen.add(n)

        # 校验边指向
        for s in stages:
            for key, val in s.items():
                if key.startswith(_EDGE_PREFIX) and isinstance(val, str):
                    if val not in names:
                        raise SpecError(
                            f"edge from '{s['name']}' points to unknown step '{val}'"
                        )

        # 至少有一个 terminal step
        has_terminal = any(s.get("type") == "terminal" for s in stages)
        if not has_terminal:
            raise SpecError("spec has no terminal step")

    # ── 序列化 ────────────────────────────────────────────

    def to_yaml(self) -> str:
        return yaml.dump(self._data, allow_unicode=True, sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> Spec:
        data = yaml.safe_load(yaml_str)
        return cls(data)
