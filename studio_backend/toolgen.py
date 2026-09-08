"""定制工具代码的静态校验 + stub 生成（Phase 5）。

元 agent 通过 ``generate_tool`` 交上来一段 Python，这里负责判断它到底能不能
用，并在不能用的时候给出**可以直接喂回给模型让它自己改**的精确错误——和
``validate_spec`` 现在的回路一致（见 tools/spec_tools.py）。

生成的模块必须暴露一个 ``TOOL`` dict，形状与预制件清单一致
（senza_studio_components.registry 的 PREFABS 条目）：

    TOOL = {
        "name": "fetch_order",
        "description": "按订单号查询订单",
        "parameters": {"type": "object", "properties": {...}, "required": [...]},
        "callback": fetch_order,   # def fetch_order(args: dict) -> dict | str
    }

复用同一个形状而不是另发明一套：元 agent 已经从 list_prefabs 见过它，而且
``parameters`` 让"检查 JSON Schema 合法"这一步有真实的检查对象——项目工具原本
只是裸 callable，根本没有 schema 可校验。

刻意不做的事：不设 import 白名单/黑名单。元 agent 本来就装着
create_fs_tools_plugin（见 agent.py），今天就能自己往项目里写文件，禁掉
os/subprocess 属于安全剧场，只会挡住正当用途，挡不住任何真想干坏事的代码。
"""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

# 工具名会直接当文件名用（tools/generated/<name>.py），而这个名字是模型给的
# ——必须挡住 "../../x" 这种路径穿越，也顺便保证它是个合法的 Python 标识符。
_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*$")

IMPORT_TIMEOUT_SECONDS = 10
MAX_ATTEMPTS = 2


@dataclass
class ValidationResult:
    ok: bool
    error: str | None = None
    # 校验通过时带回工具的对外元数据（不含 callback——它跨不了进程边界）
    tool: dict | None = None


# 子进程里跑的探针：import 目标模块、取出 TOOL、把能序列化的部分写进结果文件。
#
# 结果走文件而不是 stdout：生成的代码里可能有 print（模型很爱加调试输出），
# 那会把 stdout 搅成非 JSON，解析失败又会被误报成"模块有问题"。
_PROBE = r'''
import importlib.util, json, sys, traceback

module_path, result_path = sys.argv[1], sys.argv[2]

def write(payload):
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, default=str)

try:
    spec = importlib.util.spec_from_file_location("_studio_gen_probe", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
except BaseException:
    # BaseException 而不是 Exception：模块顶层一句 sys.exit() 抛的是
    # SystemExit，不接住的话子进程静静退出、结果文件是空的，父进程只能报一句
    # 没有信息量的"没有输出"。
    lines = traceback.format_exc().strip().splitlines()
    write({"ok": False, "error": lines[-1] if lines else "import 失败"})
    sys.exit(0)

tool = getattr(module, "TOOL", None)
if tool is None:
    write({"ok": False, "error": "模块里没有定义 TOOL"})
elif not isinstance(tool, dict):
    write({"ok": False, "error": "TOOL 必须是 dict，实际是 " + type(tool).__name__})
else:
    write({
        "ok": True,
        "name": tool.get("name"),
        "description": tool.get("description"),
        "parameters": tool.get("parameters"),
        "callable": callable(tool.get("callback")),
    })
'''


def is_valid_tool_name(name: str) -> bool:
    """名字合法才允许拿它拼文件路径。gen_tools 落 stub 前要单独问一次：名字
    本身不合法的时候绝不能写文件（那等于按模型给的路径写盘）。"""
    return bool(isinstance(name, str) and _NAME_RE.match(name))


def _check_name(name: str) -> str | None:
    if not isinstance(name, str) or not name:
        return "工具名不能为空"
    if not _NAME_RE.match(name):
        return (
            f"工具名 {name!r} 不合法：只能用小写字母、数字、下划线，且不能以数字"
            f"开头（这个名字会直接当文件名用）"
        )
    return None


def _check_parameters(params: object) -> str | None:
    """只校验用得上的那部分 JSON Schema，不引入 jsonschema 依赖。

    检查的是"元 agent 绑定这个工具时需要看懂的东西"：是不是 object、有没有
    properties、required 里点名的字段是不是真的声明过。更深的 schema 语义
    （format、oneOf 之类）运行时根本没人消费，校验了也只是给模型加无谓的门槛。
    """
    if not isinstance(params, dict):
        return f"TOOL['parameters'] 必须是 dict，实际是 {type(params).__name__}"
    if params.get("type") != "object":
        return "TOOL['parameters'] 的 type 必须是 \"object\""
    props = params.get("properties")
    if not isinstance(props, dict):
        return "TOOL['parameters'] 缺少 properties，或者它不是 dict"
    required = params.get("required", [])
    if not isinstance(required, list) or not all(isinstance(r, str) for r in required):
        return "TOOL['parameters'] 的 required 必须是字符串列表"
    missing = [r for r in required if r not in props]
    if missing:
        return f"required 里的 {missing} 没有在 properties 里声明"
    return None


def validate_tool_source(name: str, code: str) -> ValidationResult:
    """四步校验：名字 → 语法 → 子进程 import 取 TOOL → 结构/schema。

    **为什么必须开子进程**：这一步要 import 模块，而 import 会执行模块顶层
    代码。生成的代码里一个顶层死循环或者 sys.exit()，在进程内 import 就会挂死
    甚至干掉整个 Studio 后端。子进程 + 超时把它变成一条可以报告的错误。

    注意这是**正确性**上的隔离，不是安全隔离：子进程照样能读写文件、发网络
    请求。真要防恶意代码得上沙箱，而元 agent 本来就有 fs 写权限，Phase 5 不
    扩大这个面，也不假装解决它（见模块 docstring）。
    """
    name_error = _check_name(name)
    if name_error:
        return ValidationResult(False, name_error)

    try:
        ast.parse(code)
    except SyntaxError as exc:
        return ValidationResult(
            False, f"语法错误（第 {exc.lineno} 行）：{exc.msg}"
        )

    with tempfile.TemporaryDirectory(prefix="senza-toolgen-") as tmp:
        module_path = Path(tmp) / f"{name}.py"
        module_path.write_text(code, encoding="utf-8")
        result_path = Path(tmp) / "result.json"
        probe_path = Path(tmp) / "_probe.py"
        probe_path.write_text(_PROBE, encoding="utf-8")

        try:
            subprocess.run(
                [sys.executable, str(probe_path), str(module_path), str(result_path)],
                cwd=tmp,
                capture_output=True,
                timeout=IMPORT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return ValidationResult(
                False,
                f"import 超时（>{IMPORT_TIMEOUT_SECONDS}s）——模块顶层是不是有"
                f"死循环或者阻塞的网络请求？工具的实际工作应该放在 callback 里，"
                f"不要放在模块顶层。",
            )

        if not result_path.exists():
            return ValidationResult(False, "import 子进程没有产生结果（可能已崩溃）")
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return ValidationResult(False, "import 子进程返回的结果无法解析")

    if not payload.get("ok"):
        return ValidationResult(False, f"import 失败：{payload.get('error')}")

    actual_name = payload.get("name")
    if actual_name != name:
        return ValidationResult(
            False,
            f"TOOL['name'] 是 {actual_name!r}，但请求生成的是 {name!r}——两者必须"
            f"一致，spec 里 bind_tool 引用的是后者",
        )
    if not payload.get("callable"):
        return ValidationResult(False, "TOOL['callback'] 不是可调用对象")
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        return ValidationResult(False, "TOOL['description'] 不能为空")

    params_error = _check_parameters(payload.get("parameters"))
    if params_error:
        return ValidationResult(False, params_error)

    return ValidationResult(
        True,
        None,
        {
            "name": actual_name,
            "description": description,
            "parameters": payload.get("parameters"),
        },
    )


def stub_source(name: str, description: str, error: str) -> str:
    """连续校验失败之后落的占位实现。

    为什么要落一个文件而不是什么都不写：spec 里多半已经 bind_tool 引用了这个
    名字，什么都不写的话 Play 报的是 "tool not found"，看不出是生成失败还是名字
    写错。stub 会在真正跑到这一步时带着最后一条校验错误炸出来，指向明确，而且
    人接手时有个现成的文件可以改。
    """
    return (
        '"""自动生成失败后的占位实现——需要人工补充。\n\n'
        f"最后一次校验错误：{error}\n"
        '"""\n'
        "from __future__ import annotations\n\n\n"
        f"def {name}(args: dict):\n"
        "    raise NotImplementedError(\n"
        f"        {json.dumps(f'工具 {name} 自动生成失败，需要人工补充实现：{error}', ensure_ascii=False)}\n"
        "    )\n\n\n"
        "TOOL = {\n"
        f"    {json.dumps('name', ensure_ascii=False)}: {json.dumps(name, ensure_ascii=False)},\n"
        f"    {json.dumps('description', ensure_ascii=False)}: {json.dumps(description, ensure_ascii=False)},\n"
        '    "parameters": {"type": "object", "properties": {}},\n'
        f"    \"callback\": {name},\n"
        '    "stub": True,\n'
        "}\n"
    )
