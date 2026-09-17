"""导出打包测试（Phase 7 切片二）。

导出产物是要交给别人、在别的机器上跑的，所以这里重点盯两类事：产物内容对不对
（少一个文件对方就跑不起来），以及 spec 有问题时能不能**在导出这一步**就拦住，
而不是等对方装完才炸。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess
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
    # 目录名有长度上限，项目名没有——不截断的话 mkdir 直接抛 OSError
    assert len(slugify("x" * 500)) <= 64


# ── 产物内容 ─────────────────────────────────────────────


def test_export_writes_every_file_the_readme_promises(tmp_path):
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    for name in (
        "pipeline.yaml",
        "agent.json",
        "pyproject.toml",
        ".env.example",
        "README.md",
    ):
        assert (target / name).is_file(), f"少了 {name}"
    assert (target / "tools").is_dir()
    assert (target / "plugins").is_dir()


def test_agent_manifest_keeps_the_human_readable_name(tmp_path):
    """目录名和包名都被 slug 成 ASCII（中文项目名会被过滤光，退回
    senza-agent），人看的那个名字必须另外存下来——否则界面标题会显示
    "senza-agent"，用户看到的是一个自己没起过的名字。"""
    import json

    proj = _project(tmp_path, name="订单处理流程")
    target, _, _ = export_project(proj, _spec(), vendor=False)
    assert target.name == "senza-agent"  # slug 兜底
    manifest = json.loads((target / "agent.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "订单处理流程"


def test_readme_does_not_promise_the_editor_ui(tmp_path):
    """导出的是做好的 agent，不是做它用的编辑器。README 以前写着"界面和
    Studio 里的 Play 视图一样：DAG、Pause/Step"——那份承诺现在是错的，而且
    正是用户指出的问题。"""
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    readme = (target / "README.md").read_text(encoding="utf-8")
    for editor_word in ("DAG", "Inspector", "Pause/Step"):
        assert editor_word in readme, "README 该明说这些不在导出产物里"
    assert "没有" in readme


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


# ── run.sh：一条命令跑起来 ─────────────────────────────


def _run_script(tmp_path, name="订单处理流程"):
    proj = _project(tmp_path, name=name)
    # 目录名单独给：这里要试的是**项目名**进到脚本里会怎样，不想让一个很长
    # 或很怪的名字顺带把导出目录名也搞坏。
    target, _, _ = export_project(proj, _spec(), name="agent", vendor=False)
    return target / "run.sh"


def test_run_script_is_executable(tmp_path):
    """不给执行位的话用户得先 chmod，或者记得写 `bash run.sh`——那就又变回
    两步了，而"一条命令"正是这个脚本存在的全部理由。"""
    script = _run_script(tmp_path)
    assert script.is_file()
    assert script.stat().st_mode & 0o111, "run.sh 没有执行位"


@pytest.mark.skipif(shutil.which("bash") is None, reason="需要 bash")
def test_run_script_parses(tmp_path):
    """语法错误要在导出这一步就暴露，而不是等用户拿到目录、敲了命令才发现。"""
    script = _run_script(tmp_path)
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_run_script_never_leaves_a_variable_next_to_a_multibyte_char(tmp_path):
    """`$VENV）` 这种写法会炸。

    bash 按字节找变量名，全角括号的字节会被吸进变量名里，于是报
    `VENV?: unbound variable` —— 脚本在第 60 行就退出，用户看到的是一个
    莫名其妙的变量名。实测踩到过。注释和提示文案全是中文，这个坑离得很近，
    所以用测试挡住：变量一律写成 ${VAR}。
    """
    text = _run_script(tmp_path).read_text(encoding="utf-8")
    offenders = [
        line
        for line in text.splitlines()
        if re.search(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7f]", line)
    ]
    assert offenders == [], f"这些行的变量要改成 ${{VAR}}: {offenders}"


@pytest.mark.skipif(shutil.which("bash") is None, reason="需要 bash")
def test_run_script_survives_a_hostile_project_name(tmp_path):
    """项目名是用户随手输入的，会原样进到这个脚本里。带引号能把字符串提前
    闭合，带换行能让名字的后半截变成自己一行的命令。

    不靠读文本判断，直接**跑一遍**：`--help` 会在真正干活之前退出，但在那
    之前已经执行到了带名字的那行赋值——注入成功的话 canary 就没了。"""
    canary = tmp_path / "canary"
    canary.write_text("still here", encoding="utf-8")
    nasty = f'it\'s "a test"\nrm -f {canary}\n`touch {tmp_path}/pwned`'
    script = _run_script(tmp_path, name=nasty)

    result = subprocess.run(
        ["bash", str(script), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert canary.is_file(), "项目名里的命令被执行了"
    assert not (tmp_path / "pwned").exists(), "反引号里的命令被执行了"


def test_run_script_checks_the_env_vars_that_serve_actually_reads(tmp_path):
    """脚本提前把"没填 key"变成一句能照着做的提示。它检查的变量名必须真的
    是设置面板里的那些——改名之后留下一个永远检查不到的脚本，比不检查更糟
    （用户以为配好了，跑到第一次调模型才炸）。"""
    from studio_backend.export import REQUIRED_ENV_GROUPS

    known = {field["key"] for field in SETTINGS_SCHEMA}
    text = _run_script(tmp_path).read_text(encoding="utf-8")
    for group in REQUIRED_ENV_GROUPS:
        assert group[0] in known, f"{group[0]} 不在 SETTINGS_SCHEMA 里了"
        for key in group:
            assert key in text


def test_requirements_and_pyproject_list_the_same_dependencies(tmp_path):
    """两份清单，一处来源。各写各的迟早有一份漏掉新依赖——而且是"装上了、
    跑起来才炸"那种漏。"""
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    declared = tomllib.loads(
        (target / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["dependencies"]
    listed = [
        line.strip()
        for line in (target / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert sorted(declared) == sorted(listed)


def test_readme_leads_with_the_one_command(tmp_path):
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "./run.sh" in readme
    # 手动那条路径留着，但不该是第一条
    assert readme.index("./run.sh") < readme.index("python3 -m venv")


def test_re_export_keeps_the_env_and_the_venv(tmp_path):
    """改 spec 之后重新导出是常规操作。每次都把用户填好的 .env 和 run.sh
    装好的 .venv 删掉的话，"一条命令跑起来"就只有第一次成立——第二次又要
    重填 key、重装一分多钟的依赖。"""
    proj = _project(tmp_path)
    target, _, _ = export_project(proj, _spec(), vendor=False)
    (target / ".env").write_text("SENZA_STUDIO_API_KEY=sk-mine\n", encoding="utf-8")
    (target / ".venv" / "bin").mkdir(parents=True)
    (target / ".venv" / "bin" / "python").write_text("#!/bin/sh\n", encoding="utf-8")
    # 上一次导出留下的、这次不该再有的文件
    (target / "stale.txt").write_text("old", encoding="utf-8")

    export_project(proj, _spec(), vendor=False)

    assert (target / ".env").read_text(encoding="utf-8") == "SENZA_STUDIO_API_KEY=sk-mine\n"
    assert (target / ".venv" / "bin" / "python").is_file()
    assert not (target / "stale.txt").exists(), "其它内容还是要整个重写"
    assert (target / "run.sh").is_file()
