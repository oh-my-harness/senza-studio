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

import importlib.util
import inspect
import json
import re
import sys
import threading
import uuid
from typing import Any, Callable

import senza

from .config import StudioConfig
from .project import Project
from .spec import Spec

_TERMINAL_TYPES = frozenset({"settled", "aborted", "error", "agent_end"})
_SKIP_TYPES = frozenset({"timeout"})


def _create_provider(config: StudioConfig) -> Any:
    api_key = config.api_key
    api_base = config.api_base if config.api_base else None
    return senza.providers.openai(api_key=api_key, base_url=api_base)


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


def render_tool_args(tool_args: dict, context: dict) -> dict:
    """渲染 tool step 的 tool_args——跟 prompt_template 一样用 {{var}} 从
    context 取值，但作用对象是一个 dict（每个字符串 value 各自替换一次），
    不是一整段模板。非字符串 value（作者直接写死的数字/布尔等）原样传递。
    没声明 tool_args 的 step 得到空 dict——工具需要的参数必须显式声明，
    不能隐式拿整个 context（跟 agent step 只能通过 prompt_template 里的
    {{var}} 声明输入是同一个原则）。
    """
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
    """
    stages = spec_dict.get("stages", [])
    if not stages:
        return []
    template = stages[0].get("prompt_template", "")
    seen: list[str] = []
    for match in _TEMPLATE_VAR_RE.finditer(template):
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


def make_judge(routes_by_name: dict[str, dict[str, str]]) -> Callable[[dict], str]:
    """路由回调：把 executor 返回的 route_key 翻成 senza judge 的 transition 字符串。"""

    def play_judge(ctx: dict) -> str:
        structured = ctx.get("structured") or {}
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


def _run_agent_step(harness: Any, prompt: str, emit: Any) -> str:
    """驱动一个短生命周期 harness 跑一轮 prompt，streaming 转发到 emit。

    与 ws.py 的 run_prompt_streaming 同一模式：prompt() 阻塞到整轮结束，
    必须放到独立线程，当前线程负责同步迭代 events() 拿 streaming token。
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
        elif etype in _TERMINAL_TYPES:
            break

    prompt_thread.join(timeout=125)
    if errors:
        raise errors[0]
    return "".join(text_parts)


# 匹配回答里的扁平 JSON 对象（不支持嵌套花括号）——LLM 按我们的指示只会
# 在末尾吐一个简单对象，比如 {"route": "complaint", "summary": "..."}。
# 用来既提取路由标记，也提取其它想传给下游 step 的结构化字段。
_JSON_BLOB_RE = re.compile(r"\{[^{}]*\}")


def _append_routing_instruction(prompt: str, routes: list[str]) -> str:
    """多路由时，要求 LLM 在回答末尾用一行 JSON 声明选中的路由。

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
        f"If your instructions above already asked for other JSON fields (e.g. a "
        f"summary), keep them in this same JSON object alongside \"route\" — "
        f"do not drop them."
    )


def _extract_json_fields(output: str) -> tuple[dict, str]:
    """找输出里最后一个扁平 JSON 对象，解析出字段，并从展示文本里去掉这段。

    找不到、解析失败、或解析出来不是 dict，都原样返回（fields={}）——不是
    每个 agent step 都会吐 JSON，纯文字回复（比如草拟的客服回信）应该
    完全不受影响。
    """
    last_match = None
    for m in _JSON_BLOB_RE.finditer(output):
        last_match = m
    if last_match is None:
        return {}, output
    try:
        fields = json.loads(last_match.group(0))
    except (json.JSONDecodeError, ValueError):
        return {}, output
    if not isinstance(fields, dict):
        return {}, output
    clean_output = (output[: last_match.start()] + output[last_match.end() :]).strip()
    return fields, clean_output


def load_tool_registry(project: Project) -> tuple[dict[str, Callable], str | None]:
    """加载 <project>/tools/registry.py 的 get_tools()。

    每次 Play 都重新读一遍（不缓存跨次 Play，也不缓存跨项目）——用
    spec_from_file_location + 每次换一个新模块名绕开 sys.modules 缓存，
    这样：(1) 开发者手改 registry.py 后下一次 Play 立刻生效，不用重启
    Studio 后端；(2) 两个不同项目都可能有一个叫 "registry.py" 的文件，
    固定用同一个模块名（比如 "tools.registry"）会导致后加载的项目复用
    前一个项目缓存在 sys.modules 里的模块，读到别的项目的工具。

    没有 registry.py 的项目不算错误——只是没法用 tool step（返回空
    dict，等真的有 tool step 引用不存在的工具时再报错）。import 失败
    （语法错误、get_tools 不存在、返回值不是 dict）会被捕获成一条错误
    消息而不是直接抛出，让 PlaySession.play() 能正常往下走，把这条消息
    原样透传给每一个用到 tool step 的报错里，而不是让整个 Play 在构建
    阶段就崩溃。
    """
    registry_path = project.path / "tools" / "registry.py"
    if not registry_path.exists():
        return {}, None

    module_name = f"_studio_tool_registry_{uuid.uuid4().hex}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, registry_path)
        if spec is None or spec.loader is None:
            return {}, "无法加载 tools/registry.py: spec_from_file_location 失败"
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            tools = module.get_tools()
        finally:
            sys.modules.pop(module_name, None)
        if not isinstance(tools, dict):
            return (
                {},
                f"tools/registry.py 的 get_tools() 必须返回 dict，"
                f"实际返回了 {type(tools).__name__}",
            )
        return tools, None
    except Exception as exc:  # noqa: BLE001
        return {}, f"加载 tools/registry.py 失败: {exc}"


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
                return {
                    "output": "等待人工审批…",
                    "structured": {"route_key": PENDING_APPROVAL},
                }
            return {
                "output": f"人工审批结果: {decision}",
                "structured": {"route_key": decision},
            }

        if stage_type == "tool":
            if tools_load_error:
                return {
                    "output": f"Error: {tools_load_error}",
                    "structured": {"route_key": "error"},
                }
            tool_ref = stage.get("tool")
            if not tool_ref:
                return {
                    "output": "Error: step has no bound tool (use bind_tool)",
                    "structured": {"route_key": "error"},
                }
            callback = (tools_by_name or {}).get(tool_ref)
            if callback is None:
                return {
                    "output": f"Error: tool '{tool_ref}' not found in tools/registry.py",
                    "structured": {"route_key": "error"},
                }

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

            return {"output": output, "structured": {"route_key": route_key}}

        if stage_type != "agent":
            return {
                "output": f"Error: unknown step type '{stage_type}'",
                "structured": {"route_key": "error"},
            }

        prompt_template = stage.get("prompt_template", "")
        prompt = render_prompt_template(prompt_template, ctx["context"])

        # 单一路由（或没声明路由，比如直接接 terminal）不用 LLM 决策，
        # 直接走那条边；多路由才要求 LLM 在回答末尾声明选中哪条。
        routes = sorted(routes_by_name.get(step_id, {}).keys())
        if len(routes) > 1:
            prompt = _append_routing_instruction(prompt, routes)

        harness = senza.HarnessBuilder(model).provider("*", provider).env(env).build()
        try:
            raw_output = _run_agent_step(harness, prompt, ctx["emit"])
        except Exception as exc:  # noqa: BLE001
            return {"output": f"Error: {exc}", "structured": {"route_key": "error"}}

        # 不管路由数量，都尝试从回答里摘 JSON 字段——分类步骤常常在
        # {"route": ...} 之外还顺带吐 summary/classification 这类给下游用
        # 的字段，即使这个 step 本身只有一条路由也一样。
        fields, output = _extract_json_fields(raw_output)

        if len(routes) > 1:
            route_key = fields.get("route")
            if route_key not in routes:
                route_key = "error"
        else:
            route_key = routes[0] if routes else "success"

        _write_context(stage.get("output_key"), {**fields, "_output": output})

        return {"output": output, "structured": {"route_key": route_key}}

    return play_executor


class PlaySession:
    """管理一次 Play 运行的 WorkflowEngine 生命周期。

    与 StudioAgent 对称：__init__ 只存引用，play() 才真正 build engine
    并在后台线程跑 .run()。
    """

    def __init__(self, config: StudioConfig, project: Project, spec: Spec) -> None:
        self._config = config
        self._project = project
        self._spec = spec
        self._engine: Any = None
        self._engine_ref: dict[str, Any] = {}
        self._thread: threading.Thread | None = None
        self.run_error: BaseException | None = None

    def play(self, inputs: dict[str, str] | None = None) -> None:
        """构建 WorkflowEngine。不启动 .run()——调用方必须先 events() 订阅，
        再调用 start()，否则 tokio broadcast 会丢掉 run() 线程里发生太快
        （比如立刻 fail 的 step，没有真实 LLM 调用）的早期事件：broadcast
        只推送给"已订阅"的 receiver，订阅前发的消息一律丢弃，不会缓冲。

        inputs 是入口 step 的种子输入（见 get_entry_inputs），构建完 engine
        后立刻用 set_context_variable 写入共享上下文，让入口 step 的
        prompt_template 里的 {{field}} 占位符能被替换。
        """
        spec_dict = self._spec.get_current_spec()
        stage_by_name, routes_by_name = build_route_maps(spec_dict)
        provider = _create_provider(self._config)
        env = senza.create_os_env(str(self._project.path))
        # 每次 Play 都重新读一遍项目的 tools/registry.py（见 load_tool_registry
        # 注释）——不是只加载一次缓存住，开发者手改工具代码后不用重启后端。
        tools_by_name, tools_load_error = load_tool_registry(self._project)

        executor = make_executor(
            stage_by_name,
            routes_by_name,
            self._config.model,
            provider,
            env,
            self._engine_ref,
            tools_by_name,
            tools_load_error,
        )
        judge = make_judge(routes_by_name)

        self._engine = senza.WorkflowEngine(
            spec_dict, provider, self._config.model, senza.create_judge(judge), env=env
        )
        self._engine.with_executor("eda_executor", senza.create_executor(executor))
        # 晚绑定：executor 闭包在 engine 造好之前就已经创建，这里把真正的
        # engine 塞进去，让它自己在 agent step 算完后能调用
        # set_context_variable 往 context 写数据（详见 make_executor 注释）。
        self._engine_ref["engine"] = self._engine

        for key, value in (inputs or {}).items():
            self._engine.set_context_variable(key, value)

        self._project.meta["status"] = "playing"
        self._project._save_meta()

    def _run_once(self) -> None:
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

    def start(self) -> None:
        """在后台线程启动 .run()。必须在 events() 订阅之后调用（见 play()）。"""
        if self._engine is None:
            raise RuntimeError("Engine not built. Call play() first.")
        self._thread = threading.Thread(target=self._run_once, daemon=True)
        self._thread.start()

    def submit_decision(self, step_id: str, decision: str) -> None:
        """人工审批提交后调用：把决定写进 context，resume 引擎，再跑一次
        run()——resume() 本身只翻内部状态，不会真的继续执行，得再调一次
        run()（亲测行为）；同一个 .subscribe() 迭代器在多次 run() 之间
        持续有效，不需要重新订阅。checker executor 在下一次被调用时会看到
        这个 context 变量，不再返回 pending，从而正常路由下去。
        """
        if self._engine is None:
            raise RuntimeError("Engine not built. Call play() first.")
        self._engine.set_context_variable(decision_context_key(step_id), decision)
        self._engine.resume()
        self.run_error = None
        self.start()

    def stop(self, reason: str = "user stop") -> None:
        """取消运行中的 engine。项目状态收尾（playing -> editing）由调用方
        （ws.py 的 _finalize_play）负责，不在这里做——Stop 可能是在运行
        自然结束（succeeded/failed）之后才点的，那种情况下 engine 已经
        跑完，.cancel() 会把真实结果悄悄改写成 "cancelled"（亲测行为），
        所以只在还真的在跑的时候才调用它。
        """
        if self._engine is not None and self._engine.state() in (
            "idle",
            "running",
            "paused",
        ):
            self._engine.cancel(reason)

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
