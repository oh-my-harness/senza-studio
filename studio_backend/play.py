"""Play 模式（Phase 2 最薄切片）：直接用 senza 的 WorkflowEngine 跑 spec。

`stages_to_workflow`（senza SDK 内置）已经把 `{"stages": [...]}` 编译成
Workflow：每个非 terminal stage 变成一个 executor step（统一分派到
"eda_executor"），terminal stage 被引擎直接短路成原生 Step::Terminal——
永远不会调用这里的 executor 回调。所以 Studio 自己不需要写 spec 预处理器，
只需要一个 executor 回调（只支持 type: agent，checker/tool 留给 Phase 3）
和一个 judge 回调（把 executor 返回的 route_key 翻成 "to:<step>"）。

`stages_to_workflow` 不会把 stage 的原始字段（type/prompt_template/...）
透传进 executor_config，所以这里自己维护 step_name -> stage dict 和
step_name -> {route_label: target} 两张表。

回调工厂（make_judge/make_executor）与 spec_tools.make_spec_callbacks 同一
模式：与 senza.create_judge/create_executor 的包装分离，方便直接单测。
"""
from __future__ import annotations

import re
import sys
import threading
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


def make_judge(routes_by_name: dict[str, dict[str, str]]) -> Callable[[dict], str]:
    """路由回调：把 executor 返回的 route_key 翻成 senza judge 的 transition 字符串。"""

    def play_judge(ctx: dict) -> str:
        structured = ctx.get("structured") or {}
        route_key = structured.get("route_key")
        routes = routes_by_name.get(ctx["step_id"], {})
        target = routes.get(route_key)
        if target is None:
            return f"fail:no route for '{route_key}' from '{ctx['step_id']}'"
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


# 匹配 LLM 回答末尾的路由标记，如 {"route": "complaint"}。不用完整 JSON
# 解析——只要求这个扁平形状，避免被回答正文里其它花括号干扰。
_ROUTE_RE = re.compile(r'\{\s*"route"\s*:\s*"([^"]+)"\s*\}')


def _append_routing_instruction(prompt: str, routes: list[str]) -> str:
    """多路由时，要求 LLM 在回答末尾用一行 JSON 声明选中的路由。"""
    options = ", ".join(f'"{r}"' for r in routes)
    return (
        f"{prompt}\n\n---\n"
        f"After your response, end with exactly one line containing only this JSON, "
        f"choosing whichever option best applies: {{\"route\": \"<one of: {options}>\"}}"
    )


def _extract_route(output: str, routes: list[str]) -> tuple[str, str]:
    """从 LLM 输出末尾提取路由标记；成功则从展示文本里去掉这行标记。

    找不到标记，或标记的值不在这个 step 声明的路由里，都返回 "error"——
    交给 judge 报清晰的 fail 消息，而不是猜一个路由走下去。
    """
    matches = list(_ROUTE_RE.finditer(output))
    if not matches:
        return "error", output
    last = matches[-1]
    route = last.group(1)
    clean_output = (output[: last.start()] + output[last.end() :]).strip()
    if route not in routes:
        return "error", clean_output
    return route, clean_output


def make_executor(
    stage_by_name: dict[str, dict],
    routes_by_name: dict[str, dict[str, str]],
    model: str,
    provider: Any,
    env: Any,
) -> Callable[[dict], dict]:
    """执行回调：只支持 type: agent，其它类型返回 error route（Phase 3 补全）。

    短生命周期 harness——不带元 agent 的 spec/doc/prefab 工具或 strategy
    插件栈，那些是 Studio 自己的 meta agent 专属（agent.py）。这里跑的是
    spec 里被作者定义出来的 agent，项目自己的 plugins/（Phase 4）暂未接入。
    """

    def play_executor(ctx: dict) -> dict:
        step_id = ctx["step_id"]
        stage = stage_by_name.get(step_id)
        if stage is None:
            return {
                "output": f"Error: unknown step '{step_id}'",
                "structured": {"route_key": "error"},
            }
        stage_type = stage.get("type")
        if stage_type != "agent":
            return {
                "output": (
                    f"Error: step type '{stage_type}' not supported until Phase 3"
                ),
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
            output = _run_agent_step(harness, prompt, ctx["emit"])
        except Exception as exc:  # noqa: BLE001
            return {"output": f"Error: {exc}", "structured": {"route_key": "error"}}

        if len(routes) > 1:
            route_key, output = _extract_route(output, routes)
        else:
            route_key = routes[0] if routes else "success"

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

        executor = make_executor(
            stage_by_name, routes_by_name, self._config.model, provider, env
        )
        judge = make_judge(routes_by_name)

        self._engine = senza.WorkflowEngine(
            spec_dict, provider, self._config.model, senza.create_judge(judge), env=env
        )
        self._engine.with_executor("eda_executor", senza.create_executor(executor))

        for key, value in (inputs or {}).items():
            self._engine.set_context_variable(key, value)

        self._project.meta["status"] = "playing"
        self._project._save_meta()

    def start(self) -> None:
        """在后台线程启动 .run()。必须在 events() 订阅之后调用（见 play()）。"""
        if self._engine is None:
            raise RuntimeError("Engine not built. Call play() first.")

        def _run() -> None:
            # engine.run() 在 workflow 失败时 raise senza.SenzaError（比如
            # judge 返回 "fail:..."）。默认线程行为是打印一个吓人的未捕获
            # 异常 traceback 然后悄悄退出——这里改成记录到 run_error，让
            # run_play_streaming 能把清晰的 error 消息转发给前端。
            try:
                self._engine.run()
            except BaseException as exc:  # noqa: BLE001
                self.run_error = exc
                print(f"Play run error: {exc}", file=sys.stderr)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

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
