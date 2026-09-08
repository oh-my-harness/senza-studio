"""项目插件集加载测试（Phase 4 切片四）。

约定：``<project>/plugins/*.py`` 暴露 ``get_plugins()``，返回 senza Plugin
列表。这里重点测两件事：加载成功的路径，以及插件写错时**不能**把整个 Play
带崩——插件是加法，缺一个只是少一批工具。
"""
from __future__ import annotations

import senza

from studio_backend.config import StudioConfig
from studio_backend.play import load_project_plugins
from studio_backend.project import Project


def _project(tmp_path, name="插件测试"):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="k",
        api_base="",
    )
    return Project.create(config, name)


def _write_plugin(project, filename, body):
    (project.path / "plugins" / filename).write_text(body, encoding="utf-8")


GOOD = '''
import senza

def get_plugins():
    tool = senza.create_tool(
        name="now",
        description="当前时间",
        parameters={"type": "object", "properties": {}},
        callback=lambda args, ctx: "2026-01-01",
    )
    return [senza.create_plugin("clock", tools=[tool])]
'''


def test_no_plugins_dir_is_not_an_error(tmp_path):
    project = _project(tmp_path)
    import shutil

    shutil.rmtree(project.path / "plugins")
    assert load_project_plugins(project) == ([], [])


def test_empty_plugins_dir_loads_nothing(tmp_path):
    """新项目的 plugins/ 里只有 README.md，不该被当成插件去加载。"""
    project = _project(tmp_path)
    plugins, errors = load_project_plugins(project)
    assert plugins == []
    assert errors == []


def test_loads_a_valid_plugin(tmp_path):
    project = _project(tmp_path)
    _write_plugin(project, "clock.py", GOOD)
    plugins, errors = load_project_plugins(project)
    assert errors == []
    assert len(plugins) == 1
    assert isinstance(plugins[0], senza.Plugin)


def test_loads_multiple_files_in_stable_order(tmp_path):
    project = _project(tmp_path)
    _write_plugin(project, "b_second.py", GOOD)
    _write_plugin(project, "a_first.py", GOOD)
    plugins, errors = load_project_plugins(project)
    assert errors == []
    assert len(plugins) == 2  # 按文件名排序加载，结果可复现


def test_underscore_files_are_skipped(tmp_path):
    """下划线开头的文件是公共代码，不是插件——照着加载会因为没有
    get_plugins() 报一堆假错。"""
    project = _project(tmp_path)
    _write_plugin(project, "_shared.py", "HELPER = 1\n")
    plugins, errors = load_project_plugins(project)
    assert plugins == []
    assert errors == []


# ── 写错时的降级行为 ─────────────────────────────────────


def test_syntax_error_is_reported_not_raised(tmp_path):
    """一个插件语法写错不该让整个 Play 崩在构建阶段。"""
    project = _project(tmp_path)
    _write_plugin(project, "broken.py", "def get_plugins(:\n")
    plugins, errors = load_project_plugins(project)
    assert plugins == []
    assert len(errors) == 1
    assert "broken.py" in errors[0]


def test_one_broken_plugin_does_not_lose_the_others(tmp_path):
    """坏的那个报错，好的照样装上——插件之间互不影响。"""
    project = _project(tmp_path)
    _write_plugin(project, "good.py", GOOD)
    _write_plugin(project, "bad.py", "raise RuntimeError('boom')\n")
    plugins, errors = load_project_plugins(project)
    assert len(plugins) == 1
    assert len(errors) == 1
    assert "bad.py" in errors[0]


def test_missing_get_plugins_is_reported(tmp_path):
    project = _project(tmp_path)
    _write_plugin(project, "nofunc.py", "X = 1\n")
    plugins, errors = load_project_plugins(project)
    assert plugins == []
    assert "get_plugins" in errors[0]


def test_non_list_return_is_reported(tmp_path):
    project = _project(tmp_path)
    _write_plugin(
        project,
        "scalar.py",
        "import senza\ndef get_plugins():\n    return senza.create_plugin('x')\n",
    )
    plugins, errors = load_project_plugins(project)
    assert plugins == []
    assert "必须返回列表" in errors[0]


def test_returning_a_tool_instead_of_a_plugin_is_reported(tmp_path):
    """最常见的写法错误：返回了 create_tool 造的 Tool 而不是 Plugin。
    静默丢掉的话，agent 少了工具却没有任何提示。"""
    project = _project(tmp_path)
    _write_plugin(
        project,
        "wrong.py",
        '''
import senza

def get_plugins():
    return [senza.create_tool(
        name="t", description="d",
        parameters={"type": "object", "properties": {}},
        callback=lambda a, c: "x",
    )]
''',
    )
    plugins, errors = load_project_plugins(project)
    assert plugins == []
    assert "Plugin" in errors[0]


def test_plugins_are_reloaded_each_call(tmp_path):
    """改完插件下一次 Play 就生效，不用重启后端——跟 tools/registry.py
    同一个道理（换新模块名绕开 sys.modules 缓存）。"""
    project = _project(tmp_path)
    _write_plugin(project, "p.py", GOOD)
    assert len(load_project_plugins(project)[0]) == 1

    _write_plugin(
        project,
        "p.py",
        GOOD.replace('return [senza.create_plugin("clock", tools=[tool])]',
                     'return [senza.create_plugin("clock", tools=[tool]),\n'
                     '            senza.create_plugin("second", tools=[])]'),
    )
    plugins, errors = load_project_plugins(project)
    assert errors == []
    assert len(plugins) == 2


def test_two_projects_do_not_share_a_same_named_plugin_module(tmp_path):
    """两个项目都可能有 plugins/tools.py，固定模块名会让后加载的项目复用
    前一个缓存在 sys.modules 里的模块，读到别的项目的插件。"""
    a = _project(tmp_path, "A")
    b = _project(tmp_path, "B")
    _write_plugin(a, "same.py", GOOD)
    _write_plugin(
        b,
        "same.py",
        GOOD.replace('senza.create_plugin("clock", tools=[tool])',
                     'senza.create_plugin("clock", tools=[tool]),\n'
                     '            senza.create_plugin("only_in_b", tools=[])'),
    )
    assert len(load_project_plugins(a)[0]) == 1
    assert len(load_project_plugins(b)[0]) == 2
    assert len(load_project_plugins(a)[0]) == 1  # A 不受 B 影响


# ── 真的装进 harness 了吗 ────────────────────────────────


class _FakeBuilder:
    """记录 HarnessBuilder 上都调了什么——插件有没有真的装进去，光看
    load_project_plugins 是测不出来的。"""

    def __init__(self, model):
        self.model = model
        self.installed: list = []

    def provider(self, *a, **k):
        return self

    def env(self, *a, **k):
        return self

    def plugin(self, p):
        self.installed.append(p)
        return self

    def build(self):
        return self


def test_project_plugins_are_installed_on_the_agent_step_harness(tmp_path, monkeypatch):
    from studio_backend import play as play_mod

    built: list[_FakeBuilder] = []

    def _fake_builder(model):
        b = _FakeBuilder(model)
        built.append(b)
        return b

    monkeypatch.setattr(play_mod.senza, "HarnessBuilder", _fake_builder)
    monkeypatch.setattr(
        play_mod, "_run_agent_step", lambda harness, prompt, emit: ("out", 0)
    )
    monkeypatch.setattr(play_mod, "_harness_usage", lambda h: {}, raising=False)

    p1 = senza.create_plugin("one", tools=[])
    p2 = senza.create_plugin("two", tools=[])
    executor = play_mod.make_executor(
        {"a": {"name": "a", "type": "agent", "prompt_template": "hi"}},
        {"a": {}},
        "test-model",
        object(),
        object(),
        {},
        {},
        None,
        [p1, p2],
    )
    executor({"step_id": "a", "context": {}, "emit": lambda *a, **k: None})

    assert built, "没有构造 harness"
    assert built[0].installed == [p1, p2]


def test_play_harness_gets_no_studio_plugins(tmp_path, monkeypatch):
    """插件集隔离（设计文档 §7）：Play 的 harness 只装项目插件，绝不注入
    Studio 元 agent 那套（fs_tools/safety_defaults/injection_filter）。

    漏进去的话，业务流程在 Studio 里跑和导出后跑行为会不一样——agent 在
    Studio 里能读写文件，导出之后突然不能了。
    """
    from studio_backend import play as play_mod

    built: list[_FakeBuilder] = []
    monkeypatch.setattr(
        play_mod.senza, "HarnessBuilder", lambda m: built.append(_FakeBuilder(m)) or built[-1]
    )
    monkeypatch.setattr(
        play_mod, "_run_agent_step", lambda harness, prompt, emit: ("out", 0)
    )

    executor = play_mod.make_executor(
        {"a": {"name": "a", "type": "agent", "prompt_template": "hi"}},
        {"a": {}},
        "test-model",
        object(),
        object(),
        {},
        {},
        None,
        None,  # 项目没有插件
    )
    executor({"step_id": "a", "context": {}, "emit": lambda *a, **k: None})
    assert built[0].installed == []
