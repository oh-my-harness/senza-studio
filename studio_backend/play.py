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


def make_executor(
    stage_by_name: dict[str, dict],
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
        stage = stage_by_name.get(ctx["step_id"])
        if stage is None:
            return {
                "output": f"Error: unknown step '{ctx['step_id']}'",
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
        try:
            prompt = prompt_template.format(**ctx["context"])
        except (KeyError, IndexError):
            prompt = prompt_template

        harness = senza.HarnessBuilder(model).provider("*", provider).env(env).build()
        try:
            output = _run_agent_step(harness, prompt, ctx["emit"])
        except Exception as exc:  # noqa: BLE001
            return {"output": f"Error: {exc}", "structured": {"route_key": "error"}}
        return {"output": output, "structured": {"route_key": "success"}}

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

    def play(self) -> None:
        """构建 WorkflowEngine。不启动 .run()——调用方必须先 events() 订阅，
        再调用 start()，否则 tokio broadcast 会丢掉 run() 线程里发生太快
        （比如立刻 fail 的 step，没有真实 LLM 调用）的早期事件：broadcast
        只推送给"已订阅"的 receiver，订阅前发的消息一律丢弃，不会缓冲。
        """
        spec_dict = self._spec.get_current_spec()
        stage_by_name, routes_by_name = build_route_maps(spec_dict)
        provider = _create_provider(self._config)
        env = senza.create_os_env(str(self._project.path))

        executor = make_executor(stage_by_name, self._config.model, provider, env)
        judge = make_judge(routes_by_name)

        self._engine = senza.WorkflowEngine(
            spec_dict, provider, self._config.model, senza.create_judge(judge), env=env
        )
        self._engine.with_executor("eda_executor", senza.create_executor(executor))

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
        if self._engine is not None:
            self._engine.cancel(reason)
        self._project.meta["status"] = "editing"
        self._project._save_meta()

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
