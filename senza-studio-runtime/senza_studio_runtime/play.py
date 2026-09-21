"""Play 模式：直接用 senza 的 WorkflowEngine 跑 spec。

`stages_to_workflow`（senza SDK 内置）已经把 `{"stages": [...]}` 编译成
Workflow：每个非 terminal stage 变成一个 executor step（统一分派到
"eda_executor"），terminal stage 被引擎直接短路成原生 Step::Terminal——
永远不会调用这里的 executor 回调。所以 Studio 自己不需要写 spec 预处理器，
只需要一个 executor 回调（支持 type: agent/checker/tool）和一个 judge
回调（把 executor 返回的 route_key 翻成 "to:<step>"）。

`stages_to_workflow` 不会把 stage 的原始字段（type/prompt_template/...）
透传进 executor_config，所以这里自己维护 step_name -> stage dict 和
step_name -> {route_label: target} 两张表。

回调工厂（make_judge/make_executor）与 spec_tools.make_spec_callbacks 同一
模式：与 senza.create_judge/create_executor 的包装分离，方便直接单测。
"""
from __future__ import annotations

import enum
import importlib.util
import inspect
import json
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import senza

from .preprocess import preprocess_spec

_TERMINAL_TYPES = frozenset({"settled", "aborted", "error", "agent_end"})
_SKIP_TYPES = frozenset({"timeout"})

# ── 平台级安全护栏（与业务/loop 逻辑无关的最后兜底）──────────────────────
# max_steps：引擎级 step_history 总上限（含所有 Retry 重跑）。超过 → Failed。
# max_active_seconds：累计 *活跃* 执行时间的墙钟上限。暂停/HITL 等待不计入，
# 跨 resume 累计；耗尽后走 PlaySession.stop()（engine.cancel）终止。
PLAY_MAX_STEPS = 75
PLAY_MAX_ACTIVE_SECONDS = 15 * 60
_TIMEOUT_REASON = "play execution time limit exceeded (15 active minutes)"


def create_provider(api_key: str, api_base: str | None = None) -> Any:
    """OpenAI 兼容 provider。收凭据而不是 StudioConfig——运行时不认识
    Studio 的配置对象，导出的项目也没有 Studio 配置可给。"""
    return senza.providers.openai(api_key=api_key, base_url=api_base or None)


def build_route_maps(
    spec_dict: dict,
) -> tuple[dict[str, dict], dict[str, dict[str, str]]]:
    """从 spec dict 构建 step_name -> stage dict 和 step_name -> {label: target}。"""
    stage_by_name: dict[str, dict] = {}
    routes_by_name: dict[str, dict[str, str]] = {}
    for stage in spec_dict.get("stages", []):
        name = stage["name"]
        stage_by_name[name] = stage
        routes: dict[str, str] = {}
        for key, val in stage.items():
            if key.startswith("next_on_") and isinstance(val, str):
                routes[key[len("next_on_") :]] = val
        routes_by_name[name] = routes
    return stage_by_name, routes_by_name


_TEMPLATE_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def render_prompt_template(template: str, context: dict) -> str:
    """替换 prompt_template 里的 {{var}} 占位符。

    故意不用 str.format()：real prompt_template 经常自带单花括号 JSON 例子
    （比如 '{"classification": "complaint" | "question"}'），.format() 会把
    它们当成格式字段解析，多半直接 KeyError，导致整个模板一次替换都不做，
    连正常的 {{var}} 也不替换。这里只认双花括号，其它内容完全不碰；缺失的
    变量保留原样（而不是报错/清空模板），方便一眼看出漏填了什么。
    """

    def _sub(m: re.Match) -> str:
        key = m.group(1)
        return str(context[key]) if key in context else m.group(0)

    return _TEMPLATE_VAR_RE.sub(_sub, template)


def render_tool_args(tool_args: Any, context: dict) -> dict:
    """渲染 tool step 的 tool_args——跟 prompt_template 一样用 {{var}} 从
    context 取值，但作用对象是一个 dict（每个字符串 value 各自替换一次），
    不是一整段模板。非字符串 value（作者直接写死的数字/布尔等）原样传递。
    没声明 tool_args 的 step 得到空 dict——工具需要的参数必须显式声明，
    不能隐式拿整个 context（跟 agent step 只能通过 prompt_template 里的
    {{var}} 声明输入是同一个原则）。

    tool_args 来自 spec（可能是元 agent 通过 set_step_property 写进去的，
    也可能是人手改 pipeline.yaml）——不是 Studio 自己生成的可信数据，是个
    真实的输入边界。实测元 agent 的 LLM 调用 set_step_property 时会偶尔把
    这个本该是 dict 的 value 参数吐成一段 JSON 字符串（比如
    '{"city": "{{city}}"}'）而不是真正的嵌套对象——大概率是模型在处理一个
    schema 里没标注具体 type（"any JSON type"）的参数时的常见毛病。不做
    防御的话，这里会直接 AttributeError（字符串没有 .items()），而且是在
    调用方 try/except 包裹的范围之外抛出，会把整个 executor 回调打崩，而
    不是干净地失败成这一个 step 的 error。所以这里既接受字符串（尝试当
    JSON 解析一遍），也接受任何解析不出 dict 的情况——一律退化成空 dict，
    而不是让整个 workflow 崩掉。
    """
    if isinstance(tool_args, str):
        try:
            tool_args = json.loads(tool_args)
        except (json.JSONDecodeError, ValueError):
            tool_args = {}
    if not isinstance(tool_args, dict):
        return {}
    return {
        key: render_prompt_template(value, context) if isinstance(value, str) else value
        for key, value in tool_args.items()
    }


def get_entry_inputs(spec_dict: dict) -> list[str]:
    """入口 step（第一个 stage，与 stages_to_workflow 的 entry_step 规则一致）
    prompt_template 里引用的 {{var}} 占位符——Play 前需要真人手动填的种子
    输入（比如 customer_message），因为 Studio 不接真实生产流量。

    故意扫 prompt_template 本身，而不是 ui.fields：ui.fields 是展示配置
    （这个 step 结果要在 Game view 用哪些字段渲染 chart/table 卡片），跟
    "这个 step 需要哪些输入" 是完全不同的两件事——同一个字段名可能两边都
    用（巧合），也可能像 ui.fields=[route, reasoning] 这种纯输出展示字段
    完全对不上输入，把它当输入需求会问出不存在的字段。prompt_template 里
    实际出现的 {{var}} 才是唯一可靠的输入来源。

    收编辑态 spec，内部自己先 preprocess——spec 第一个 stage 可能是个能力
    组件引用，它本身没有 prompt_template，展开后的入口 step 才有。调用方
    （比如 /api/projects/{id}/entry-inputs）因此不用关心组件语义。
    """
    stages = preprocess_spec(spec_dict).get("stages", [])
    if not stages:
        return []
    entry = stages[0]

    # prompt_template（agent/checker step）和 tool_args（tool step）——入口
    # step 声明自己需要什么输入，就这两个地方。只扫前者的话，以 tool step 开
    # 头的流程（数据看板那一类：先拉数，参数是"查哪个区域"）永远问不出参数，
    # 而 render_tool_args 那边其实是认 {{var}} 的，等于输入永远是空字符串。
    sources = [entry.get("prompt_template", "")]
    tool_args = entry.get("tool_args")
    if isinstance(tool_args, dict):
        sources.extend(v for v in tool_args.values() if isinstance(v, str))

    seen: list[str] = []
    for source in sources:
        for match in _TEMPLATE_VAR_RE.finditer(source):
            key = match.group(1)
            if key not in seen:
                seen.append(key)
    return seen


# checker step 在等人工审批时，executor 返回这个 route_key——judge 认出
# 它就转成 "pause:..."，而不是当成一个查不到边的路由错误。
PENDING_APPROVAL = "__pending_approval__"


def decision_context_key(step_id: str) -> str:
    """人工审批结果存在 context 里的 key——完全是 Studio 内部记账，spec
    作者不需要（也不能）声明它。checker executor 检查它决定要不要 pause，
    submit_decision() 写它然后 resume。"""
    return f"__decision_{step_id}__"


def make_judge(
    routes_by_name: dict[str, dict[str, str]],
    engine_ref: dict[str, Any] | None = None,
) -> Callable[[dict], str]:
    """路由回调：把 executor 返回的 route_key 翻成 senza judge 的 transition 字符串。

    engine_ref 是晚绑定容器（跟 make_executor 的同一个约定）：V1 验证失败时
    judge 要往共享 context 写/清 step-scoped 的修正反馈，没有 engine 写不进去。
    """
    _validation_engine_ref = engine_ref if engine_ref is not None else {}

    def play_judge(ctx: dict) -> str:
        step_id = ctx["step_id"]
        structured = ctx.get("structured") or {}

        # V1 不变量：结构化验证失败优先于一切正常路由匹配。没有这个前置
        # 处理，失败的验证会退化成 route_key="error" → "no route for
        # 'error'"——用户可读的诊断必须在 execute 路由匹配之前给出。
        validation = structured.get("_validation") or {}
        if validation.get("status") == "failed":
            detail = str(validation.get("detail", ""))
            feedback_key = validation_feedback_key(step_id=ctx["step_id"])
            engine = _validation_engine_ref.get("engine")
            if ctx.get("retry_count", 0) == 0:
                # 第一次失败：把修正反馈写进共享 context（step-scoped），
                # 只对紧接着的那一次重试生效（重试 attempt 开头即读+清）。
                if engine is not None:
                    engine.set_context_variable(feedback_key, detail)
                return "retry"
            # 连续第二次失败（或引擎重试上限兜底）：显式失败——不再静默
            # 合成 "no route for 'error'"。清掉反馈，防止终态后残留。
            if engine is not None:
                engine.set_context_variable(feedback_key, None)
            return f"fail:structured_output_validation_failed ({validation.get('code')}): {detail}"

        route_key = structured.get("route_key")
        if route_key == PENDING_APPROVAL:
            return f"pause:waiting for approval on '{ctx['step_id']}'"
        routes = routes_by_name.get(ctx["step_id"], {})
        target = routes.get(route_key)
        if target is None:
            reason = f"no route for '{route_key}' from '{ctx['step_id']}'"
            # ctx["output"] 是 executor 真正返回的错误详情（比如 "step type
            # 'checker' not supported until Phase 3"）——不带上的话，日志面板
            # 只会看到一句不知道为什么的路由失败，得跑去 Game view 才看得到
            # 真正原因。
            output = ctx.get("output")
            if output:
                reason += f" — {output}"
            return f"fail:{reason}"
        return f"to:{target}"

    return play_judge


def _run_agent_step(harness: Any, prompt: str, emit: Any) -> tuple[str, int]:
    """驱动一个短生命周期 harness 跑一轮 prompt，streaming 转发到 emit。

    与 ws.py 的 run_prompt_streaming 同一模式：prompt() 阻塞到整轮结束，
    必须放到独立线程，当前线程负责同步迭代 events() 拿 streaming token。

    顺带数一遍这一轮里 LLM 发起了几次工具调用（tool_call_start）——
    WorkflowEvent::StepFinished 自带的 tool_calls_count 字段对 Studio 的
    executor-驱动 step 永远是硬编码的 0（Rust 侧看不到 Python 回调内部
    发生了什么），这是唯一能拿到真实数字的地方，因为 harness.events()
    是一次性消费的迭代器，事后没法回头再数。返回 (输出文本, 工具调用次数)。
    """
    errors: list[BaseException] = []
    done = threading.Event()

    def _do_prompt() -> None:
        try:
            harness.prompt(prompt)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
            print(f"Play prompt error: {exc}", file=sys.stderr)
        finally:
            done.set()

    prompt_thread = threading.Thread(target=_do_prompt, daemon=True)
    prompt_thread.start()

    text_parts: list[str] = []
    tool_calls_count = 0
    for event in harness.events(timeout_ms=5000, max_consecutive_timeouts=999):
        if event is None:
            if not prompt_thread.is_alive():
                break
            continue
        if not isinstance(event, dict):
            try:
                event = dict(event)
            except Exception:
                continue
        etype = event.get("type")
        if etype in _SKIP_TYPES:
            continue
        if etype == "text_delta":
            text = event.get("text", "")
            text_parts.append(text)
            emit.text_delta(text)
        elif etype == "tool_call_start":
            tool_calls_count += 1
        elif etype in _TERMINAL_TYPES:
            break

    prompt_thread.join(timeout=125)
    if errors:
        raise errors[0]
    return "".join(text_parts), tool_calls_count


# 顶层 JSON 对象提取器（替代旧的扁平正则 \{[^{}]*\}）：从 LLM 回答里找最后
# 一个**完整顶层**对象——支持嵌套（比如 evaluate_results 的 route + candidates
# 数组），字符串里的花括号/转义引号不算结构。用来既提取路由标记，也提取
# 其它想传给下游 step 的结构化字段。


def _looks_like_json_container(output: str, start: int) -> bool:
    """Return whether ``output[start]`` plausibly begins a JSON container.

    This small guard lets the structural scanner ignore prose punctuation such as
    ``"starts with {."`` without attempting to validate the entire JSON value.
    Final validation remains ``json.loads``' responsibility.
    """
    opener = output[start]
    k = start + 1
    while k < len(output) and output[k] in " \t\r\n":
        k += 1
    if k == len(output):
        return True
    if opener == "{":
        return output[k] in '\"}'
    return output[k] in '[{\"]-0123456789tfn'


def _last_top_level_json_object(output: str) -> tuple[int, int] | None:
    """扫描 output，返回最后一个完整顶层 ``{...}`` 对象的 (start, end)。

    单趟维护对象/数组栈。只有栈为空时开始的对象才是顶层候选；因此截断
    外层中的属性对象和数组 sibling 都始终保留嵌套身份，不能在恢复扫描时
    被提升。字符串里的括号和转义字符不参与结构计数。

    散文中的引号在容器外被忽略；明显不是 JSON 起点的 ``{`` / ``[`` 也
    被忽略，保留 ``The token starts with {.`` 后仍能发现合法 JSON 的行为。
    完整顶层对象闭合后继续扫描，从而保持“最后一个完整顶层对象胜出”。
    """
    best: tuple[int, int] | None = None
    stack: list[str] = []
    root_start: int | None = None
    root_is_object = False
    in_string = False
    escaped = False

    for i, ch in enumerate(output):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue

        if stack and ch == '"':
            in_string = True
        elif ch in "{[":
            if stack or _looks_like_json_container(output, i):
                if not stack:
                    root_start = i
                    root_is_object = ch == "{"
                stack.append(ch)
        elif ch in "}]" and stack:
            expected = "{" if ch == "}" else "["
            if stack[-1] != expected:
                stack.clear()
                root_start = None
                root_is_object = False
                in_string = False
                escaped = False
                continue
            stack.pop()
            if not stack:
                if root_is_object and root_start is not None:
                    best = (root_start, i + 1)
                root_start = None
                root_is_object = False
    return best


def _extract_json_fields(output: str) -> tuple[dict, str]:
    """找输出里最后一个完整顶层 JSON 对象，解析出字段，并从展示文本里去掉这段。

    找不到、解析失败、或解析出来不是 dict，都原样返回（fields={}）——不是
    每个 agent step 都会吐 JSON，纯文字回复（比如草拟的客服回信）应该
    完全不受影响。
    """
    span = _last_top_level_json_object(output)
    if span is None:
        return {}, output
    start, end = span
    try:
        fields = json.loads(output[start:end])
    except (json.JSONDecodeError, ValueError):
        return {}, output
    if not isinstance(fields, dict):
        return {}, output
    clean_output = (output[:start] + output[end:]).strip()
    return fields, clean_output


class StructuredValidationCode(enum.Enum):
    """结构化输出验证失败码——每个码都是一类可单独诊断的模型输出缺陷。"""

    INVALID_JSON = "invalid_json"  # 没有可解析的顶层 JSON object（含截断）
    MISSING_ROUTE = "missing_route"  # 解析成 dict 了，但没有顶层 "route"
    ROUTE_NOT_STRING = "route_not_string"  # "route" 存在但不是字符串
    UNKNOWN_ROUTE = "unknown_route"  # "route" 是字符串，但不在合法枚举里


@dataclass(frozen=True)
class StructuredValidation:
    """结构化输出验证结果。OK 时 code == None；失败时携带人类可读的 detail。"""

    code: StructuredValidationCode | None
    detail: str = ""
    attempt: int = 1
    raw_head: str = ""

    @property
    def ok(self) -> bool:
        return self.code is None

    def to_dict(self) -> dict:
        """序列化成 structured["_validation"] 的 payload。成功时不产生条目。"""
        if self.ok:
            return {}
        return {
            "status": "failed",
            "code": self.code.value,
            "detail": self.detail,
            "attempt": self.attempt,
            "raw_head": self.raw_head,
        }


def validation_feedback_key(step_id: str) -> str:
    """验证失败修正反馈在共享 context 里的 key——按 step 隔离，只在该 step
    的下一次（重试）prompt 组装时被读取并立刻清除。命名空间化是刻意的：
    引擎的 context 是整个 workflow 生命周期共享的 Arc（Transition::Retry 不
    重置、resume 也不清），裸的全局 key 会在重放/其它 step 间泄漏。"""
    return f"_validation_feedback::{step_id}"


def _validate_structured(
    fields: Any, output: str, routes: list[str], attempt: int
) -> StructuredValidation:
    """对 _extract_json_fields 的产物做确定性验证。只查结构化路由契约：
    顶层 dict、"route" 键存在且为字符串、值在合法枚举内。字段类型/额外
    字段不验证——V1 只关心平台结构性消费的部分。"""
    raw_head = output[:200]
    span = _last_top_level_json_object(output)
    if not isinstance(fields, dict) or span is None:
        # fields 不是 dict，或解析器根本没找到可解析的顶层对象（纯散文/截断
        # 到不可恢复）——两类都是"没有合法 JSON object"。
        return StructuredValidation(
            StructuredValidationCode.INVALID_JSON,
            "response does not contain a parseable top-level JSON object",
            attempt, raw_head,
        )
    if not fields:
        # 扫描器定位到了对象 span，但 json.loads 失败（提取返回空 dict）——
        # 结构存在但内容不是合法 JSON（比如尾逗号）。
        try:
            json.loads(output[span[0] : span[1]])
        except (json.JSONDecodeError, ValueError):
            return StructuredValidation(
                StructuredValidationCode.INVALID_JSON,
                "top-level JSON object found but not valid JSON",
                attempt, raw_head,
            )
    if "route" not in fields:
        return StructuredValidation(
            StructuredValidationCode.MISSING_ROUTE,
            f"no top-level \"route\" field (expected one of: {', '.join(routes)})",
            attempt, raw_head,
        )
    route = fields["route"]
    if not isinstance(route, str):
        return StructuredValidation(
            StructuredValidationCode.ROUTE_NOT_STRING,
            f"\"route\" must be a string, got {type(route).__name__}",
            attempt, raw_head,
        )
    if route not in routes:
        return StructuredValidation(
            StructuredValidationCode.UNKNOWN_ROUTE,
            f"route '{route}' not in [{', '.join(routes)}]",
            attempt, raw_head,
        )
    return StructuredValidation(None, attempt=attempt)


def _append_routing_instruction(prompt: str, routes: list[str]) -> str:
    """多路由时，要求 LLM 在回答末尾用一行 JSON 声明选中的路由。

    routes 来自 routes_by_name（next_on_* 派生）——V1 起这就是验证器的
    合法枚举，prompt 里的措辞和代码验证用同一份来源，不再有两处各写各的。

    如果 prompt_template 本身已经要求了别的 JSON 字段（比如给 output_key
    用的 summary），这条指令必须显式提醒"保留原有字段"——否则模型会把
    这条指令当成最后、最具体的要求，只吐一个只有 route 的 JSON，
    _extract_json_fields 取最后一个 JSON blob 时就会把 summary 等字段
    丢掉（实测触发过一次：多路由 + output_key 同时出现时 summary 消失）。
    """
    options = ", ".join(f'"{r}"' for r in routes)
    return (
        f"{prompt}\n\n---\n"
        f"After your response, end with exactly one line containing a single JSON "
        f"object with a \"route\" field, choosing whichever option best applies: "
        f'{{"route": "<one of: {options}>"}}. '
        f"The \"route\" value MUST be exactly one of: {options} — no other value "
        f"will be accepted. "
        f"If your instructions above already asked for other JSON fields (e.g. a "
        f"summary), keep them in this same JSON object alongside \"route\" — "
        f"do not drop them."
    )


def _append_validation_feedback(prompt: str, feedback: str) -> str:
    """重试 prompt 追加上一次验证失败的修正反馈。

    反馈只在重试这一次的 prompt 组装时出现：executor 在读取反馈变量的同时
    把它从共享 context 清掉，生命周期恰好覆盖一次 prompt——不会泄漏到后续
    step 或更晚的重入。
    """
    return (
        f"{prompt}\n\n---\n"
        f"Your previous answer was rejected because it was not a valid routing "
        f"response: {feedback}\n"
        f"Fix this and follow the routing JSON rules above exactly."
    )



def _load_prefab_tools() -> dict[str, Callable]:
    """senza_studio_components 是本仓库 ./senza-studio-components 子目录里的
    独立 pip 包（Phase 4）——dev.sh 会 editable install 它，但没装的话降级成
    没有预制件可用，不影响项目自己的 tools/registry.py。"""
    try:
        from senza_studio_components import registry as prefab_registry
    except ImportError:
        return {}
    return dict(prefab_registry.get_tools())


def load_project_plugins(root: Path) -> tuple[list[Any], list[str]]:
    """加载 <project>/plugins/ 下的项目插件集，返回 (plugins, 错误列表)。

    约定跟 tools/registry.py 一致：每个 ``plugins/*.py`` 暴露一个
    ``get_plugins()``，返回 senza Plugin 列表（``senza.create_plugin`` 造
    的）。下划线开头的文件跳过，方便放公共代码。

    **插件集是隔离的**（设计文档 §7）：这里只加载当前项目的插件，绝不注入
    Studio 元 agent 自己那套（fs_tools/safety_defaults/injection_filter
    等）。业务流程该跑什么工具由项目自己决定，不该因为它跑在 Studio 里就
    莫名其妙多出一堆 Studio 的能力——那样导出之后行为还会变。

    和 load_tool_registry 一样每次 Play 重新 import（不热加载、不跨项目缓
    存）：换一个新模块名绕开 sys.modules，这样开发者改完插件下一次 Play
    就生效，也不会让两个项目里同名的 plugins/foo.py 互相串。

    单个插件加载失败不影响其它插件，也不让整个 Play 崩——插件是加法，缺一
    个只是少一批工具。错误收集起来由调用方显示给用户，否则 agent 会莫名其
    妙少了工具却没有任何提示。
    """
    plugins_dir = root / "plugins"
    if not plugins_dir.is_dir():
        return [], []

    plugins: list[Any] = []
    errors: list[str] = []
    for path in sorted(plugins_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            get_plugins = getattr(_exec_module_fresh(path), "get_plugins", None)
            if get_plugins is None:
                errors.append(f"plugins/{path.name}: 没有定义 get_plugins()")
                continue
            produced = get_plugins()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"plugins/{path.name}: 加载失败: {exc}")
            continue

        if not isinstance(produced, (list, tuple)):
            errors.append(
                f"plugins/{path.name}: get_plugins() 必须返回列表，"
                f"实际返回了 {type(produced).__name__}"
            )
            continue
        for item in produced:
            if isinstance(item, senza.Plugin):
                plugins.append(item)
            else:
                # 明确报错而不是静默丢掉：最常见的写法错误就是返回了
                # create_tool 造的 Tool（或一个裸函数），而不是 Plugin。
                errors.append(
                    f"plugins/{path.name}: get_plugins() 返回了 "
                    f"{type(item).__name__}，需要的是 senza.create_plugin() "
                    f"造出来的 Plugin"
                )
    return plugins, errors


def _exec_module_fresh(path: Path) -> Any:
    """按文件路径加载一个模块，且**绕开 .pyc 字节码缓存**。

    为什么不用 spec.loader.exec_module：CPython 的字节码缓存是按
    (mtime, size) 判断新旧的。同一秒内把文件改成**长度相同**的另一份内容
    （"v1" → "v2" 这种），两个 key 都没变，import 机制会直接用
    __pycache__ 里的旧 .pyc——改了代码却完全不生效，还查不出原因。

    Studio 的三处热加载（tools/registry.py、tools/generated|custom/、
    plugins/）都对外承诺"改完下一次 Play 立刻生效"，所以统一走自己
    compile+exec，缓存根本不参与。

    模块名每次都换新的，同时绕开 sys.modules 缓存——两个项目里同名的
    registry.py / plugins/foo.py 不会互相串。
    """
    module_name = f"_studio_fresh_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None:
        raise ImportError(f"spec_from_file_location 失败: {path}")
    module = importlib.util.module_from_spec(spec)
    source = path.read_text(encoding="utf-8")
    sys.modules[module_name] = module
    try:
        exec(compile(source, str(path), "exec"), module.__dict__)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _load_tool_dir(
    root: Path, subdir: str
) -> tuple[dict[str, Callable], list[str]]:
    """自动发现 ``tools/<subdir>/*.py``，每个文件读它的 ``TOOL`` dict。

    形状见 toolgen.py：``{"name","description","parameters","callback"}``，与预制件
    清单一致。这里运行时只用到 name 和 callback，另外两个是给元 agent 看的。

    为什么是自动发现而不是往 registry.py 里追加注册（roadmap 的原话）：机器去改
    用户手写的文件是整个方案里最容易出事的一步——用户手动编辑过 registry.py 之
    后，AST 手术也好标记块也好都会翻车。不改它就没有这个风险，"重新生成
    generated/ 不覆盖 custom/" 也从"小心翼翼保证"变成结构性成立。顺带把一个现有
    缺口补上：custom/ 以前根本不会被自动加载，得手动在 registry.py 里 import。

    加载方式跟 load_project_plugins 完全同构：下划线开头的文件跳过，每次换新模块
    名绕开 sys.modules，单个文件坏掉只丢它自己。
    """
    directory = root / "tools" / subdir
    if not directory.is_dir():
        return {}, []

    tools: dict[str, Callable] = {}
    errors: list[str] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        label = f"tools/{subdir}/{path.name}"
        try:
            tool = getattr(_exec_module_fresh(path), "TOOL", None)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{label}: 加载失败: {exc}")
            continue

        if not isinstance(tool, dict):
            errors.append(
                f"{label}: 需要一个 TOOL dict"
                + ("" if tool is None else f"，实际是 {type(tool).__name__}")
            )
            continue
        name = tool.get("name")
        callback = tool.get("callback")
        if not isinstance(name, str) or not name:
            errors.append(f"{label}: TOOL['name'] 缺失或不是字符串")
            continue
        if not callable(callback):
            errors.append(f"{label}: TOOL['callback'] 不是可调用对象")
            continue
        tools[name] = callback
    return tools, errors


def load_tool_registry(root: Path) -> tuple[dict[str, Callable], str | None]:
    """加载工具：先铺一层 senza_studio_components 的预制件工具（Phase 4），
    项目自己 <project>/tools/registry.py 里同名的工具覆盖预制件（项目定制
    优先于通用预制件——跟其它"项目本地覆盖共享默认值"的场景是同一个道理）。

    每次 Play 都重新读一遍项目 registry.py（不缓存跨次 Play，也不缓存跨
    项目）——用 spec_from_file_location + 每次换一个新模块名绕开
    sys.modules 缓存，这样：(1) 开发者手改 registry.py 后下一次 Play 立刻
    生效，不用重启 Studio 后端；(2) 两个不同项目都可能有一个叫
    "registry.py" 的文件，固定用同一个模块名（比如 "tools.registry"）会
    导致后加载的项目复用前一个项目缓存在 sys.modules 里的模块，读到别的
    项目的工具。

    没有 registry.py 的项目不算错误——预制件仍然可用，只是没有项目自定义
    工具。项目 registry.py import 失败（语法错误、get_tools 不存在、返回
    值不是 dict）也不会丢掉已经加载好的预制件——只把这条消息带回去，由
    调用方决定要不要在某个具体 tool step 找不到工具时把它带上，而不是让
    整个 Play 在构建阶段就崩溃，也不该因为项目自己的 registry.py 坏了就
    连预制件都用不了。
    """
    tools = _load_prefab_tools()

    # 自动发现两个目录，generated 在前、custom 在后——同名时开发者手写的
    # custom/ 覆盖元 agent 生成的 generated/，这正是"重新生成不覆盖手写"的
    # 运行时保证。
    discovery_errors: list[str] = []
    for subdir in ("generated", "custom"):
        found, errors = _load_tool_dir(root, subdir)
        tools.update(found)
        discovery_errors.extend(errors)

    def _combine(extra: str | None) -> str | None:
        parts = [*discovery_errors, *( [extra] if extra else [] )]
        return "；".join(parts) if parts else None

    registry_path = root / "tools" / "registry.py"
    if not registry_path.exists():
        return tools, _combine(None)

    try:
        project_tools = _exec_module_fresh(registry_path).get_tools()
        if not isinstance(project_tools, dict):
            return (
                tools,
                _combine(
                    f"tools/registry.py 的 get_tools() 必须返回 dict，"
                    f"实际返回了 {type(project_tools).__name__}"
                ),
            )
        tools.update(project_tools)
        return tools, _combine(None)
    except Exception as exc:  # noqa: BLE001
        return tools, _combine(f"加载 tools/registry.py 失败: {exc}")


def _call_tool(callback: Callable, args: dict, ctx: dict) -> Any:
    """按回调实际接收几个位置参数决定传 (args) 还是 (args, ctx)——跟 senza
    自己的 create_tool 回调归一化是同一个思路，方便同一个函数以后不改
    签名就能直接被 senza.create_tool(callback=fn) 包装复用。"""
    try:
        n_params = len(inspect.signature(callback).parameters)
    except (TypeError, ValueError):
        n_params = 2
    if n_params <= 1:
        return callback(args)
    return callback(args, ctx)


def _normalize_tool_result(result: Any) -> tuple[dict, str, str | None]:
    """把 tool 回调的返回值统一成 (fields, output, route)，跟 agent step
    的 _extract_json_fields 是同一个模型：dict 返回值里非 "route" 的字段
    写进 context 供下游引用，"route" 字段（如果有）用来选边；纯文本返回
    值直接当展示输出，没有可写进 context 的字段。
    """
    if isinstance(result, dict):
        fields = {k: v for k, v in result.items() if k != "route"}
        route = result.get("route")
        output = result.get("output")
        if output is None:
            output = json.dumps(fields, ensure_ascii=False, default=str) if fields else ""
        return fields, output, route
    return {}, "" if result is None else str(result), None


def make_executor(
    stage_by_name: dict[str, dict],
    routes_by_name: dict[str, dict[str, str]],
    model: str,
    provider: Any,
    env: Any,
    engine_ref: dict[str, Any],
    tools_by_name: dict[str, Callable] | None = None,
    tools_load_error: str | None = None,
    plugins: list[Any] | None = None,
) -> Callable[[dict], dict]:
    """执行回调：支持 type: agent、checker、tool。

    engine_ref 是个可变的"晚绑定"容器——PlaySession.play() 构造 executor
    时 WorkflowEngine 还不存在（executor 得先造好才能传给 WorkflowEngine
    构造函数），engine 建好之后才把它塞进 engine_ref["engine"]。这样
    executor 自己才能在 agent step 算完结果后调用
    engine.set_context_variable(...) 往共享 context 写数据（ctx 参数本身
    只有 context 的只读快照，没有写入口）——实测同一个 engine 在自己的
    executor 回调里反过来调用它自己的 set_context_variable 不会死锁。

    短生命周期 harness——不带元 agent 的 spec/doc/prefab 工具或 strategy
    插件栈，那些是 Studio 自己的 meta agent 专属（agent.py）。这里跑的是
    spec 里被作者定义出来的 agent，项目自己的 plugins/（Phase 4）暂未接入。
    """

    def _write_context(output_key: str | None, fields: dict) -> None:
        engine = engine_ref.get("engine")
        if engine is None:
            return
        if output_key:
            engine.set_context_variable(output_key, fields.get("_output", ""))
        for key, value in fields.items():
            if key not in ("route", "_output"):
                engine.set_context_variable(key, value)

    def play_executor(ctx: dict) -> dict:
        step_id = ctx["step_id"]
        stage = stage_by_name.get(step_id)
        if stage is None:
            return {
                "output": f"Error: unknown step '{step_id}'",
                "structured": {"route_key": "error"},
            }
        stage_type = stage.get("type")

        if stage_type == "checker":
            # 人工审批门——不调用 LLM，只看 submit_decision() 有没有写过
            # 决定。没有就让 judge pause；有就直接按决定路由。
            decision = ctx["context"].get(decision_context_key(step_id))
            if decision is None:
                # stage.message 是 spec 作者给这道审批门写的说明（能力组件的
                # title 参数也落在这里），有就显示它——审批人看到"退货审批：
                # 金额超过 500 需人工确认"比看到一句通用的"等待人工审批"
                # 有用得多。
                return {
                    "output": stage.get("message") or "等待人工审批…",
                    "structured": {"route_key": PENDING_APPROVAL},
                }
            return {
                "output": f"人工审批结果: {decision}",
                "structured": {"route_key": decision},
            }

        if stage_type == "tool":
            # tools_load_error 只说明项目自己的 tools/registry.py 没加载成功
            # ——不代表完全没有工具可用（预制件那一层是独立加载的，见
            # load_tool_registry），所以这里不再无条件让每个 tool step 都
            # 失败，只在真的找不到这个具体工具时才把这条消息带上，帮助
            # 排查到底是"工具压根不存在"还是"项目 registry.py 坏了"。
            tool_ref = stage.get("tool")
            if not tool_ref:
                return {
                    "output": "Error: step has no bound tool (use bind_tool)",
                    "structured": {"route_key": "error"},
                }
            callback = (tools_by_name or {}).get(tool_ref)
            if callback is None:
                reason = f"tool '{tool_ref}' not found (checked prefabs and project tools/registry.py)"
                if tools_load_error:
                    reason += f" — 项目 tools/registry.py 加载失败: {tools_load_error}"
                return {"output": f"Error: {reason}", "structured": {"route_key": "error"}}

            args = render_tool_args(stage.get("tool_args") or {}, ctx["context"])
            try:
                raw_result = _call_tool(callback, args, {"step_id": step_id})
            except Exception as exc:  # noqa: BLE001
                return {"output": f"Error: {exc}", "structured": {"route_key": "error"}}

            fields, output, route = _normalize_tool_result(raw_result)
            routes = sorted(routes_by_name.get(step_id, {}).keys())
            if len(routes) > 1:
                route_key = route if route in routes else "error"
            else:
                route_key = routes[0] if routes else "success"

            _write_context(stage.get("output_key"), {**fields, "_output": output})

            return {
                "output": output,
                "structured": {
                    "route_key": route_key,
                    "fields": fields,
                    "_debug": {"tool": tool_ref, "args": args},
                },
            }

        if stage_type != "agent":
            return {
                "output": f"Error: unknown step type '{stage_type}'",
                "structured": {"route_key": "error"},
            }

        prompt_template = stage.get("prompt_template", "")
        prompt = render_prompt_template(prompt_template, ctx["context"])

        # 单一路由（或没声明路由，比如直接接 terminal）不用 LLM 决策，
        # 直接走那条边；多路由（结构化路由 step）才要求 LLM 在回答末尾声明
        # 选中哪条，并且 V1 起要经过确定性验证。
        routes = sorted(routes_by_name.get(step_id, {}).keys())
        is_structured = len(routes) > 1
        if is_structured:
            # 重试反馈：只读自己的 step-scoped key，读完立刻清除——生命周期
            # 恰好覆盖这一次（重试）prompt，不会泄漏到其它 step 或更晚的重入。
            feedback_key = validation_feedback_key(step_id)
            feedback = ctx["context"].get(feedback_key)
            if feedback is not None:
                engine = engine_ref.get("engine")
                if engine is not None:
                    engine.set_context_variable(feedback_key, None)
                prompt = _append_validation_feedback(prompt, str(feedback))
            prompt = _append_routing_instruction(prompt, routes)

        # 项目插件集（设计文档 §7 的"插件集隔离"）：只装当前项目 plugins/
        # 里的插件，不注入 Studio 元 agent 那一套。装的是项目自己的东西，
        # 所以导出之后 agent step 的行为跟在 Studio 里跑是一致的。
        #
        # 结构化路由 step 的请求期 fallback（有界，恰好 1 次额外请求）：
        # 有的 OpenAI 兼容端点会对 {"type":"json_object"} 返回 400（invalid
        # request）。这类错误在 harness 里走 error_message → RuntimeError
        # （类型上无法与其它 provider 错误区分），只能按错误文本识别：包含
        # "invalid request" 且提到 "response_format" 才触发。命中则重建不带
        # response_format 的 harness 重跑一次。任何其它异常原样上抛——绝不
        # 吞掉无关的 provider/model 错误。这与"模型输出验证失败"的一次修正
        # 重试是两个独立机制，互不消耗。单路由 step 不设 response_format，
        # 单次运行，行为与从前一致。
        attempts = (True, False) if is_structured else (False,)
        for use_response_format in attempts:
            builder = senza.HarnessBuilder(model).provider("*", provider).env(env)
            for plugin in plugins or []:
                builder = builder.plugin(plugin)
            if use_response_format:
                # 强化，不是正确性来源：response_format 只影响请求约束，
                # 正确性由提示词 + 解析 + 验证保证。
                try:
                    builder = builder.response_format(
                        senza.create_json_object_format()
                    )
                except Exception:  # noqa: BLE001
                    pass
            harness = builder.build()
            try:
                raw_output, tool_calls_count = _run_agent_step(
                    harness, prompt, ctx["emit"]
                )
                break
            except Exception as exc:  # noqa: BLE001
                text = str(exc)
                is_format_rejection = (
                    "invalid request" in text.lower()
                    and "response_format" in text
                )
                if not is_format_rejection or not use_response_format:
                    return {
                        "output": f"Error: {exc}",
                        "structured": {"route_key": "error"},
                    }
                # 命中 format 拒绝 → 落到第二趟（不带 response_format）。

        # usage() 是 harness 累计值，但这是个一次性、单轮 prompt 用完就扔的
        # harness（每个 agent step 一个新的），累计值就是这一轮的值。
        try:
            usage = harness.usage()
        except Exception:  # noqa: BLE001
            usage = None

        # 不管路由数量，都尝试从回答里摘 JSON 字段——分类步骤常常在
        # {"route": ...} 之外还顺带吐 summary/classification 这类给下游用
        # 的字段，即使这个 step 本身只有一条路由也一样。
        fields, output = _extract_json_fields(raw_output)

        if len(routes) <= 1:
            # 单路由/对话 step：不验证、不重试——现有行为原样保留。
            route_key = routes[0] if routes else "success"
            _write_context(stage.get("output_key"), {**fields, "_output": output})
            return {
                "output": output,
                "structured": {
                    "route_key": route_key,
                    "fields": fields,
                    "_debug": {
                        "prompt": prompt,
                        "tool_calls_count": tool_calls_count,
                        "usage": usage,
                    },
                },
            }

        # 结构化路由 step（V1）：确定性验证先于路由选择。
        attempt = 1 if ctx["context"].get(validation_feedback_key(step_id)) is None else 2
        validation = _validate_structured(fields, raw_output, routes, attempt)
        if not validation.ok:
            # 失败：任何模型产物都不进共享 context（提取的字段、route、
            # output_key 一律不写）——被拒绝的输出只能出现在本次返回值的
            # _debug.prompt / structured 之外，重试的修正提示由 judge 写入
            # step-scoped 的 _validation_feedback key。route_key="error" 仅
            # 是引擎路由兼容用的内部值，真正的诊断在 _validation 里。
            return {
                "output": output,
                "structured": {
                    "route_key": "error",
                    "fields": {},
                    "_validation": validation.to_dict(),
                    "_debug": {
                        "prompt": prompt,
                        "tool_calls_count": tool_calls_count,
                        "usage": usage,
                    },
                },
            }

        route_key = fields["route"]
        _write_context(stage.get("output_key"), {**fields, "_output": output})

        return {
            "output": output,
            "structured": {
                "route_key": route_key,
                # GameView 的 table/chart 卡片用——spec 作者在 ui.fields 里点名
                # 要展示哪些字段，这里把这一轮实际算出来的字段值原样带上。
                "fields": fields,
                # Inspector 运行态用——prompt 是真正发给模型的完整文本（包含
                # 多路由时追加的 routing 指令），不是没渲染过的 prompt_template。
                "_debug": {
                    "prompt": prompt,
                    "tool_calls_count": tool_calls_count,
                    "usage": usage,
                },
            },
        }

    return play_executor


class PlaySession:
    """管理一次 Play 运行的 WorkflowEngine 生命周期。

    与 StudioAgent 对称：__init__ 只存引用，play() 才真正 build engine
    并在后台线程跑 .run()。
    """

    def __init__(
        self,
        root: Path | None = None,
        spec: dict | None = None,
        model: str = "",
        provider: Any = None,
    ) -> None:
        """root 是项目根目录（tools/ 和 plugins/ 就在它下面），spec 是**编辑态**
        的 dict（组件还没展开，play() 里才 preprocess）。

        不收 Studio 的 Project/StudioConfig：运行时要能被导出的项目直接用，
        那边没有 Studio 的任何东西。Studio 侧由 studio_backend/play.py 那层
        薄适配把 Project/StudioConfig 翻成这四个参数。
        """
        # 四个入参都允许先空着、到 play() 之前再填：Studio 那层适配就是这么用的
        # ——它要保持"构造时只存引用、play() 那一刻才读"的惰性，这样构造之后、
        # 真正跑之前改的 spec 也能生效。play() 里会检查它们齐了没有。
        self._root = Path(root) if root is not None else None
        self._spec_dict = spec
        self._model = model
        self._provider = provider
        self._engine: Any = None
        # play() 里填：这次运行真正执行的 spec（组件已展开）
        self.runtime_spec: dict | None = None
        # play() 里填：plugins/ 里加载失败的插件（非致命，展示给用户）
        self.plugin_errors: list[str] = []
        self._engine_ref: dict[str, Any] = {}
        self._thread: threading.Thread | None = None
        self.run_error: BaseException | None = None
        # ── 平台级执行护栏状态（见模块顶常量）─────────────────────────
        # 累计活跃执行秒数：run() 线程活着才算。暂停/HITL 不计入。
        self._active_accum: float = 0.0
        # 本轮 run() 的开始时刻（time.monotonic()）；线程不在跑时为 None。
        self._active_since: float | None = None
        # 保护累计账本的锁：_run_once 收尾与 stop() 都会关闭账本，防双计。
        self._active_lock = threading.RLock()
        # 剩余预算的倒计时器；到点调 stop(_TIMEOUT_REASON)。
        self._timeout_timer: threading.Timer | None = None
        self._timed_out = False
        # 每个执行段一个 epoch：旧 run 线程/旧 timer 不得关闭新段的账本。
        self._run_epoch = 0
        # 用户是不是在"手动逐步执行"——Step 按钮或 Play Paused 打开它，
        # Resume 按钮关掉它。submit_decision（checker 审批）需要知道这个：
        # 不看这个标志的话，用户在单步模式下走到一个 checker、点了
        # approve，resume() 之后会一路跑到底，而不是像其它 step 一样审批
        # 完也只跑这一步就重新暂停——审批本质上也是"往前走了一步"，理应
        # 遵守同一个单步节奏（亲测复现过这个 bug）。
        self._step_mode = False

    def play(
        self, inputs: dict[str, str] | None = None, start_paused: bool = False
    ) -> None:
        """构建 WorkflowEngine。不启动 .run()——调用方必须先 events() 订阅，
        再调用 start()，否则 tokio broadcast 会丢掉 run() 线程里发生太快
        （比如立刻 fail 的 step，没有真实 LLM 调用）的早期事件：broadcast
        只推送给"已订阅"的 receiver，订阅前发的消息一律丢弃，不会缓冲。

        inputs 是入口 step 的种子输入（见 get_entry_inputs），构建完 engine
        后立刻用 set_context_variable 写入共享上下文，让入口 step 的
        prompt_template 里的 {{field}} 占位符能被替换。

        start_paused=True 时提前武装 pause（构造完 engine、还没 run() 过
        就调 engine.pause()）——亲测 run() 的 pause 检查点在"当前 step 的
        transition 已经 apply 之后"，不存在"一个 step 都不跑就暂停"这种
        粒度；能做到的最好效果是保证恰好只跑第一个 step 就自动暂停，不管
        流程本身跑多快，用户都能在第一个 step 后拿到控制权，用 Step 逐步
        往下走，而不是像纯靠手动点 Pause 那样可能因为跑得太快漏过好几个
        step 才追上（用户原话："even then the agent would have gone
        through multiple steps if flow is fast enough"）。这次 pause 之后
        的 Step/Resume 走的是已有的 step()/resume_run()，不需要额外改动。
        """
        if self._root is None or self._spec_dict is None:
            raise RuntimeError(
                "PlaySession 还没绑定 root/spec——构造时没给就得在 play() 之前填上"
            )

        # 编辑态 spec → 运行态 spec：把 component 引用展开成真正的 step
        # （见 preprocess.py）。放在最前面，后面所有环节——路由表、executor、
        # WorkflowEngine——看到的都是展开后的 step，不需要各自懂组件语义。
        spec_dict = preprocess_spec(self._spec_dict)
        # 前端要按"实际在跑的 step"来查路由和 ui 配置——能力组件展开后的
        # step 名（gate_review）在编辑态 spec 里根本不存在，前端拿编辑态
        # spec 查会一无所获（审批按钮渲染不出来，Play 直接卡死）。
        self.runtime_spec = spec_dict
        stage_by_name, routes_by_name = build_route_maps(spec_dict)
        provider = self._provider
        env = senza.create_os_env(str(self._root))
        # 每次 Play 都重新读一遍项目的 tools/registry.py（见 load_tool_registry
        # 注释）——不是只加载一次缓存住，开发者手改工具代码后不用重启后端。
        tools_by_name, tools_load_error = load_tool_registry(self._root)
        # 插件加载错误不阻断 Play（插件是加法，缺一个只是少一批工具），但
        # 要让用户看见——不然 agent 莫名其妙少了工具却没有任何提示。
        plugins, self.plugin_errors = load_project_plugins(self._root)

        executor = make_executor(
            stage_by_name,
            routes_by_name,
            self._model,
            provider,
            env,
            self._engine_ref,
            tools_by_name,
            tools_load_error,
            plugins,
        )
        judge = make_judge(routes_by_name, self._engine_ref)

        # 平台护栏 1：引擎级 step_history 上限（含所有 Retry 重跑），超过 →
        # Failed("max_steps (75) exceeded")。必须在此处、首次 run() 之前
        # 设置——engine 一旦被 run() 共享，with_max_steps 会拒绝。
        # 重复 play() 会重建 engine，这里是唯一也是每次都会经过的入口。
        self._engine = senza.WorkflowEngine(
            spec_dict, provider, self._model, senza.create_judge(judge), env=env
        ).with_max_steps(PLAY_MAX_STEPS)
        self._engine.with_executor("eda_executor", senza.create_executor(executor))
        # 平台护栏 2 记账：每次 play() 重置本轮预算（同一 PlaySession 重放
        # 是一次全新运行，不是 resume）。
        self._reset_time_budget()
        # 晚绑定：executor 闭包在 engine 造好之前就已经创建，这里把真正的
        # engine 塞进去，让它自己在 agent step 算完后能调用
        # set_context_variable 往 context 写数据（详见 make_executor 注释）。
        self._engine_ref["engine"] = self._engine

        for key, value in (inputs or {}).items():
            self._engine.set_context_variable(key, value)

        self._step_mode = start_paused
        if start_paused:
            self._engine.pause("start paused")

    # ── 平台护栏 2：累计活跃执行时间（暂停/HITL 不计入，跨 resume 累计）──

    def _reset_time_budget(self) -> None:
        """play() 重放时调用：清空累计账本，新一轮 Play 拿到完整预算。"""
        with self._active_lock:
            self._disarm_timer_locked()
            self._run_epoch += 1
            self._active_accum = 0.0
            self._active_since = None
        self._timed_out = False

    def _disarm_time_budget(self, run_epoch: int | None = None) -> None:
        """run() 收尾（正常结束/pause/异常）与 stop() 共用的收账入口。
        锁保证"关计时器 + 结算账本"只发生一次；run_epoch 不匹配时说明
        这是旧执行段的迟到收尾，不能影响新执行段。"""
        with self._active_lock:
            if run_epoch is not None and run_epoch != self._run_epoch:
                return
            self._settle_time_budget_locked()

    def _settle_time_budget_locked(self) -> None:
        """须持 _active_lock 调用。关闭当前计时器并结算当前活跃段。"""
        self._disarm_timer_locked()
        if self._active_since is not None:
            self._active_accum += time.monotonic() - self._active_since
            self._active_since = None

    def _disarm_timer_locked(self) -> None:
        """须持 _active_lock 调用。取消当前计时器；迟到回调由 epoch 守卫拦下。"""
        timer = self._timeout_timer
        self._timeout_timer = None
        if timer is not None:
            timer.cancel()

    def _arm_time_budget_locked(self, run_epoch: int) -> None:
        """须持 _active_lock 调用。按剩余预算武装本 epoch 的计时器。"""
        remaining = PLAY_MAX_ACTIVE_SECONDS - self._active_accum
        if remaining <= 0:
            # 预算已在之前的活跃段耗尽（防御分支；start() 已先行拦截）。
            self._timed_out = True
            return
        self._active_since = time.monotonic()
        timer = threading.Timer(
            remaining, self._on_time_budget_expired, args=(run_epoch,)
        )
        timer.daemon = True
        timer.start()
        self._timeout_timer = timer

    def _on_time_budget_expired(self, run_epoch: int | None = None) -> None:
        """超时回调：复用 stop() → engine.cancel() 终止运行。stop() 内部
        的 state 守卫保证运行已自然结束时（succeeded/failed）不会覆盖
        真实结果；跑得快于预算的运行根本不会等到这一枪。epoch 守卫防止
        已被 start() 取代的旧 timer 误杀新执行段。"""
        with self._active_lock:
            if run_epoch is None:
                run_epoch = self._run_epoch
            if run_epoch != self._run_epoch:
                return
            self._timed_out = True
            self.stop(_TIMEOUT_REASON)

    def _run_once(self, run_epoch: int) -> None:
        """跑一次 .run()（初次启动或 pause 后 resume 都调这个）。

        engine.run() 在 workflow 失败时 raise senza.SenzaError（比如
        judge 返回 "fail:..."）——记到 run_error，让 run_play_streaming
        能把清晰的 error 消息转发给前端，而不是让线程默认打印一个吓人的
        未捕获异常 traceback 然后悄悄退出。

        WorkflowPausedError 单独处理：judge 返回 "pause:..." 时 run() 也是
        靠 raise 这个异常来通知调用方，但这是正常的"等人工审批"状态，不是
        错误——不该记进 run_error，也不该打印成报错。
        """
        try:
            self._engine.run()
        except senza.WorkflowPausedError:
            pass
        except BaseException as exc:  # noqa: BLE001
            self.run_error = exc
            print(f"Play run error: {exc}", file=sys.stderr)
        finally:
            # 无论正常结束、pause 还是异常都收账——暂停/HITL 的时间从此
            # 不再累计（线程已退出），resume 后 start() 会按剩余预算重新
            # 武装计时器。finally 与 stop() 里的收账经 _active_lock 串行，
            # 不会双计。
            self._disarm_time_budget(run_epoch)

    def start(self) -> None:
        """在后台线程启动 .run()。必须在 events() 订阅之后调用（见 play()）。

        预算已耗尽（之前的活跃时间用满 15 分钟）时拒绝启动并直接终止——
        resume/step/审批 submit 都经由这里，守一处即覆盖所有重启路径。
        """
        if self._engine is None:
            raise RuntimeError("Engine not built. Call play() first.")
        with self._active_lock:
            self._settle_time_budget_locked()
            self._run_epoch += 1
            run_epoch = self._run_epoch
            if self._active_accum >= PLAY_MAX_ACTIVE_SECONDS:
                self._timed_out = True
                self._engine.cancel(_TIMEOUT_REASON)
                return
            self._arm_time_budget_locked(run_epoch)
        thread = threading.Thread(
            target=self._run_once, args=(run_epoch,), daemon=True
        )
        self._thread = thread
        self._thread.start()

    def submit_decision(self, step_id: str, decision: str) -> None:
        """人工审批提交后调用：把决定写进 context，resume 引擎，再跑一次
        run()——resume() 本身只翻内部状态，不会真的继续执行，得再调一次
        run()（亲测行为）；同一个 .subscribe() 迭代器在多次 run() 之间
        持续有效，不需要重新订阅。checker executor 在下一次被调用时会看到
        这个 context 变量，不再返回 pending，从而正常路由下去。

        _step_mode 时（用户在用 Play Paused/Step 手动逐步执行）额外重新
        武装一次 pause——跟 step() 同样的 resume-then-pause 顺序（resume()
        会清空 pause_requested，必须先 resume 再 pause，不然刚设的标志会
        被清掉）。不这样做的话，审批完这一步会一路跑到底，把"逐步执行"
        的节奏在 checker 这里打断（亲测复现过：Play Paused 一路 Step 到
        审批节点，点 approve 后直接冲到终点）——审批本身也是往前走了一步，
        应该跟其它 step 一样只跑这一步就再暂停。
        """
        if self._engine is None:
            raise RuntimeError("Engine not built. Call play() first.")
        # 状态守卫（与 resume_run/step 的守卫同一哲学）：决定只在引擎仍在
        # 等待审批（paused）或处于可恢复失败（failed —— Runtime resume 显式
        # 支持 Failed → Paused 恢复）时有意义。其它状态都是过期决定——典型
        # 场景：15 分钟活跃预算在 HITL 等待期间到期，超时已把引擎置为
        # Cancelled，而审批卡片还挂在界面上。过期决定必须无害：不 raise、
        # 不改状态、不重启（Cancelled 是终态，Runtime resume 会以
        # InvalidStatus 拒绝 —— 那个异常会把 WS 连接打死）。
        if self._engine.state() not in ("paused", "failed"):
            return
        try:
            self._engine.set_context_variable(decision_context_key(step_id), decision)
            self._engine.resume()
        except senza.HarnessStateError:
            # 竞争窗口：守卫读到 paused/failed 之后、resume 执行前，stop()
            #（用户 Stop 或 15 分钟超时计时器线程）已把引擎终态化。此时决定
            # 已经过期——静默放弃即可。异常绝不能向上抛：本方法在 WS 事件
            # 循环线程执行（app.py 无 try/except），HarnessStateError 会把
            # 整个连接打死（守卫只能缩小窗口，不能消除）。
            return
        if self._step_mode:
            self._engine.pause("single-step (after approval)")
        self.run_error = None
        self.start()

    def request_pause(self, reason: str = "user pause") -> None:
        """控制条的 Pause 按钮用——跟 checker 的 pause 是两回事：这个是
        engine.pause()（亲测：非阻塞，只是设个标志位，run() 在当前 step
        的 transition 已经 apply 之后、下一个 step 开始之前才检查并消费），
        不是 judge 返回 "pause:..."。区别很关键——judge 那种 pause 因为
        路由还没定下来，resume 后会重新调用"当前"这个 step 的 executor；
        这个 engine.pause() 因为 transition 已经 apply 过了，resume 后
        会正常执行"下一个" step，不会把刚跑完、可能有副作用（发邮件、
        真实 LLM 调用）的 step 重跑一遍。只在真的在跑的时候才有意义。
        """
        if self._engine is not None and self._engine.state() == "running":
            self._engine.pause(reason)

    def resume_run(self) -> None:
        """控制条的 Resume 按钮用——从任意原因的暂停（checker 或手动
        pause）恢复成正常连续运行，不重新武装暂停标志。关掉 _step_mode——
        用户明确选择"别再逐步走了，跑到底"，之后再遇到 checker 审批
        （submit_decision）也不该再帮它重新暂停。"""
        if self._engine is not None and self._engine.state() == "paused":
            self._step_mode = False
            self._engine.resume()
            self.run_error = None
            self.start()

    def step(self, reason: str = "single-step") -> None:
        """控制条的 Step 按钮用——从暂停状态恰好再跑一个 step 就自动
        重新暂停。必须先 resume() 再 pause()：resume() 会顺带把
        pause_requested 标志清空（亲测行为），顺序反过来的话这里刚设的
        标志会被 resume() 自己清掉，run() 就会一路跑到底而不是只跑一步。

        打开 _step_mode——之后如果走到 checker 审批（submit_decision），
        也会记得再帮它重新暂停一次，而不是让审批打断"逐步执行"的节奏。
        """
        if self._engine is not None and self._engine.state() == "paused":
            self._step_mode = True
            self._engine.resume()
            self._engine.pause(reason)
            self.run_error = None
            self.start()

    def stop(self, reason: str = "user stop") -> None:
        """取消运行中的 engine。项目状态收尾（playing -> editing）由调用方
        （ws.py 的 _finalize_play）负责，不在这里做——Stop 可能是在运行
        自然结束（succeeded/failed）之后才点的，那种情况下 engine 已经
        跑完，.cancel() 会把真实结果悄悄改写成 "cancelled"（亲测行为），
        所以只在还真的在跑的时候才调用它。

        手动 Stop（与超时回调共用本方法）同时收账并解除计时器——与
        _run_once 的 finally 经 _active_lock 串行，不会双计活跃时间；
        已到终态时这里不做事，迟到的超时回调因此无法覆盖真实结果。
        """
        if self._engine is not None and self._engine.state() in (
            "idle",
            "running",
            "paused",
        ):
            self._engine.cancel(reason)
        self._disarm_time_budget()

    def events(self, timeout_ms: int = 5000, max_consecutive_timeouts: int = 999):
        if self._engine is None:
            raise RuntimeError("Play not started. Call play() first.")
        return self._engine.subscribe(
            timeout_ms=timeout_ms, max_consecutive_timeouts=max_consecutive_timeouts
        )

    def state(self) -> str:
        if self._engine is None:
            return "idle"
        return self._engine.state()
