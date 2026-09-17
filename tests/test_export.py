"""导出打包测试（Phase 7 切片二）。

导出产物是要交给别人、在别的机器上跑的，所以这里重点盯两类事：产物内容对不对
（少一个文件对方就跑不起来），以及 spec 有问题时能不能**在导出这一步**就拦住，
而不是等对方装完才炸。
"""
from __future__ import annotations

import pathlib
import tomllib

import pytest

from studio_backend.config import StudioConfig
from studio_backend.export import ExportError, export_project, slugify
from studio_backend.project import Project
from studio_backend.settings import SETTINGS_SCHEMA
from studio_backend.spec import Spec


def _project(tmp_path, name="订单处理流程"):
    return Project.create(
        StudioConfig(
            home_dir=str(tmp_path / ".senza-studio"),
            model="m",
            api_key="k",
            api_base="",
        ),
        name,
    )


def _spec():
    return Spec(
        {
            "stages": [
                {
                    "name": "classify",
                    "type": "agent",
                    "prompt_template": "分类 {{msg}}",
                    "next_on_success": "done",
                },
                {"name": "done", "type": "terminal", "message": "完成"},
            ]
        }
    )


# ── slug ─────────────────────────────────────────────────


def test_slugify_handles_chinese_names():
    """项目名经常是中文。pyproject 的 name 必须是 PEP 508 字符集，直接拿中文
    当包名会生成一个装不上的包。"""
    assert slugify("研究 agent") == "agent"
    assert slugify("订单处理流程") == "senza-agent"  # 全中文 → 退回兜底
    assert slugify("Order Flow v2") == "order-flow-v2"
    assert slugify("a___b") == "a-b"


# ── 产物内容 ─────────────────────────────────────────────


def test_export_writes_every_file_the_readme_promises(tmp_path):
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    for name in ("pipeline.yaml", "pyproject.toml", ".env.example", "README.md"):
        assert (target / name).is_file(), f"少了 {name}"
    assert (target / "tools").is_dir()
    assert (target / "plugins").is_dir()


def test_exported_pipeline_keeps_components_unexpanded(tmp_path):
    """产物里存编辑态 spec：导出项目跑的是同一个预处理器，而不是一份烘焙好的
    快照。存展开结果等于把当时的实现固化进产物。"""
    proj = _project(tmp_path)
    spec = Spec(
        {
            "stages": [
                {
                    "name": "gate",
                    "component": "approval_flow",
                    "next_on_approve": "done",
                    "next_on_reject": "done",
                },
                {"name": "done", "type": "terminal"},
            ]
        }
    )
    target, _, _ = export_project(proj, spec, vendor=False)
    text = (target / "pipeline.yaml").read_text(encoding="utf-8")
    assert "component: approval_flow" in text
    assert "gate_review" not in text  # 没有被展开


def test_export_uses_the_in_memory_spec_not_the_saved_file(tmp_path):
    """用户要导出的是他现在屏幕上那份，不是上次存盘的那份。"""
    proj = _project(tmp_path)
    proj.save_spec(Spec({"stages": [{"name": "old", "type": "terminal"}]}))
    target, _, _ = export_project(proj, _spec(), vendor=False)
    text = (target / "pipeline.yaml").read_text(encoding="utf-8")
    assert "classify" in text and "old" not in text


def test_generated_pyproject_is_valid_toml_with_the_three_deps(tmp_path):
    """对方第一件事就是 pip install -e .——这个文件坏了什么都别谈。"""
    proj = _project(tmp_path, "Order Flow")
    target, _, _ = export_project(proj, _spec(), vendor=False)
    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["project"]["name"] == "order-flow"
    deps = data["project"]["dependencies"]
    # senza-sdk 带版本号（钉成 Studio 验证过的那个），另两个是裸名字
    assert any(d.startswith("senza-sdk") for d in deps), deps
    assert {"senza-studio-runtime", "senza-studio-components"} <= set(deps)


def test_env_example_covers_every_settings_key(tmp_path):
    """从 SETTINGS_SCHEMA 生成而不是手写——手写那份迟早和设置面板对不上，
    用户照着配就是少一项。"""
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    env = (target / ".env.example").read_text(encoding="utf-8")
    for field in SETTINGS_SCHEMA:
        assert f"{field['key']}=" in env, f"{field['key']} 没进 .env.example"


def test_env_example_marks_secrets(tmp_path):
    """密钥项要有"别提交进版本库"的提醒。提醒在键的上一行（行尾注释会被某些
    dotenv 解析器当成值，见 test_env_example_values_parse_as_empty...）。"""
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    lines = (target / ".env.example").read_text(encoding="utf-8").splitlines()
    secrets = [f["key"] for f in SETTINGS_SCHEMA if f["secret"]]
    assert secrets, "schema 里没有密钥字段，这条测试就没意义了"
    for key in secrets:
        index = next(i for i, l in enumerate(lines) if l.startswith(f"{key}="))
        preceding = "\n".join(lines[max(0, index - 3) : index])
        assert "密钥" in preceding, f"{key} 上方没有密钥提醒"


def test_tools_and_plugins_are_copied_without_caches(tmp_path):
    proj = _project(tmp_path)
    (proj.path / "tools" / "custom" / "mine.py").write_text("TOOL = {}\n", encoding="utf-8")
    cache = proj.path / "tools" / "custom" / "__pycache__"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "mine.cpython-312.pyc").write_bytes(b"\x00")
    target, _, _ = export_project(proj, _spec(), vendor=False)
    assert (target / "tools" / "custom" / "mine.py").is_file()
    assert not (target / "tools" / "custom" / "__pycache__").exists()


def test_webui_is_bundled_when_a_build_exists(tmp_path):
    proj = _project(tmp_path)
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    target, with_webui, _ = export_project(proj, _spec(), webui_dist=dist, vendor=False)
    assert with_webui is True
    assert (target / "webui" / "dist" / "index.html").is_file()


def test_missing_webui_build_is_not_an_error(tmp_path):
    """没构建过前端照样能导出，只是跑起来没有网页界面——由调用方提示用户。"""
    proj = _project(tmp_path)
    target, with_webui, _ = export_project(proj, _spec(), webui_dist=tmp_path / "nope", vendor=False)
    assert with_webui is False
    assert (target / "pipeline.yaml").is_file()


# ── 导出前的拦截 ─────────────────────────────────────────


def test_invalid_spec_is_rejected_before_writing_anything(tmp_path):
    """spec 不合法就地报错，比让用户把跑不起来的目录交给别人强。"""
    proj = _project(tmp_path)
    bad = Spec({"stages": [{"name": "a", "type": "agent"}]})  # 没有 terminal
    with pytest.raises(ExportError, match="spec 不合法"):
        export_project(proj, bad, vendor=False)
    assert not any((proj.path / "exports").iterdir())


def test_unexpandable_component_is_rejected(tmp_path):
    proj = _project(tmp_path)
    bad = Spec(
        {
            "stages": [
                {"name": "gate", "component": "no_such_component", "next_on_approve": "done"},
                {"name": "done", "type": "terminal"},
            ]
        }
    )
    with pytest.raises(ExportError, match="组件"):
        export_project(proj, bad, vendor=False)


def test_export_name_cannot_escape_the_exports_dir(tmp_path):
    """name 可能来自 HTTP 请求，而它会被拼进路径然后 rmtree——必须留在
    exports/ 里面。

    这里断言的是"结果安全"而不是"报错"：slugify 的职责本来就是把任意名字
    （包括中文）转成合法 slug，"../../evil" 被洗成 "evil" 是预期行为，不是
    意外放行。export_project 里那道 is_relative_to 是第二层保险。
    """
    proj = _project(tmp_path)
    exports_root = (proj.path / "exports").resolve()
    for hostile in ("../../evil", "..", "/etc", "....//....//x"):
        target, _, _ = export_project(proj, _spec(), name=hostile, vendor=False)
        assert target.is_relative_to(exports_root), f"{hostile!r} 跑出了 exports/"
        assert target != exports_root
    # 确认没有任何东西被写到 exports/ 外面
    assert not (proj.path / "evil").exists()
    assert not (proj.path.parent / "evil").exists()


# ── 重复导出 ─────────────────────────────────────────────


def test_re_export_replaces_the_previous_output(tmp_path):
    """同名重复导出要整个重写，不能留下上一次的残留文件。"""
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    stale = target / "stale.txt"
    stale.write_text("上一次导出留下的", encoding="utf-8")
    again, _, _ = export_project(proj, _spec(), vendor=False)
    assert again == target
    assert not stale.exists()


def test_export_records_the_location_in_project_meta(tmp_path):
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    assert proj.meta["last_export_dir"] == str(target)
    assert proj.meta["last_exported_at"]


def test_env_example_values_parse_as_empty_not_as_comment_text(tmp_path):
    """回归：别写成 `KEY=  # 说明`。行尾注释在各家 dotenv 解析器里行为不一致，
    有的会把 "# 说明" 整段当成值读进去——用户以为自己留空了，实际配了一串垃圾。
    注释必须单独占一行。
    """
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    values = {}
    for line in (target / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        values[key] = value
    assert values, ".env.example 里一个键都没有"
    for key, value in values.items():
        assert value == "", f"{key} 的值不是空的：{value!r}"


def test_readme_run_instructions_actually_load_the_env(tmp_path):
    """README 里得给一条真能用的命令。没有任何代码会自动读 .env——只写
    `cp .env.example .env` 然后叫人跑，配置根本不会生效。"""
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "source .env" in readme
    assert "set +a" in readme  # 别把 set -a 一直开着
    assert "senza-studio-runtime serve" in readme


def test_generated_pyproject_disables_package_discovery(tmp_path):
    """回归：不写 [tool.setuptools] packages = [] 的话，setuptools 会把
    plugins/ 和 webui/ 当成两个顶级 Python 包自动发现，然后直接报
    "Multiple top-level packages discovered in a flat-layout" 装不上——
    也就是说按 README 第一步 `pip install -e .` 就失败（用户实测踩到）。

    导出目录本来就不是一个 Python 包，只是一份依赖清单 + 一堆数据文件；
    tools/ 和 plugins/ 是运行时按路径加载的，不需要被打包。
    """
    proj = _project(tmp_path)
    (proj.path / "plugins" / "p.py").write_text("def get_plugins():\n    return []\n", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    target, _, _ = export_project(proj, _spec(), webui_dist=dist, vendor=False)

    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    assert data["tool"]["setuptools"]["packages"] == []
    # 确认这正是会触发自动发现的那种目录结构
    assert (target / "plugins").is_dir() and (target / "webui").is_dir()


# ── vendor：把依赖 wheel 打进导出目录 ────────────────────


def test_vendor_bundles_only_the_unpublished_packages(tmp_path):
    """runtime 和 components 没发到 PyPI，所以要自带 wheel——否则拿到这个目录
    的人只能去装 Studio 源码，"不依赖 Studio"就是句空话。

    senza-sdk **不** vendor：它在 PyPI 上，交给 pip 解析还能拿到对方平台的
    wheel（它是编译产物），我们硬拷一份只会是打包这台机器的架构。

    这条会真的 build wheel（几秒），所以其它用例一律 vendor=False。
    """
    proj = _project(tmp_path)
    target, _, missing = export_project(proj, _spec())
    assert missing == []
    names = sorted(p.name for p in (target / "vendor").glob("*.whl"))
    assert any(n.startswith("senza_studio_runtime") for n in names), names
    assert any(n.startswith("senza_studio_components") for n in names), names
    assert not any(n.startswith("senza_sdk") for n in names), (
        f"senza-sdk 不该被 vendor（PyPI 上有）: {names}"
    )


def test_sdk_is_pinned_to_the_verified_version(tmp_path):
    """"行为和 Studio 里一致"也包括引擎版本一致——让对方随便装个最新的不安全。"""
    import json as _json

    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    locked = _json.loads(
        (pathlib.Path(__file__).resolve().parent.parent / "senza-sdk.lock").read_text()
    )["senza_version"]
    data = tomllib.loads((target / "pyproject.toml").read_text(encoding="utf-8"))
    assert f"senza-sdk=={locked}" in data["project"]["dependencies"]


def test_readme_installs_from_vendor(tmp_path):
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec())
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "--find-links vendor" in readme
    # 两种来源要讲清楚，否则用户不知道为什么有的从 vendor 装、有的从网上装
    assert "vendor/" in readme and "PyPI" in readme
    assert "需要联网" in readme


def test_missing_wheels_are_reported_not_fatal(tmp_path, monkeypatch):
    """打不出 wheel 不该让导出失败——用户照样拿到目录，只是得自己解决依赖。"""
    from studio_backend import export as export_mod

    monkeypatch.setattr(export_mod, "_VENDORED_PACKAGES", ("no-such-package",))
    proj = _project(tmp_path)
    target, _, missing = export_project(proj, _spec())
    assert (target / "pipeline.yaml").is_file()  # 导出本身成功了
    assert missing == ["no-such-package"]
    assert "⚠️" in (target / "README.md").read_text(encoding="utf-8")
