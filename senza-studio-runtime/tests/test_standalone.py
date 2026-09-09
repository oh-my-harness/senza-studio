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
