"""dev.sh 启动与就绪探测回归测试。

层次:

1. DevShStaticContract / WrapperCommandContract —— 快速静态契约,以及真实
   `scripts/provider-network.py` 的命令行行为。
2. CurlLoopbackProxySemantics —— 用真实 curl 证明 `NO_PROXY=127.*` 不会覆盖
   127.0.0.1,而 `--noproxy '*'` 会直连。
3. RealDevShReadiness —— **在隔离临时目录执行生产 dev.sh 原样拷贝**。PATH
   前置替身隔离 lsof/pgrep/uv/npm/后端子进程;就绪探测调用真实 curl,但
   dev.sh 的固定 URL 被替身改写到临时端口上的回环 HTTP 服务。设置
   http_proxy 且 NO_PROXY 只有 `127.*`(缺少明确 127.0.0.1/localhost),
   验证后端与前端探测都显式 `--noproxy '*'`,且请求确实没有经过代理。

安全边界:不绑定也不探测 7878/5173,不发现或清理宿主进程,不读取真实
HOME/配置,不启动真实 Studio 服务。运行:
python3 -m pytest tests/test_dev_sh_launch.py -q
"""

import http.server
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
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


class _RecordingHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.hits.append(self.path)
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _RecordingServer(http.server.ThreadingHTTPServer):
    """临时回环 HTTP 服务,记录收到的请求路径。"""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), _RecordingHandler)
        self.hits = []
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server_port}"

    def stop(self):
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=5)


def _clean_proxy_env():
    return {
        key: value for key, value in os.environ.items()
        if key.lower() not in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    }


class CurlLoopbackProxySemantics(unittest.TestCase):
    """真实 curl 行为:证明 127.* 不是通配,而 --noproxy '*' 强制直连。"""

    def setUp(self):
        self.real_curl = shutil.which("curl")
        if not self.real_curl:
            self.skipTest("curl not installed")
        self.direct = _RecordingServer()
        self.proxy = _RecordingServer()
        self.addCleanup(self.proxy.stop)
        self.addCleanup(self.direct.stop)

    def _curl(self, url, no_proxy, noproxy=None):
        env = _clean_proxy_env()
        env["http_proxy"] = self.proxy.base_url
        env["NO_PROXY"] = no_proxy
        args = [self.real_curl, "-sf"]
        if noproxy is not None:
            args += ["--noproxy", noproxy]
        args.append(url)
        return subprocess.run(args, env=env, capture_output=True, text=True,
                              timeout=15)

    def test_wildcard_127_does_not_cover_loopback(self):
        url = f"{self.direct.base_url}/api/health"
        result = self._curl(url, "127.*,api.hyper-op.com")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.direct.hits, [], "请求不应直连")
        self.assertEqual(self.proxy.hits, [url], "127.* 不匹配 127.0.0.1")

    def test_noproxy_star_forces_direct_loopback(self):
        url = f"{self.direct.base_url}/api/health"
        result = self._curl(url, "127.*,api.hyper-op.com", noproxy="*")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.direct.hits, ["/api/health"])
        self.assertEqual(self.proxy.hits, [])

    def test_explicit_loopback_entry_also_bypasses(self):
        url = f"{self.direct.base_url}/api/health"
        result = self._curl(url, "127.0.0.1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.direct.hits, ["/api/health"])
        self.assertEqual(self.proxy.hits, [])


class RealDevShReadiness(unittest.TestCase):
    """执行生产 dev.sh 原样拷贝,验证前后端就绪探测在代理环境下直连。

    隔离:
    - dev.sh 与 provider-network.py 拷贝到临时目录;`.venv/bin/activate` 为空,
      不读取真实虚拟环境;node_modules/子包目录只建骨架。
    - PATH 前置替身:lsof/pgrep 恒返回 1(不发现宿主进程),uv/git/node 空操作,
      python 后端与 npm 是短命 sleep,真实 curl 由替身改写 URL 后执行。
    - HOME / SENZA_STUDIO_HOME / SENZA_STUDIO_DATA_ROOT 全部指向临时目录。
    - 不绑定 7878/5173;就绪探测命中临时端口上的回环服务。
    """

    BACKEND_URL = "http://127.0.0.1:7878"
    FRONTEND_URL = "http://localhost:5173"

    CURL_STUB = r'''#!__PYTHON__
import json
import os
import subprocess
import sys
from pathlib import Path

argv = sys.argv[1:]
original = argv[-1]
rewritten = original.replace(
    os.environ["STUB_BACKEND_URL"], os.environ["STUB_BACKEND_DIRECT"]
).replace(
    os.environ["STUB_FRONTEND_URL"], os.environ["STUB_FRONTEND_DIRECT"]
)
with open(os.environ["STUB_CURL_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps(
        {"args": argv, "url": original, "rewritten": rewritten},
        ensure_ascii=False,
    ) + "\n")
rc = subprocess.call([os.environ["STUB_REAL_CURL"], *argv[:-1], rewritten])
if original.startswith(os.environ["STUB_FRONTEND_URL"]) and rc == 0:
    Path(os.environ["STUB_PROBES_DONE"]).touch()
sys.exit(rc)
'''

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.real_curl = shutil.which("curl")
        self.real_python3 = shutil.which("python3")
        if not self.real_curl or not self.real_python3:
            self.skipTest("curl/python3 not installed")

        self.backend_server = _RecordingServer()
        self.frontend_server = _RecordingServer()
        self.proxy_server = _RecordingServer()
        self.addCleanup(self.proxy_server.stop)
        self.addCleanup(self.frontend_server.stop)
        self.addCleanup(self.backend_server.stop)

        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.curl_log = self.root / "curl.log"
        self.probes_done = self.root / "probes.done"
        self._write_stubs()
        self._write_sandbox()

    def _write_stub(self, name, body):
        path = self.bin / name
        path.write_text(body)
        path.chmod(0o755)

    def _write_stubs(self):
        # 后端替身:导入检查成功;`-m studio_backend.server` 驻留到 cleanup。
        self._write_stub(
            "python",
            "#!/bin/sh\n"
            'case "${1:-}" in\n'
            "  -c) exit 0 ;;\n"
            "  -m) exec sleep 2 ;;\n"
            "esac\n"
            "exit 0\n",
        )
        # python3 必须真实执行 provider-network.py;绝对路径避免自我递归。
        self._write_stub(
            "python3", f'#!/bin/sh\nexec "{self.real_python3}" "$@"\n')
        self._write_stub("npm", "#!/bin/sh\nexec sleep 2\n")
        self._write_stub("uv", "#!/bin/sh\nexit 0\n")
        self._write_stub("node", "#!/bin/sh\nexit 0\n")
        self._write_stub("git", "#!/bin/sh\nexit 0\n")
        # 关键的宿主隔离:端口/进程清理永远“没找到”。
        self._write_stub("lsof", "#!/bin/sh\nexit 1\n")
        self._write_stub("pgrep", "#!/bin/sh\nexit 1\n")
        self._write_stub(
            "curl", self.CURL_STUB.replace("__PYTHON__", sys.executable))

    def _write_sandbox(self):
        (self.root / "dev.sh").write_text(DEV_SH.read_text())
        scripts = self.root / "scripts"
        scripts.mkdir()
        (scripts / "provider-network.py").write_text(WRAPPER.read_text())
        venv_bin = self.root / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        (venv_bin / "activate").touch()  # 空 activate:不污染测试 PATH
        (self.root / "senza-studio-components").mkdir()
        (self.root / "senza-studio-runtime").mkdir()
        (self.root / "studio_frontend" / "node_modules").mkdir(parents=True)
        # 与用户现场一致:provider 直连域名存在,但 NO_PROXY 仍缺明确回环地址。
        (self.root / "provider-network.json").write_text(
            json.dumps({"version": 1, "no_proxy": ["api.example.com"]}))

    def _environment(self):
        env = _clean_proxy_env()
        env.update({
            "HOME": str(self.root),
            "SENZA_STUDIO_HOME": str(self.root / "senza-home"),
            "SENZA_STUDIO_DATA_ROOT": str(self.root),
            "SENZA_STUDIO_API_TOKEN": "test-token",
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "STUB_REAL_CURL": self.real_curl,
            "STUB_CURL_LOG": str(self.curl_log),
            "STUB_PROBES_DONE": str(self.probes_done),
            "STUB_BACKEND_URL": self.BACKEND_URL,
            "STUB_BACKEND_DIRECT": self.backend_server.base_url,
            "STUB_FRONTEND_URL": self.FRONTEND_URL,
            "STUB_FRONTEND_DIRECT": self.frontend_server.base_url,
            # 用户现场:代理开启,NO_PROXY 只有 127.*(不是明确回环地址),
            # 且没有 localhost——前后端探测都会受代理影响。
            "http_proxy": self.proxy_server.base_url,
            "HTTP_PROXY": self.proxy_server.base_url,
            "https_proxy": self.proxy_server.base_url,
            "HTTPS_PROXY": self.proxy_server.base_url,
            "NO_PROXY": "127.*,api.hyper-op.com",
            "no_proxy": "127.*,api.hyper-op.com",
        })
        for key in ("SENZA_STUDIO_MODEL", "SENZA_STUDIO_API_TOKEN_FILE",
                    "STUDIO_NO_PROXY_APPEND", "STUDIO_PROVIDER_NETWORK_APPLIED"):
            env.pop(key, None)
        return env

    @staticmethod
    def _terminate(proc):
        if proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)

    def test_readiness_bypasses_proxy_for_backend_and_frontend(self):
        proc = subprocess.Popen(
            ["bash", str(self.root / "dev.sh")],
            cwd=self.root, env=self._environment(),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )
        self.addCleanup(self._terminate, proc)
        try:
            output, _ = proc.communicate(timeout=40)
        except subprocess.TimeoutExpired:
            self._terminate(proc)
            output, _ = proc.communicate()
            self.fail(f"dev.sh 未退出:\n{output}")

        self.assertIn(proc.returncode, (0, 1),
                      f"rc={proc.returncode}\n{output}")
        self.assertIn("✅ 后端就绪", output)
        self.assertIn("✅ 前端就绪", output)
        self.assertNotIn("启动超时", output)

        records = [json.loads(line) for line in
                   self.curl_log.read_text().splitlines() if line.strip()]
        self.assertEqual(len(records), 2,
                         f"期望前后端各一次探测,实际: {records}\n{output}")
        by_url = {record["url"]: record for record in records}
        self.assertEqual(set(by_url), {self.BACKEND_URL + "/api/health",
                                       self.FRONTEND_URL + "/"})
        for url, record in by_url.items():
            args = record["args"]
            self.assertIn("--noproxy", args, f"{url} 缺少 --noproxy")
            self.assertEqual(args[args.index("--noproxy") + 1], "*",
                             f"{url} 的 --noproxy 值不是 *")

        self.assertEqual(self.backend_server.hits, ["/api/health"])
        self.assertEqual(self.frontend_server.hits, ["/"])
        self.assertEqual(self.proxy_server.hits, [],
                         "就绪探测不应经过代理")


if __name__ == "__main__":
    unittest.main()
