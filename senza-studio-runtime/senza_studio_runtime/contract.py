"""界面契约：Studio 的 Game view 和导出 Agent 共用的那一份。

Game view 就是导出产品的预览——作者在 Studio 里看到什么，最终用户就看到什么。
要让这句话长期成立，"渲染什么"必须**只有一处定义**：两个前端各自去翻 spec 的
话，迟早长得不一样，而且是悄悄地（我们已经踩过一次：两边的默认值、标签、审批
区文案全都各写各的，最后差出七八处）。

所以这里产出一份**展示契约**，Studio 和导出项目的后端都回它：

    {
      "title": "客服工单处理",
      "description": "粘贴客户邮件，自动分类并起草回复",
      "layout": "form",            # 整体形态，见 LAYOUTS
      "theme": {...},              # 配色/明暗/密度，见 DEFAULT_THEME
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

# 整体形态。做的 agent 不一样，产品长相就不一样：一次性问答是表单 + 时间线，
# 数据复盘是一屏面板，没有共同的"正确布局"。不做成可自由拼版的 DSL——那是一门
# 要设计、要校验、还要让元 agent 写得好的新语言，而现在连第三种形态都还没出现。
# 加一种形态 = 加一个 layout 组件，喂给它的契约和运行状态跟别的形态完全一样。
LAYOUTS = ("form", "dashboard", "conversation")
DEFAULT_LAYOUT = "form"

# 配色/明暗/密度。前端把这些变成 CSS 变量，所有 layout 自动跟着变——交付给
# 别人的 agent 看起来像**他们的**产品，而不是像我们的。
THEME_KEYS = ("accent", "mode", "density", "logo")
THEME_MODES = ("light", "dark")
THEME_DENSITIES = ("comfortable", "compact")
DEFAULT_THEME = {
    "accent": "#2563eb",
    "mode": "light",
    "density": "comfortable",
    "logo": "",
}

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
                # 作者显式声明 optional 的字段可以留空；默认必填（向后兼容：
                # 没写 optional 的 agent 表单行为与从前一致）。
                "optional": bool(options.get("optional", False)),
            }
        )
    for field in fields:
        options = configured.get(field["name"])
        default = options.get("default") if isinstance(options, dict) else None
        if isinstance(default, str):
            field["default"] = default
    return fields


def describe_conversation(spec_dict: dict) -> dict:
    """Validate mappings against real template inputs (currently all strings).

    History is a bounded JSON *string*, never an undeclared array input. This
    contract deliberately makes no claim about runtime/business-state memory.
    """
    inputs = {field["name"] for field in describe_inputs(spec_dict)}
    config = _ui(spec_dict).get("conversation")
    if not isinstance(config, dict):
        raise ValueError("ui.conversation must be an object")
    allowed = {"message_input", "carry_inputs", "history_input",
               "history_max_messages", "history_max_chars"}
    if set(config) - allowed:
        raise ValueError("ui.conversation has unknown keys")
    message = config.get("message_input")
    carry = config.get("carry_inputs", [])
    history = config.get("history_input")
    if not isinstance(message, str) or message not in inputs:
        raise ValueError("conversation.message_input must reference a real string input")
    if not isinstance(carry, list) or any(not isinstance(v, str) or v not in inputs for v in carry):
        raise ValueError("conversation.carry_inputs must reference real string inputs")
    if len(carry) != len(set(carry)) or message in carry:
        raise ValueError("conversation input mappings must be distinct")
    if history is not None and (not isinstance(history, str) or history not in inputs
                                or history == message or history in carry):
        raise ValueError("conversation.history_input must reference a distinct real string input")
    result = {"message_input": message, "carry_inputs": carry}
    if history is not None:
        result["history_input"] = history
    for key, default, maximum in (("history_max_messages", 20, 100),
                                  ("history_max_chars", 12000, 100000)):
        value = config.get(key, default)
        if type(value) is not int or not 2 <= value <= maximum:
            raise ValueError(f"conversation.{key} must be an integer between 2 and {maximum}")
        result[key] = value
    return result


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


def infer_layout(steps: dict[str, dict]) -> str:
    """没写 ui.layout 时按流程形态猜一个。

    规则只看**非终点** step，而且只认两类信号：table/chart 是"面板"，chat 是
    "正文"。有面板且没有正文 → dashboard，否则 form。

    为什么排除终点 step：每个 spec 都必须有终点，而终点通常没配 ui（默认就是
    chat）。不排除的话这条规则几乎永远猜不出 dashboard。
    status 和 none 也不算信号：前者是进度提示，后者是作者明确说了不给人看；
    approval_form 也不算——数据看板一样可以有审批门。

    保守是故意的：配都没配过的 agent 不该突然变成一屏看板，猜错的代价是作者
    得去 Inspector 里改一下，比"看起来完全不是我做的那个东西"好。
    """
    panel = prose = 0
    for step in steps.values():
        if step.get("terminal"):
            continue
        display = step.get("display")
        if display in ("table", "chart"):
            panel += 1
        elif display == "chat":
            prose += 1
    return "dashboard" if panel and not prose else DEFAULT_LAYOUT


def describe_theme(spec_dict: dict) -> dict:
    """作者写的主题覆盖在默认值上。不认的 key 一律忽略——spec 是人和 LLM 一起
    编辑的，一个拼错的键名不该让整个界面白屏。"""
    configured = _ui(spec_dict).get("theme")
    configured = configured if isinstance(configured, dict) else {}
    theme = dict(DEFAULT_THEME)
    for key in THEME_KEYS:
        value = configured.get(key)
        if isinstance(value, str) and value:
            theme[key] = value
    if theme["mode"] not in THEME_MODES:
        theme["mode"] = DEFAULT_THEME["mode"]
    if theme["density"] not in THEME_DENSITIES:
        theme["density"] = DEFAULT_THEME["density"]
    return theme


def describe_agent(spec_dict: dict, fallback_title: str = "Agent") -> dict:
    """界面渲染所需的全部信息。一次请求拿齐，前端不用再拼第二个接口。

    展不开的组件不抛：产品界面该显示一条"这个 agent 装坏了"，而不是白屏。
    inputs/steps 给空，error 说明原因。
    """
    ui = _ui(spec_dict)
    info: dict[str, Any] = {
        "title": str(ui.get("title") or fallback_title),
        "description": str(ui.get("description") or ""),
        "layout": DEFAULT_LAYOUT,
        "theme": describe_theme(spec_dict),
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

    # 作者写了就听他的；没写就按流程形态猜。回给前端的永远是**最终生效的那个**
    # ——前端不该也去猜一遍（那就又是两份实现了）。
    explicit = ui.get("layout")
    info["layout"] = (
        explicit if explicit in LAYOUTS else infer_layout(info["steps"])
    )
    if info["layout"] == "conversation":
        try:
            info["conversation"] = describe_conversation(spec_dict)
        except ValueError as exc:
            info["error"] = str(exc)
    return info
