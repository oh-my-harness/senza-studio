"""运行时包能脱离 Studio 独立使用（Phase 7 切片一）。

这个包存在的全部意义就是"导出的项目不需要 Studio 也能跑"。所以这里刻意**不**
import 任何 studio_backend 的东西——一旦有人不小心把 Studio 的类型加回运行时，
这些测试会立刻红。
"""
from __future__ import annotations

from pathlib import Path

import pytest

import senza_studio_runtime as runtime
from senza_studio_runtime.play import PlaySession, load_tool_registry


def test_package_does_not_import_studio_backend():
    """真正的护栏：运行时不能反向依赖 Studio。

    必须开一个干净的解释器来验。在本进程里查 sys.modules 是没用的——整个测试
    套件里别的模块早就把 studio_backend import 进来了，这个断言要么恒假、要么
    只在单独跑这个文件时才碰巧通过（第一版就是这么挂的）。
    """
    import subprocess
    import sys

    probe = (
        "import senza_studio_runtime, sys; "
        "bad=[m for m in sys.modules if m.startswith('studio_backend')]; "
        "print(bad)"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        cwd="/",  # 别让仓库目录混进 sys.path
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]", (
        f"运行时把 Studio 模块拉进来了：{result.stdout.strip()}"
    )


def test_public_api_is_complete():
    for name in runtime.__all__:
        assert hasattr(runtime, name), name


def test_loaders_take_a_plain_path_not_a_project(tmp_path):
    """接口去 Studio 化的核心：收根目录，不收 Project。"""
    (tmp_path / "tools" / "generated").mkdir(parents=True)
    (tmp_path / "tools" / "generated" / "t.py").write_text(
        'def t(args):\n    return "ok"\n\n'
        'TOOL = {"name": "t", "description": "d",\n'
        '        "parameters": {"type": "object", "properties": {}},\n'
        '        "callback": t}\n',
        encoding="utf-8",
    )
    tools, error = load_tool_registry(tmp_path)
    assert error is None
    assert tools["t"]({}) == "ok"


def test_play_session_takes_root_spec_model_provider(tmp_path):
    """导出的项目就是这么构造它的：一个目录 + 一份 spec dict + 模型 + provider。"""
    session = PlaySession(
        root=tmp_path,
        spec={"stages": [{"name": "a", "type": "terminal", "message": "done"}]},
        model="test-model",
        provider=object(),
    )
    assert session._root == Path(tmp_path)
    assert session._model == "test-model"


def test_play_requires_root_and_spec_to_be_bound():
    """允许晚绑定（Studio 那层适配靠它保持惰性），但真跑之前必须填上，
    而且要给一句能看懂的错，不是 AttributeError: 'NoneType'。"""
    session = PlaySession()
    with pytest.raises(RuntimeError, match="还没绑定"):
        session.play()


def test_preprocess_is_reexported():
    """导出项目运行时也要展开能力组件——预处理器必须跟着一起走。"""
    spec = {
        "stages": [
            {"name": "gate", "component": "approval_flow", "next_on_approve": "ok"},
            {"name": "ok", "type": "terminal"},
        ]
    }
    out = runtime.preprocess_spec(spec)
    assert out["stages"][0]["name"] == "gate_review"


def test_index_html_is_served_with_no_cache(tmp_path):
    """回归：index.html 必须每次回源校验。

    Vite 给 JS/CSS 的文件名带内容哈希，所以资源本身随便缓存；但 index.html
    一被缓存住，它引用的就是上一次构建的哈希，而那个文件在新导出的目录里不
    存在——浏览器于是反复请求一个 404 的 js，页面白屏，刷新也没用（刷新读的
    还是缓存里的 html）。用户实测踩到过。

    注意"不设 Cache-Control"不等于"不缓存"：没有这个头时浏览器会按启发式规则
    自己决定缓存多久，所以必须显式声明。
    """
    from fastapi.testclient import TestClient

    from senza_studio_runtime.serve import create_app

    pipeline = tmp_path / "pipeline.yaml"
    pipeline.write_text("stages:\n  - name: z\n    type: terminal\n", encoding="utf-8")
    dist = tmp_path / "webui" / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    (dist / "assets" / "index-abc123.js").write_text("//js", encoding="utf-8")

    client = TestClient(create_app(pipeline, dist))
    for path in ("/", "/some/spa/route"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert "no-cache" in r.headers.get("cache-control", ""), (
            f"{path} 没有 no-cache，浏览器会缓存住旧的 index.html"
        )
    # 带哈希的资源是不可变的，不需要（也不该）加 no-cache
    asset = client.get("/assets/index-abc123.js")
    assert asset.status_code == 200
    assert "no-cache" not in asset.headers.get("cache-control", "")


def test_manifest_name_falls_back_to_the_directory(tmp_path):
    """手写的 pipeline 旁边没有 agent.json——不能因此让界面标题空着。"""
    from senza_studio_runtime.serve import load_manifest

    assert load_manifest(tmp_path) == {}
    (tmp_path / "agent.json").write_text('{"name": "退款助手"}', encoding="utf-8")
    assert load_manifest(tmp_path)["name"] == "退款助手"

    # 坏掉的 agent.json 不该让整个服务起不来——名字退回目录名就行
    (tmp_path / "agent.json").write_text("{ not json", encoding="utf-8")
    assert load_manifest(tmp_path) == {}


def test_describe_steps_defaults_display_to_chat():
    """ui.display 没写时按 chat 渲染——必须和 Studio 的 Game view 同一个默认
    值（GameView.tsx 的 displayConfigFor）。两边默认值不一样的话，作者在
    Studio 里看到的效果和用户在导出产品里看到的就不是一回事。"""
    from senza_studio_runtime.serve import describe_steps

    steps = describe_steps(
        {
            "stages": [
                {"name": "a", "type": "agent", "prompt_template": "x", "next_on_success": "b"},
                {"name": "b", "type": "terminal", "message": "完"},
            ]
        }
    )
    assert steps["a"]["display"] == "chat"
    assert steps["a"]["terminal"] is False
    assert steps["b"]["terminal"] is True


def test_only_checker_steps_expose_choices():
    """choices 是"停下来问人时给的选项"，不是"这一步能走哪几条分支"。

    普通 step 的 next_on_* 是流程结构，产品界面不需要知道——回给它等于把
    DAG 的一部分漏出去。用户实测的 spec 里 classify_message 有三个分类分支，
    以前会原样出现在 /api/agent 的响应里。
    """
    from senza_studio_runtime.serve import describe_steps

    steps = describe_steps(
        {
            "stages": [
                {
                    "name": "classify",
                    "type": "agent",
                    "prompt_template": "分类 {{msg}}",
                    "next_on_complaint": "gate",
                    "next_on_question": "done",
                },
                {
                    "name": "gate",
                    "type": "checker",
                    "prompt_template": "审批",
                    "next_on_approve": "done",
                    "next_on_reject": "done",
                },
                {"name": "done", "type": "terminal", "message": "完"},
            ]
        }
    )
    assert steps["classify"]["choices"] == []
    assert steps["gate"]["choices"] == ["approve", "reject"]


def test_event_poll_keeps_the_same_silence_budget():
    """缩短轮询间隔是为了尽快发现"跑完了"（终态没有事件通知，只能靠 timeout
    哨兵醒过来时检查后台线程）。但两个常数的乘积是"允许一直没有事件"的总
    时长——真实 LLM 长时间不出字是正常的，间隔变小而次数没同比变大，就会把
    跑得慢的 step 误判成卡死。这条把这个不变量钉住。"""
    from senza_studio_runtime import stream

    budget_seconds = stream.POLL_INTERVAL_MS / 1000 * stream.MAX_SILENT_POLLS
    assert budget_seconds >= 4800, "静默预算被缩短了，慢的 LLM step 会被误杀"
    # 终态发现延迟直接就是这个间隔；超过 1s 用户就能感觉到按钮"卡"在上一个状态
    assert stream.POLL_INTERVAL_MS <= 500
