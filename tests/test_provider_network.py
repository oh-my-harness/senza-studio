"""provider-network.py(Senza Studio 侧)离线启动策略测试。

语义与 llm-harness-runtime/scripts/tests/test_provider_network.py 的
StartupPolicy 部分对齐;全部离线,无真实网络请求。

运行: python3 -m unittest tests.test_provider_network -v
"""

import contextlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "provider-network.py"

spec = importlib.util.spec_from_file_location("provider_network", SCRIPT)
network = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network)


class StartupPolicy(unittest.TestCase):
    # ── 配置文件存在:正确继承绕行规则 ─────────────────────────

    def test_config_entry_appended_to_no_proxy(self):
        """配置含 api.example.com 时,子进程 NO_PROXY 获得该条目。"""
        with tempfile.TemporaryDirectory() as root:
            Path(root, "provider-network.json").write_text(
                json.dumps({"version": 1, "no_proxy": ["api.hyper-op.com"]}))
            env = {"SENZA_STUDIO_DATA_ROOT": root,
                   "NO_PROXY": "localhost,127.0.0.1,::1"}
            child, source, _ = network.child_environment(env)
            self.assertEqual(child["NO_PROXY"],
                             "localhost,127.0.0.1,::1,api.hyper-op.com")
            self.assertEqual(source, "persistent file")

    def test_original_loopback_entries_preserved(self):
        """原有 localhost,127.0.0.1,::1 不丢失、顺序不变。"""
        with tempfile.TemporaryDirectory() as root:
            Path(root, "provider-network.json").write_text(
                json.dumps({"version": 1, "no_proxy": ["provider.example"]}))
            env = {"SENZA_STUDIO_DATA_ROOT": root,
                   "NO_PROXY": "localhost,127.0.0.1,::1",
                   "no_proxy": "other.example"}
            child, _, _ = network.child_environment(env)
            self.assertTrue(child["NO_PROXY"].startswith("localhost,127.0.0.1,::1"))
            self.assertEqual(child["no_proxy"], "other.example,provider.example")

    def test_repeated_launch_does_not_duplicate_entries(self):
        """重复启动(同 env 反复套包装器)不会不断追加相同条目。"""
        with tempfile.TemporaryDirectory() as root:
            Path(root, "provider-network.json").write_text(
                json.dumps({"version": 1, "no_proxy": ["api.hyper-op.com"]}))
            env = {"SENZA_STUDIO_DATA_ROOT": root,
                   "NO_PROXY": "localhost,127.0.0.1,::1",
                   "STUDIO_PROVIDER_NETWORK_APPLIED": "1"}
            expected = "localhost,127.0.0.1,::1,api.hyper-op.com"
            for _ in range(3):
                child, _, _ = network.child_environment(env)
                self.assertEqual(child["NO_PROXY"], expected)

    # ── 配置缺失/损坏:保守回退 ────────────────────────────────

    def test_missing_file_preserves_proxy_policy(self):
        with tempfile.TemporaryDirectory() as root:
            env = {"SENZA_STUDIO_DATA_ROOT": root,
                   "HTTP_PROXY": "http://proxy.example:8080",
                   "NO_PROXY": "localhost"}
            child, _, count = network.child_environment(env)
            self.assertEqual(count, 0)
            self.assertEqual(child["HTTP_PROXY"], env["HTTP_PROXY"])
            self.assertEqual(child["NO_PROXY"], "localhost")
            self.assertNotIn("no_proxy", child)

    def test_empty_and_malformed_fields_are_rejected(self):
        for policy in ['', '{}', '{"version":1}', '{"version":2,"no_proxy":[]}',
                       '{"version":1,"no_proxy":"not-a-list"}',
                       '{"version":1,"no_proxy":["example.com"],"extra":1}']:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as root:
                Path(root, "provider-network.json").write_text(policy)
                with self.assertRaises(network.PolicyError):
                    network.child_environment({"SENZA_STUDIO_DATA_ROOT": root})

    def test_invalid_policy_prevents_execution_without_leaking_value(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "provider-network.json").write_text(
                '{"version":1,"no_proxy":["http://credential-marker@example"]}')
            env = dict(os.environ, SENZA_STUDIO_DATA_ROOT=root)
            env.pop("STUDIO_NO_PROXY_APPEND", None)
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--", sys.executable, "-c",
                 "print('SHOULD_NOT_RUN')"],
                env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn("SHOULD_NOT_RUN", result.stdout)
            self.assertNotIn("credential-marker", result.stderr)

    # ── NO_PROXY / no_proxy 大小写处理 ────────────────────────

    def test_missing_uppercase_keeps_lowercase_rules(self):
        child, _, _ = network.child_environment(
            {"no_proxy": "*.example,127.0.0.1",
             "STUDIO_NO_PROXY_APPEND": "direct.example"})
        self.assertEqual(child["NO_PROXY"], "*.example,127.0.0.1,direct.example")

    def test_deduplicate_case_insensitive_and_trailing_dot(self):
        child, _, _ = network.child_environment(
            {"NO_PROXY": "DIRECT.example",
             "STUDIO_NO_PROXY_APPEND": "direct.example,DIRECT.example."})
        self.assertEqual(child["NO_PROXY"], "DIRECT.example")

    def test_env_override_takes_priority_over_file(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "provider-network.json").write_text(
                '{"version":1,"no_proxy":["from.file.example"]}')
            child, source, _ = network.child_environment(
                {"SENZA_STUDIO_DATA_ROOT": root,
                 "STUDIO_NO_PROXY_APPEND": "from.env.example"})
            self.assertEqual(source, "environment override")
            self.assertIn("from.env.example", child["NO_PROXY"])
            self.assertNotIn("from.file.example", child["NO_PROXY"])

    def test_empty_override_ignores_file(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "provider-network.json").write_text("invalid")
            child, _, count = network.child_environment(
                {"SENZA_STUDIO_DATA_ROOT": root, "STUDIO_NO_PROXY_APPEND": ""})
            self.assertEqual(count, 0)
            self.assertNotIn("NO_PROXY", child)

    # ── 值合法性:拒绝 URL/通配/端口/可执行文本 ────────────────

    def test_rejects_urls_wildcards_and_shell_text(self):
        for value in ["http://user:secret@example", "*", "example:80",
                      "$(command)", "example\nexport"]:
            with self.subTest(value=value), \
                 self.assertRaises(network.PolicyError):
                network.child_environment({"STUDIO_NO_PROXY_APPEND": value})

    # ── 不覆盖其他代理/凭据配置 ───────────────────────────────

    def test_proxy_and_credentials_untouched(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "provider-network.json").write_text(
                json.dumps({"version": 1, "no_proxy": ["provider.example"]}))
            env = {"SENZA_STUDIO_DATA_ROOT": root,
                   "HTTP_PROXY": "http://proxy.example:8080",
                   "https_proxy": "http://proxy.example:8443",
                   "OPENAI_API_KEY": "sk-should-not-appear"}
            child, _, _ = network.child_environment(env)
            self.assertEqual(child["HTTP_PROXY"], env["HTTP_PROXY"])
            self.assertEqual(child["https_proxy"], env["https_proxy"])
            self.assertEqual(child["OPENAI_API_KEY"], env["OPENAI_API_KEY"])

    # ── 子进程端到端:环境真实传递(无真实网络)────────────────

    def test_exec_passes_environment_to_child(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--", sys.executable, "-c",
             "import os; print(os.environ['NO_PROXY'])"],
            env=dict(os.environ,
                     STUDIO_NO_PROXY_APPEND="direct.example",
                     NO_PROXY="localhost,127.0.0.1,::1"),
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         "localhost,127.0.0.1,::1,direct.example")

    def test_check_only_never_launches_command(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--check", "--",
             "nonexistent-command"],
            env=dict(os.environ, STUDIO_NO_PROXY_APPEND="direct.example"),
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIn("startup-only", result.stdout)
        self.assertNotIn("direct.example", result.stdout)


if __name__ == "__main__":
    unittest.main()
