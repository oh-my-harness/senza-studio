"""界面契约：Studio 的 Game view 和导出 Agent 共用的那一份。

Game view 就是导出产品的预览——作者在 Studio 里看到什么，最终用户就看到什么。
要让这句话长期成立，"渲染什么"必须**只有一处定义**：两个前端各自去翻 spec 的
话，迟早长得不一样，而且是悄悄地（我们已经踩过一次：两边的默认值、标签、审批
区文案全都各写各的，最后差出七八处）。

所以这里产出一份**展示契约**，Studio 和导出项目的后端都回它：

    {
      "title": "客服工单处理",
      "description": "粘贴客户邮件，自动分类并起草回复",
      "inputs": [{"name", "label", "placeholder", "multiline"}],
      "steps": {"<step>": {"title", "display", "fields", "choices", "terminal"}},
      "error": None,
    }

刻意**不含流程结构**：prompt、工具、next_on_* 指向哪里，一个字都不回。前端因此
在结构上就画不出 DAG，而不是"画得出但我们不画"。

标签（step 标题、选项文案、输入框 label）全在这里算好，前端不做任何猜测——
猜测放在前端就等于放了两份，而且作者无从覆盖。
"""
from __future__ import annotations

import re
from typing import Any

from .preprocess import PreprocessError, preprocess_spec

# ui.display 没写时按 chat 渲染。两边共用这一个默认值——以前 Game view 和导出
# 各写各的默认值，同一个 spec 在两边长得不一样。
DEFAULT_DISPLAY = "chat"

# 入口输入默认多行。种子输入多半是粘进来的整段内容（邮件正文、工单描述），
# 单行框放不下；要单行的作者自己在 ui.inputs 里关掉。
DEFAULT_MULTILINE = True

_WORD_SPLIT = re.compile(r"[_\-]+")


def humanize(name: str) -> str:
    """变量名/step 名 → 给人看的标签。customer_email → Customer email。

    只是个兜底：作者在 ui 块里写了 label/title 就用他写的。中文名字经过这里
    不会有任何变化（没有下划线可拆，首字母大写对中文是空操作）。
    """
    spaced = _WORD_SPLIT.sub(" ", name).strip()
    return spaced[:1].upper() + spaced[1:] if spaced else name


def _ui(source: Any) -> dict:
    """取 ui 块，非 dict 一律当没写——spec 是人和 LLM 一起编辑的，
    `ui: chat` 这种写法出现过，不能因此整个界面炸掉。"""
    block = source.get("ui") if isinstance(source, dict) else None
    return block if isinstance(block, dict) else {}


def describe_inputs(spec_dict: dict) -> list[dict]:
    """入口 step 的 prompt_template 里引用的 {{var}} → 表单字段描述。

    扫 prompt_template 而不是 ui.inputs：ui.inputs 是**给这些字段配文案**的
    地方，不是声明字段的地方。作者删了一个 {{var}} 却忘了删对应的 ui.inputs
    条目时，表单不该还问一个没人用的字段。
    """
    from .play import get_entry_inputs  # 延迟导入：play 会拉起整个 SDK

    configured = _ui(spec_dict).get("inputs")
    configured = configured if isinstance(configured, dict) else {}

    fields = []
    for name in get_entry_inputs(spec_dict):
        options = configured.get(name)
        options = options if isinstance(options, dict) else {}
        fields.append(
            {
                "name": name,
                "label": str(options.get("label") or humanize(name)),
                "placeholder": str(options.get("placeholder") or ""),
                "multiline": bool(options.get("multiline", DEFAULT_MULTILINE)),
            }
        )
    return fields


def describe_steps(spec_dict: dict) -> dict[str, dict]:
    """展开后的 spec → 每个 step 的展示契约。

    收编辑态 spec，内部先 preprocess：能力组件展开出来的 step（gate_review
    之类）在编辑态里根本不存在，而它恰恰常常就是那个要人工审批的 step。
    """
    steps: dict[str, dict] = {}
    for stage in preprocess_spec(spec_dict).get("stages", []):
        name = stage.get("name")
        if not name:
            continue
        ui = _ui(stage)
        labels = ui.get("choice_labels")
        labels = labels if isinstance(labels, dict) else {}
        # 停下来问人时给的选项。只有 checker 会停，所以只有它有 choices——
        # 普通 step 的 next_on_* 是流程结构（"这一步之后能走哪几条分支"），
        # 不是给用户的选项，回给前端等于把 DAG 的一部分漏出去。
        choices = []
        if stage.get("type") == "checker":
            for key, value in sorted(stage.items()):
                if not key.startswith("next_on_") or not isinstance(value, str):
                    continue
                route = key[len("next_on_"):]
                choices.append(
                    {"value": route, "label": str(labels.get(route) or humanize(route))}
                )
        steps[name] = {
            "title": str(ui.get("title") or humanize(name)),
            "display": ui.get("display") or DEFAULT_DISPLAY,
            "fields": ui.get("fields") or [],
            "choices": choices,
            # 终点 step。前端据此把最后一张卡片渲染成"结果"而不是"过程"。
            "terminal": stage.get("type") == "terminal",
        }
    return steps


def describe_agent(spec_dict: dict, fallback_title: str = "Agent") -> dict:
    """界面渲染所需的全部信息。一次请求拿齐，前端不用再拼第二个接口。

    展不开的组件不抛：产品界面该显示一条"这个 agent 装坏了"，而不是白屏。
    inputs/steps 给空，error 说明原因。
    """
    ui = _ui(spec_dict)
    info: dict[str, Any] = {
        "title": str(ui.get("title") or fallback_title),
        "description": str(ui.get("description") or ""),
        "inputs": [],
        "steps": {},
        "error": None,
    }
    try:
        info["inputs"] = describe_inputs(spec_dict)
        info["steps"] = describe_steps(spec_dict)
    except PreprocessError as exc:
        info["error"] = str(exc)
    return info
