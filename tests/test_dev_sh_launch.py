"""dev.sh 启动参数的安全测试:静态契约 + 真实包装器组件验证。

安全边界(最高优先级):

- **不执行**仓库 dev.sh。dev.sh 启动前会用 `lsof` / `pgrep` 清理“占用端口或
  进程名匹配”的进程;PATH stub、临时 HOME、独立进程组都不能可靠约束这种
  宿主级行为。此前正是真实入口测试触发了这类清理。
- **不发送** SIGTERM / SIGINT,不启动、停止或探测任何真实 Studio 服务。
- 因此真实 dev.sh 的端到端启动/SIGTERM 行为不在自动化测试范围内,标记为
  未验证;这里只验证生产文件中可直接静态检查的启动参数,以及真实
  `scripts/provider-network.py` 的命令行行为。

运行: python3 -m pytest tests/test_dev_sh_launch.py -q
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
DEV_SH = REPO / "dev.sh"
WRAPPER = REPO / "scripts" / "provider-network.py"

BACKEND_START = "# ── 启动后端"
BACKEND_READY = "# ── 等待后端就绪"


def _backend_block():
    """从生产 dev.sh 中截取后端启动段(不含就绪轮询与前端)。"""
    text = DEV_SH.read_text()
    start = text.index(BACKEND_START)
    end = text.index(BACKEND_READY, start)
    return text[start:end]


class DevShStaticContract(unittest.TestCase):
    """断言直接读取生产 dev.sh,不复制一份启动器。"""

    def test_backend_only_launched_through_wrapper(self):
        block = _backend_block()
        # 后端命令只出现一次,且作为 BACKEND_ARGS 的最后一个参数。
        self.assertEqual(block.count("python -m studio_backend.server"), 1)
        self.assertEqual(block.count("scripts/provider-network.py"), 1)
        self.assertIn(
            'python3 scripts/provider-network.py -- "${BACKEND_ARGS[@]}" &',
            block,
        )
        # 旧写法:后台直接启动 python,绕过包装器。
        self.assertNotIn("python -m studio_backend.server &", block)

    def test_env_assignments_precede_program(self):
        block = _backend_block()
        base = block.index("BACKEND_ARGS=(env ")
        model = block.index('BACKEND_ARGS+=("SENZA_STUDIO_MODEL=$MODEL")')
        program = block.index("BACKEND_ARGS+=(python -m studio_backend.server)")
        wrapper = block.index("scripts/provider-network.py")
        self.assertLess(base, model)
        self.assertLess(model, program)
        self.assertLess(program, wrapper)

        # 基础数组:第一个参数必须是 env,否则 wrapper 会把赋值串当程序名。
        self.assertIn(
            'BACKEND_ARGS=(env PYTHONPATH=studio_backend '
            '"SENZA_STUDIO_API_TOKEN=$API_TOKEN")',
            block,
        )

    def test_model_assignment_is_inside_explicit_model_branch(self):
        block = _backend_block()
        branch_start = block.index('if [ -n "$MODEL" ]; then')
        branch_end = block.index("\nfi\n", branch_start)
        branch = block[branch_start:branch_end]
        self.assertIn('BACKEND_ARGS+=("SENZA_STUDIO_MODEL=$MODEL")', branch)
        # 整个启动块只在这一处设置 SENZA_STUDIO_MODEL。
        self.assertEqual(block.count("SENZA_STUDIO_MODEL="), 1)

    def test_model_value_stays_quoted_in_array(self):
        block = _backend_block()
        self.assertIn('BACKEND_ARGS+=("SENZA_STUDIO_MODEL=$MODEL")', block)
        # 旧写法把赋值串放在行首(直接命令前缀),wrapper 无法解析。
        self.assertNotIn('SENZA_STUDIO_MODEL="$MODEL" PYTHONPATH=', block)

    def test_bash_syntax_is_valid_without_execution(self):
        # bash -n 只解析,不执行任何命令。
        result = subprocess.run(
            ["bash", "-n", str(DEV_SH)], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_personal_paths_or_credentials(self):
        for path in (DEV_SH, WRAPPER):
            text = path.read_text()
            with self.subTest(path=path.name):
                self.assertNotIn("/home/", text)
                self.assertNotIn("/Users/", text)
                self.assertNotRegex(text, r"sk-[A-Za-z0-9]{8,}")


class WrapperCommandContract(unittest.TestCase):
    """用真实 provider-network.py 验证 dev.sh 实际使用的命令行形状。

    dev.sh 传给包装器的是 `env <ASSIGN>... python -m studio_backend.server`;
    这里用同样的 env 前缀与一个只读子进程替换后端,不触碰 Studio 代码或服务。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _config(self, no_proxy):
        (self.root / "provider-network.json").write_text(
            json.dumps({"version": 1, "no_proxy": no_proxy})
        )

    def _env(self, **extra):
        env = dict(os.environ, SENZA_STUDIO_DATA_ROOT=str(self.root))
        for key in ("STUDIO_NO_PROXY_APPEND", "STUDIO_PROVIDER_NETWORK_APPLIED",
                    "NO_PROXY", "no_proxy"):
            env.pop(key, None)
        env.pop("SENZA_STUDIO_MODEL", None)
        env.update(extra)
        return env

    def _run(self, assignments, script, env):
        command = [sys.executable, str(WRAPPER), "--", "env", *assignments,
                   sys.executable, "-c", script]
        return subprocess.run(command, env=env, capture_output=True, text=True,
                              timeout=20)

    def test_env_assignments_reach_backend(self):
        self._config(["api.example.com"])
        env = self._env(NO_PROXY="localhost,127.0.0.1,::1",
                        no_proxy="localhost")
        script = (
            "import json, os; print(json.dumps({"
            "'model': os.environ['SENZA_STUDIO_MODEL'],"
            "'token': os.environ['SENZA_STUDIO_API_TOKEN'],"
            "'pythonpath': os.environ['PYTHONPATH'],"
            "'NO_PROXY': os.environ['NO_PROXY'],"
            "'no_proxy': os.environ['no_proxy']}))"
        )
        result = self._run(
            ["PYTHONPATH=studio_backend",
             "SENZA_STUDIO_API_TOKEN=test-token",
             "SENZA_STUDIO_MODEL=model-example"],
            script, env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        seen = json.loads(result.stdout)
        self.assertEqual(seen["model"], "model-example")
        self.assertEqual(seen["token"], "test-token")
        self.assertEqual(seen["pythonpath"], "studio_backend")
        self.assertEqual(seen["NO_PROXY"],
                         "localhost,127.0.0.1,::1,api.example.com")
        self.assertEqual(seen["no_proxy"], "localhost,api.example.com")

    def test_missing_config_leaves_proxy_environment_unchanged(self):
        env = self._env(NO_PROXY="localhost,127.0.0.1,::1")
        result = self._run(
            ["PYTHONPATH=studio_backend"],
            "import os; print(os.environ['NO_PROXY']); "
            "print(os.environ.get('no_proxy', '<absent>'))",
            env,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "localhost,127.0.0.1,::1")
        self.assertEqual(lines[1], "<absent>")

    def test_invalid_config_never_starts_backend(self):
        (self.root / "provider-network.json").write_text(
            '{"version":1,"no_proxy":["http://credential-marker@example"]}'
        )
        marker = self.root / "started"
        env = self._env()
        result = self._run(
            ["PYTHONPATH=studio_backend"],
            f"from pathlib import Path; Path({str(marker)!r}).write_text('x')",
            env,
        )
        self.assertEqual(result.returncode, 2)
        self.assertFalse(marker.exists(), "backend command must not run")
        self.assertNotIn("credential-marker", result.stderr)

    def test_check_mode_never_starts_backend(self):
        self._config(["api.example.com"])
        marker = self.root / "started"
        env = self._env()
        result = subprocess.run(
            [sys.executable, str(WRAPPER), "--check", "--",
             sys.executable, "-c",
             f"from pathlib import Path; Path({str(marker)!r}).write_text('x')"],
            env=env, capture_output=True, text=True, timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("startup-only", result.stdout)
        self.assertFalse(marker.exists(), "--check must not execute command")


if __name__ == "__main__":
    unittest.main()
