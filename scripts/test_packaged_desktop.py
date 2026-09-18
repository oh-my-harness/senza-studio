import argparse
import csv
import hashlib
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from websockets.sync.client import connect as connect_websocket


PROCESS_OUTPUT = {"stdout": [], "stderr": [], "api_token": ""}


def parse_arguments():
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--no-xvfb",
        action="store_true",
        help="Run without xvfb-run when a display is already available",
    )
    return parser.parse_args()


def reserve_port():
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def reserve_display_number():
    used = {entry.name[2:-5] for entry in Path("/tmp").glob(".X*-lock")}
    used.update(
        entry.name[1:]
        for entry in Path("/tmp/.X11-unix").glob("X*")
        if entry.is_socket()
    )
    for number in range(100, 1000):
        if str(number) not in used:
            return number
    raise AssertionError("No X11 display number is available for Xvfb")


def start_xvfb(executable):
    last_error = None
    for _ in range(5):
        display_number = reserve_display_number()
        process = subprocess.Popen(
            [
                executable,
                f":{display_number}",
                "-nolisten",
                "tcp",
                "-screen",
                "0",
                "1280x800x24",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if process.poll() is not None:
                last_error = f"Xvfb display :{display_number} exited"
                break
            if Path(f"/tmp/.X11-unix/X{display_number}").is_socket():
                return process, f":{display_number}"
            time.sleep(0.05)
        terminate_process_tree(process)
        process.wait(timeout=5)
    raise AssertionError(f"Xvfb did not become ready: {last_error}")


def request(url, api_token=None, origin=None):
    headers = {}
    if api_token:
        headers["Cookie"] = f"senza_studio_api={api_token}"
    if origin:
        headers["Origin"] = origin
    request_object = Request(url, headers=headers)
    try:
        with urlopen(request_object, timeout=2) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def wait_for_health(base_url, timeout, logs):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            status, _ = request(f"{base_url}/api/health")
            if status == 200:
                return
            last_error = f"health returned HTTP {status}"
        except Exception as error:
            last_error = str(error)
        time.sleep(0.25)
    raise AssertionError(
        "Packaged desktop did not become healthy: "
        f"{last_error}\nstdout:\n{format_process_logs(logs[0])}"
        f"\nstderr:\n{format_process_logs(logs[1])}"
    )


def format_process_logs(lines, limit=100):
    relevant_lines = [
        line
        for line in lines
        if not line.startswith("/tmp/appimage_extracted_")
    ]
    return "".join(relevant_lines[-limit:])

def windows_process_snapshot():
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        "Get-CimInstance Win32_Process | "
        "Select-Object ProcessId,ParentProcessId,CommandLine | "
        "ConvertTo-Json -Compress",
    ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    payload = json.loads(result.stdout)
    if isinstance(payload, dict):
        payload = [payload]
    return {
        int(row["ProcessId"]): {
            "parent": int(row["ParentProcessId"]),
            "command": row.get("CommandLine") or "",
        }
        for row in payload
    }


def descendants(process_id, snapshot=None):
    if sys.platform == "win32":
        if snapshot is None:
            snapshot = windows_process_snapshot()
        children = {}
        for pid, metadata in snapshot.items():
            children.setdefault(metadata["parent"], []).append(pid)
        result = []
        pending = [process_id]
        while pending:
            current = pending.pop()
            if current in result:
                continue
            result.append(current)
            pending.extend(children.get(current, []))
        return result
    result = []
    pending = [process_id]
    seen = set()
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        result.append(current)
        task_dir = Path(f"/proc/{current}/task")
        if not task_dir.is_dir():
            continue
        for task in task_dir.iterdir():
            children_file = task / "children"
            if not children_file.is_file():
                continue
            for child in children_file.read_text(encoding="utf-8").split():
                pending.append(int(child))
    return result


def process_command(process_id, snapshot=None):
    if sys.platform == "win32":
        if snapshot is None:
            snapshot = windows_process_snapshot()
        return snapshot.get(process_id, {}).get("command", "")
    try:
        return Path(f"/proc/{process_id}/cmdline").read_bytes().replace(
            b"\0", b" "
        ).decode("utf-8", errors="replace")
    except OSError:
        return ""


def process_environment(process_id):
    if sys.platform == "win32":
        return {}
    try:
        raw = Path(f"/proc/{process_id}/environ").read_bytes()
    except OSError:
        return {}
    environment = {}
    for item in raw.split(b"\0"):
        if b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        environment[key.decode("utf-8", errors="replace")] = value
    return environment


def process_alive(process_id):
    if sys.platform == "win32":
        result = subprocess.run(
            [
                "tasklist",
                "/FI",
                f"PID eq {process_id}",
                "/FO",
                "CSV",
                "/NH",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        for row in csv.reader(result.stdout.splitlines()):
            if len(row) >= 2:
                try:
                    if int(row[1]) == process_id:
                        return True
                except ValueError:
                    continue
        return False
    try:
        stat = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    process_state = stat.rsplit(")", 1)[1].split()[0]
    return process_state != "Z"


def wait_for_processes_to_exit(process_ids, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(process_alive(process_id) for process_id in process_ids):
            return True
        time.sleep(0.1)
    return not any(process_alive(process_id) for process_id in process_ids)


def drain(stream, sink):
    for line in iter(stream.readline, ""):
        sink.append(line)
    stream.close()


def terminate_process_tree(process, timeout=20.0):
    if process.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            force_kill_process_tree(process.pid)
            process.wait(timeout=timeout)
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=timeout)

def force_kill_process_tree(process_id):
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(process_id), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return
    try:
        os.killpg(process_id, signal.SIGKILL)
    except ProcessLookupError:
        pass

def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def sha256_tree(root):
    files = sorted(
        (path for path in root.rglob("*") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix().encode("utf-8"),
    )
    digest = hashlib.sha256()
    for path in files:
        contents = path.read_bytes()
        relative_path = path.relative_to(root).as_posix()
        digest.update(f"{relative_path}\0{len(contents)}\0".encode("utf-8"))
        digest.update(contents)
        digest.update(b"\0")
    return digest.hexdigest()

def verify_packaged_resources(install_dir):
    resources = install_dir / "resources"
    manifest_path = resources / "desktop-resources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    is_windows = sys.platform == "win32"
    runtime_name = "agent-studio.exe" if is_windows else "agent-studio"
    python_name = (
        Path("python") / "python.exe"
        if is_windows
        else Path("python") / "bin" / "python"
    )
    backend_entrypoint = (
        Path("senza-studio-backend") / "studio_backend" / "server.py"
    )
    frontend_bundle = Path("studio_frontend") / "dist"

    checks = {
        "agent_team_sha256": (resources / runtime_name, sha256_file),
        "python_executable_sha256": (resources / python_name, sha256_file),
        "backend_entrypoint_sha256": (
            resources / backend_entrypoint,
            sha256_file,
        ),
        "frontend_bundle_sha256": (
            resources / frontend_bundle,
            sha256_tree,
        ),
    }
    for field, (path, digest_function) in checks.items():
        expected = manifest.get(field)
        if not isinstance(expected, str) or digest_function(path) != expected:
            raise AssertionError(f"Packaged resource checksum mismatch: {field}")
    if not isinstance(manifest.get("agent_team_source_sha256"), str):
        raise AssertionError("Agent Team source checksum is missing")

    runtime_metadata = json.loads(
        (resources / "python-runtime.json").read_text(encoding="utf-8")
    )
    platform_name = "windows-x86_64" if is_windows else "linux-x86_64"
    platform = runtime_metadata.get("platforms", {}).get(platform_name)
    if not platform or platform.get("sha256") != manifest.get("python_archive_sha256"):
        raise AssertionError("Packaged Python runtime metadata mismatch")

def install_windows_artifact(artifact, install_dir, environment, timeout):
    command = [str(artifact), "/S", f"/D={install_dir}"]
    subprocess.run(
        command,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    executables = [
        path
        for path in install_dir.glob("*.exe")
        if not path.name.lower().startswith("uninstall")
    ]
    if len(executables) != 1:
        raise AssertionError(
            f"Expected one installed application executable, found: {executables}"
        )
    return executables[0]

def uninstall_windows_artifact(install_dir, timeout):
    uninstaller = next(
        (path for path in install_dir.glob("Uninstall*.exe")),
        None,
    )
    if uninstaller is None:
        return
    subprocess.run(
        [str(uninstaller), "/S"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def remove_tree_with_retry(path, timeout=15.0):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            shutil.rmtree(path)
            return
        except PermissionError as error:
            last_error = error
            time.sleep(0.25)
    if path.exists():
        raise AssertionError(
            f"Temporary directory remained locked: {path}: {last_error}"
        )


def read_diagnostics(config_root):
    matches = list(config_root.rglob("desktop.jsonl"))
    if not matches:
        return []
    events = []
    for line in matches[0].read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def wait_for_startup_diagnostics(config_root, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = read_diagnostics(config_root)
        failures = [
            event
            for event in events
            if event.get("data", {}).get("type") == "startup-failed"
        ]
        if failures:
            raise AssertionError(f"Packaged desktop startup failed: {failures[-1]}")
        if any(
            event.get("data", {}).get("type") == "started" for event in events
        ):
            return
        time.sleep(0.1)
    raise AssertionError("Packaged desktop did not record a started lifecycle event")


def assert_diagnostics(config_root):
    events = read_diagnostics(config_root)
    if not any(
        event.get("data", {}).get("type") == "started" for event in events
    ):
        raise AssertionError("Packaged desktop did not record a started lifecycle event")
    failures = [
        event
        for event in events
        if event.get("data", {}).get("type") == "startup-failed"
    ]
    if failures:
        raise AssertionError(f"Packaged desktop startup failed: {failures[-1]}")


def assert_private_api(base_url, api_token):
    health_status, _ = request(f"{base_url}/api/health")
    if health_status != 200:
        raise AssertionError(f"Public health endpoint failed: HTTP {health_status}")
    unauthenticated_status, _ = request(f"{base_url}/")
    if unauthenticated_status not in (401, 403):
        raise AssertionError(
            f"Static UI was not protected: HTTP {unauthenticated_status}"
        )
    private_status, _ = request(f"{base_url}/api/settings")
    if private_status != 401:
        raise AssertionError(f"Private API was not protected: HTTP {private_status}")
    authenticated_status, body = request(f"{base_url}/", api_token)
    if authenticated_status != 200 or b"<title>Senza Studio</title>" not in body:
        raise AssertionError(
            "Authenticated static UI did not load: "
            f"HTTP {authenticated_status}: {body[:512]!r}"
        )
    authenticated_private_status, _ = request(
        f"{base_url}/api/settings", api_token
    )
    if authenticated_private_status != 200:
        raise AssertionError(
            "Authenticated private API failed: "
            f"HTTP {authenticated_private_status}"
        )

    asset_paths = re.findall(
        r'(?:src|href)="/(assets/[^"]+)"',
        body.decode("utf-8", errors="strict"),
    )
    if not asset_paths:
        raise AssertionError("Static UI did not reference production assets")
    for asset_path in asset_paths:
        asset_status, asset_body = request(
            f"{base_url}/{asset_path}", api_token, base_url
        )
        if asset_status != 200 or not asset_body:
            raise AssertionError(
                "Authenticated static UI asset did not load: "
                f"/{asset_path}: HTTP {asset_status}"
            )

def assert_agent_descriptor(appdata):
    descriptor_paths = list(appdata.rglob("panel.json"))
    if not descriptor_paths:
        raise AssertionError("Agent Team descriptor was not created under app data")
    descriptor = json.loads(descriptor_paths[0].read_text(encoding="utf-8"))
    if descriptor.get("schema") != "llm-harness.studio.panel-descriptor.v1":
        raise AssertionError("Agent Team descriptor schema is invalid")

def wait_for_agent_restart(root_process_id, previous_process_id, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snapshot = windows_process_snapshot()
        process_ids = descendants(root_process_id, snapshot)
        restarted = [
            process_id
            for process_id in process_ids
            if process_id != previous_process_id
            and "agent-studio" in process_command(process_id, snapshot).lower()
        ]
        if restarted:
            return restarted[0]
        time.sleep(0.25)
    raise AssertionError("Agent Team runtime did not restart")

def leaked_processes(process_ids):
    return [
        {
            "pid": process_id,
            "command": process_command(process_id),
        }
        for process_id in process_ids
        if process_alive(process_id)
    ]


def wait_for_cdp_page(port, timeout):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1) as response:
                targets = json.loads(response.read().decode("utf-8"))
            pages = [
                target
                for target in targets
                if target.get("type") == "page"
                and target.get("url", "").startswith("http://127.0.0.1:")
            ]
            if pages:
                return pages[0]
            last_error = f"CDP exposed no page targets: {targets!r}"
        except Exception as error:
            last_error = str(error)
        time.sleep(0.1)
    raise AssertionError(f"Packaged desktop CDP page did not become ready: {last_error}")


class ChromeDevToolsSession:
    def __init__(self, websocket_url, timeout=10.0):
        self.websocket = connect_websocket(
            websocket_url,
            open_timeout=timeout,
            close_timeout=timeout,
            legacy=True,
        )
        self.timeout = timeout
        self.next_request_id = 1
        self.pending_dialog_response_id = None

    def close(self):
        self.websocket.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def _send(self, method, parameters=None):
        request_id = self.next_request_id
        self.next_request_id += 1
        self.websocket.send(
            json.dumps({"id": request_id, "method": method, "params": parameters or {}})
        )
        return request_id

    def _receive_until(self, request_id):
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"CDP request {request_id} timed out")
            message = json.loads(self.websocket.recv(timeout=remaining))
            if message.get("id") == request_id:
                if "error" in message:
                    raise AssertionError(f"CDP request failed: {message['error']}")
                return message.get("result", {})
            if message.get("id") == self.pending_dialog_response_id:
                self.pending_dialog_response_id = None
            elif message.get("method") == "Page.javascriptDialogOpening":
                self.pending_dialog_response_id = self._send(
                    "Page.handleJavaScriptDialog", {"accept": True}
                )

    def call(self, method, parameters=None):
        return self._receive_until(self._send(method, parameters))

    def evaluate(self, expression, await_promise=False):
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        if result.get("exceptionDetails"):
            raise AssertionError(
                f"CDP JavaScript evaluation failed: {result['exceptionDetails']}"
            )
        return result.get("result", {}).get("value")


def wait_for_ui(session, expression, description, timeout=15.0):
    deadline = time.monotonic() + timeout
    last_value = None
    while time.monotonic() < deadline:
        last_value = session.evaluate(expression)
        if last_value:
            return last_value
        time.sleep(0.1)
    raise AssertionError(
        f"Packaged desktop UI condition failed: {description}; last value: {last_value!r}"
    )


def click_button(session, text, timeout=15.0):
    expression = """
    (() => {
      const button = Array.from(document.querySelectorAll('button'))
        .find((candidate) => candidate.textContent.includes(arguments[0]));
      if (!button || button.disabled) return false;
      button.click();
      return true;
    })()
    """.replace(
        "arguments[0]", json.dumps(text)
    )
    deadline = time.monotonic() + timeout
    clicked = None
    while not clicked and time.monotonic() < deadline:
        clicked = session.evaluate(expression)
        if not clicked:
            time.sleep(0.1)
    if not clicked:
        raise AssertionError(f"UI button was not clickable: {text}")


def click_test_id_button(session, test_id, timeout=15.0):
    selector = json.dumps(f"[data-testid={json.dumps(test_id)}]")
    expression = f"""
    (() => {{
      const button = document.querySelector({selector});
      if (!button || button.disabled) return false;
      button.click();
      return true;
    }})()
    """
    deadline = time.monotonic() + timeout
    clicked = None
    while not clicked and time.monotonic() < deadline:
        clicked = session.evaluate(expression)
        if not clicked:
            time.sleep(0.1)
    if not clicked:
        raise AssertionError(f"UI button was not clickable: {test_id}")


def set_input_value(session, aria_label, value):
    selector = json.dumps(
        f'[aria-label="{aria_label}"], [placeholder="{aria_label}"]'
    )
    set = session.evaluate(
        """
        (() => {
          const selector = JSON.stringify(arguments[0]);
          const input = document.querySelector(
            `[aria-label=${selector}], [placeholder=${selector}]`
          );
          if (!input) return false;
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype,
            'value'
          ).set;
          setter.call(input, arguments[1]);
          input.dispatchEvent(new Event('input', {bubbles: true}));
          return true;
        })()
        """.replace(
            "arguments[0]", json.dumps(aria_label)
        ).replace(
            "arguments[1]", json.dumps(value)
        )
    )
    if not set:
        raise AssertionError(f"UI input was not found: {aria_label}")
    expression = f"""
    new Promise((resolve) => {{
      requestAnimationFrame(() => {{
        resolve(document.querySelector({selector})?.value);
      }});
    }})
    """
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        current_value = session.evaluate(expression, await_promise=True)
        if current_value == value:
            return
        time.sleep(0.05)
    raise AssertionError(
        f"UI input value did not settle: {aria_label}; "
        f"expected {value!r}, got {current_value!r}"
    )


def open_agent_teams(session):
    click_button(session, "打开 Agent Teams")
    wait_for_ui(
        session,
        "Boolean(document.querySelector('[data-testid=\"agent-team-list\"]'))",
        "Agent Team workspace visible",
    )


def configure_runtime_settings(session):
    wait_for_ui(
        session,
        "document.readyState === 'complete'",
        "application document loaded",
    )
    wait_for_ui(
        session,
        "document.querySelector('[data-testid=\"agent-team-runtime-settings\"]')?.dataset.ready === 'true'",
        "runtime settings loaded",
    )
    for label, value in (
        ("AgentTeam strong 模型", "packaged-desktop-model"),
        ("AgentTeam main 模型", "packaged-desktop-model"),
        ("AgentTeam cheap 模型", "packaged-desktop-model"),
        ("AgentTeam API base URL", "http://127.0.0.1:9"),
        ("AgentTeam scout 间隔秒数", "0"),
        ("AgentTeam API key", "packaged-desktop-dummy-key"),
    ):
        set_input_value(session, label, value)
    click_button(session, "保存 Runtime 设置")
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        error_text = session.evaluate(
            """
            document.querySelector(
              '[data-testid="agent-team-action-error"]'
            )?.textContent.trim() || ''
            """
        )
        if error_text:
            raise AssertionError(f"Runtime settings save failed: {error_text}")
        saved = session.evaluate(
            """
            document.querySelector('[aria-label="AgentTeam API key"]')
              ?.placeholder.includes('已设置') === true
            """
        )
        if saved:
            return
        time.sleep(0.1)
    raise AssertionError("Runtime settings save timed out")


def create_agent_team(session, team_id):
    set_input_value(session, "团队 ID", team_id)
    set_input_value(session, "团队显示名称", "Packaged desktop E2E")
    click_button(session, "创建团队")
    wait_for_ui(
        session,
        f"document.querySelector('[data-testid=\"agent-team-list\"]').textContent.includes({json.dumps(team_id)})",
        "created team visible",
        timeout=20.0,
    )
    wait_for_ui(
        session,
        "Array.from(document.querySelector('[data-testid=\"agent-team-members\"]').children).length > 0",
        "team member pulse loaded",
        timeout=20.0,
    )


def select_team(session, team_id):
    expression = """
    (() => {
      const list = document.querySelector('[data-testid="agent-team-list"]');
      const button = Array.from(list.querySelectorAll('button'))
        .find((candidate) => candidate.textContent.trim() === arguments[0]);
      if (!button) return false;
      button.click();
      return true;
    })()
    """.replace(
        "arguments[0]", json.dumps(team_id)
    )
    deadline = time.monotonic() + 15.0
    selected = None
    while not selected and time.monotonic() < deadline:
        selected = session.evaluate(expression)
        if not selected:
            time.sleep(0.1)
    if not selected:
        raise AssertionError(f"Team was not selectable: {team_id}")
    wait_for_ui(
        session,
        "Array.from(document.querySelector('[data-testid=\"agent-team-members\"]').children).length > 0",
        "persisted team member pulse loaded",
        timeout=20.0,
    )


def select_planner_and_send_message(session, message):
    click_button(session, "planner")
    wait_for_ui(
        session,
        "document.querySelector('#agent-team-message').disabled === false",
        "planner selected and message input enabled",
    )
    set_input_value(session, "输入任务或消息", message)
    click_button(session, "发送")
    wait_for_ui(
        session,
        "document.querySelector('#agent-team-message').value === ''",
        "chat message accepted",
        timeout=20.0,
    )
    wait_for_ui(
        session,
        """
        (() => {
          const state = document.querySelector(
            '[data-testid="agent-team-connection"]'
          ).textContent.trim();
          return state === '已连接' ? true : state;
        })()
        """,
        "Agent Team event stream connected",
        timeout=20.0,
    )
    wait_for_ui(
        session,
        f"""
        (() => {{
          const text = document.querySelector('[data-testid="agent-team-events"]').textContent;
          return text.includes({json.dumps(message)}) ? true : text;
        }})()
        """,
        "operator chat event visible",
        timeout=20.0,
    )


def restart_agent_team(session, team_id):
    session.evaluate("window.confirm = () => true")
    click_test_id_button(session, "agent-team-restart")
    wait_for_ui(
        session,
        "document.querySelector('[data-testid=\"agent-team-restart\"]').disabled === true",
        "restart action started",
    )
    wait_for_ui(
        session,
        "document.querySelector('[data-testid=\"agent-team-restart\"]').disabled === false",
        "restart action completed",
        timeout=20.0,
    )
    wait_for_ui(
        session,
        "!document.querySelector('[data-testid=\"agent-team-action-error\"]')",
        "restart action succeeded",
    )
    wait_for_ui(
        session,
        f"document.querySelector('[data-testid=\"agent-team-list\"]').textContent.includes({json.dumps(team_id)})",
        "team remains after restart",
        timeout=20.0,
    )
    wait_for_ui(
        session,
        "Array.from(document.querySelector('[data-testid=\"agent-team-members\"]').children).length > 0",
        "team members remain after restart",
        timeout=20.0,
    )


def delete_agent_team(session, team_id):
    session.evaluate("window.confirm = () => true")
    click_button(session, "删除")
    wait_for_ui(
        session,
        "document.querySelector('[data-testid=\"agent-team-list\"]').textContent.trim() === '暂无团队'",
        "team deleted",
        timeout=20.0,
    )


def drive_agent_team_workspace(port, team_id, message, configure, create, restart, delete):
    page = wait_for_cdp_page(port, 15.0)
    with ChromeDevToolsSession(page["webSocketDebuggerUrl"]) as session:
        open_agent_teams(session)
        if configure:
            configure_runtime_settings(session)
        if create:
            create_agent_team(session, team_id)
        else:
            select_team(session, team_id)
        select_planner_and_send_message(session, message)
        if restart:
            restart_agent_team(session, team_id)
        if delete:
            delete_agent_team(session, team_id)

def main():
    arguments = parse_arguments()
    is_windows = sys.platform == "win32"
    if sys.platform not in ("linux", "win32"):
        raise SystemExit("This packaged desktop E2E supports Linux and Windows")
    if not arguments.artifact.is_file() or not os.access(arguments.artifact, os.X_OK):
        raise SystemExit(f"Artifact is not executable: {arguments.artifact}")

    xvfb_executable = shutil.which("Xvfb") if sys.platform == "linux" else None
    if sys.platform == "linux" and arguments.no_xvfb and not os.environ.get("DISPLAY"):
        raise SystemExit("DISPLAY is required when --no-xvfb is used")
    if sys.platform == "linux" and not arguments.no_xvfb and not xvfb_executable:
        raise SystemExit("Xvfb is required for headless packaged desktop E2E")

    port = reserve_port()
    cdp_port = reserve_port()
    api_token = secrets.token_urlsafe(32)
    PROCESS_OUTPUT["api_token"] = api_token
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(
        prefix="senza-studio-e2e-", ignore_cleanup_errors=True
    ) as temporary_directory:
        temporary_root = Path(temporary_directory)
        home = temporary_root / "home"
        cache_home = temporary_root / "cache"
        python_user_base = temporary_root / "python-user"
        if is_windows:
            appdata = temporary_root / "appdata"
            localappdata = temporary_root / "localappdata"
            programdata = temporary_root / "programdata"
            temp_home = temporary_root / "temp"
            user_data = temporary_root / "user-data"
            diagnostics_root = user_data
            python_user_site = (
                python_user_base / "Python312" / "site-packages"
            )
            for directory in (
                home,
                cache_home,
                appdata,
                localappdata,
                programdata,
                temp_home,
                user_data,
                python_user_site,
            ):
                directory.mkdir(parents=True)
        else:
            config_home = temporary_root / "config"
            diagnostics_root = config_home
            python_user_site = (
                python_user_base / "lib" / "python3.12" / "site-packages"
            )
            for directory in (home, config_home, cache_home, python_user_site):
                directory.mkdir(parents=True)

        user_site_marker = temporary_root / "user-site-loaded"
        (python_user_site / "sitecustomize.py").write_text(
            f'from pathlib import Path\nPath({str(user_site_marker)!r}).touch()\n',
            encoding="utf-8",
        )
        environment = {
            **os.environ,
            "HOME": str(home),
            "PYTHONUSERBASE": str(python_user_base),
            "SENZA_STUDIO_HOME": str(temporary_root / "studio-home"),
            "SENZA_STUDIO_API_TOKEN": api_token,
            "SENZA_STUDIO_PORT": str(port),
            "ELECTRON_DISABLE_GPU": "1",
            "ELECTRON_CACHE": str(cache_home),
        }
        for override in (
            "ELECTRON_RUN_AS_NODE",
            "SENZA_STUDIO_AGENT_TEAM_BIN",
            "SENZA_STUDIO_PYTHON",
        ):
            environment.pop(override, None)
        if is_windows:
            environment.update(
                {
                    "APPDATA": str(appdata),
                    "LOCALAPPDATA": str(localappdata),
                    "PROGRAMDATA": str(programdata),
                    "TEMP": str(temp_home),
                    "TMP": str(temp_home),
                }
            )
        else:
            environment.update(
                {
                    "XDG_CONFIG_HOME": str(config_home),
                    "XDG_CACHE_HOME": str(cache_home),
                }
            )

        install_dir = None
        xvfb_process = None
        if sys.platform == "linux" and not arguments.no_xvfb:
            xvfb_process, display = start_xvfb(xvfb_executable)
            environment["DISPLAY"] = display
        if is_windows:
            install_dir = temporary_root / "install"
            app_executable = install_windows_artifact(
                arguments.artifact,
                install_dir,
                environment,
                arguments.timeout,
            )
            verify_packaged_resources(install_dir)
        else:
            app_executable = arguments.artifact

        def start_application():
            command = [
                str(app_executable),
                f"--remote-debugging-port={cdp_port}",
            ]
            if is_windows:
                command.append(f"--user-data-dir={user_data}")
            if not is_windows:
                command.extend(["--appimage-extract-and-run", "--no-sandbox"])
            stdout = []
            stderr = []
            PROCESS_OUTPUT["stdout"] = stdout
            PROCESS_OUTPUT["stderr"] = stderr
            process = subprocess.Popen(
                command,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=not is_windows,
            )
            threads = [
                threading.Thread(
                    target=drain, args=(process.stdout, stdout), daemon=True
                ),
                threading.Thread(
                    target=drain, args=(process.stderr, stderr), daemon=True
                ),
            ]
            for thread in threads:
                thread.start()
            return process, stdout, stderr, threads

        process = None
        threads = []
        tracked_process_ids = []
        try:
            process, stdout, stderr, threads = start_application()
            try:
                wait_for_health(base_url, arguments.timeout, (stdout, stderr))
                tracked_process_ids = descendants(process.pid)
                if user_site_marker.exists():
                    raise AssertionError("Backend loaded packages from user site")
                assert_private_api(base_url, api_token)

                snapshot = windows_process_snapshot() if is_windows else None
                process_ids = descendants(process.pid, snapshot)
                tracked_process_ids = process_ids
                agent_processes = [
                    process_id
                    for process_id in process_ids
                    if "agent-studio" in process_command(
                        process_id, snapshot
                    ).lower()
                ]
                backend_processes = [
                    process_id
                    for process_id in process_ids
                    if "studio_backend.server" in process_command(
                        process_id, snapshot
                    )
                ]
                if not agent_processes or not backend_processes:
                    raise AssertionError(
                        "Agent Team or backend process was not running"
                    )
                if is_windows:
                    assert_agent_descriptor(user_data)
                else:
                    for process_id in agent_processes:
                        environment_data = process_environment(process_id)
                        if (
                            "SENZA_STUDIO_API_TOKEN" in environment_data
                            or api_token.encode() in environment_data.values()
                        ):
                            raise AssertionError(
                                "Agent Team runtime received the Studio API token"
                            )
                    if not any(
                        api_token.encode()
                        in process_environment(process_id).values()
                        for process_id in backend_processes
                    ):
                        raise AssertionError(
                        "Backend did not receive the Studio API token"
                    )

                wait_for_startup_diagnostics(diagnostics_root, 15.0)
                team_id = f"e2e-{secrets.token_hex(8)}"
                chat_message = "packaged desktop user flow"
                drive_agent_team_workspace(
                    cdp_port,
                    team_id,
                    chat_message,
                    configure=True,
                    create=True,
                    restart=True,
                    delete=False,
                )
                if is_windows:
                    force_kill_process_tree(agent_processes[0])
                    wait_for_agent_restart(process.pid, agent_processes[0], 15.0)
                    wait_for_health(base_url, 15.0, (stdout, stderr))
                    process_ids = descendants(process.pid)
                    tracked_process_ids = process_ids

                terminate_process_tree(process)
                if not wait_for_processes_to_exit(process_ids, 15.0):
                    force_kill_process_tree(process.pid)
                if not wait_for_processes_to_exit(process_ids, 2.0):
                    raise AssertionError(
                        f"Packaged desktop leaked processes: {leaked_processes(process_ids)}"
                    )
                assert_diagnostics(diagnostics_root)
                if not any(
                    event.get("data", {}).get("type") == "shutdown-stopped"
                    for event in read_diagnostics(diagnostics_root)
                ):
                    raise AssertionError(
                        "Packaged desktop did not complete graceful shutdown: "
                        f"{read_diagnostics(diagnostics_root)}"
                    )

            finally:
                if process is not None and process.poll() is None:
                    force_kill_process_tree(process.pid)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        pass
                if tracked_process_ids:
                    wait_for_processes_to_exit(tracked_process_ids, 15)
                for thread in threads:
                    thread.join(timeout=1)
                process = None
                threads = []

            process, stdout, stderr, threads = start_application()
            try:
                wait_for_health(base_url, arguments.timeout, (stdout, stderr))
                process_ids = descendants(process.pid)
                tracked_process_ids = process_ids
                drive_agent_team_workspace(
                    cdp_port,
                    team_id,
                    "packaged desktop persisted user flow",
                    configure=False,
                    create=False,
                    restart=False,
                    delete=True,
                )
                terminate_process_tree(process)
                if not wait_for_processes_to_exit(process_ids, 15.0):
                    force_kill_process_tree(process.pid)
                if not wait_for_processes_to_exit(process_ids, 2.0):
                    raise AssertionError(
                        f"Packaged desktop leaked processes: {leaked_processes(process_ids)}"
                    )
                assert_diagnostics(diagnostics_root)
                if not any(
                    event.get("data", {}).get("type") == "shutdown-stopped"
                    for event in read_diagnostics(diagnostics_root)
                ):
                    raise AssertionError(
                        "Packaged desktop did not complete graceful shutdown"
                    )
            finally:
                if process is not None and process.poll() is None:
                    force_kill_process_tree(process.pid)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        pass
                if tracked_process_ids:
                    wait_for_processes_to_exit(tracked_process_ids, 15)
                for thread in threads:
                    thread.join(timeout=1)
                process = None
                threads = []

            if is_windows:
                process, stdout, stderr, threads = start_application()
                try:
                    wait_for_health(base_url, arguments.timeout, (stdout, stderr))
                    process_ids = descendants(process.pid)
                    tracked_process_ids = process_ids
                    force_kill_process_tree(process.pid)
                    process.wait(timeout=15)
                    if not wait_for_processes_to_exit(process_ids, 15.0):
                        raise AssertionError(
                            f"Packaged desktop leaked processes after forced cleanup: "
                            f"{leaked_processes(process_ids)}"
                        )
                finally:
                    if process is not None and process.poll() is None:
                        force_kill_process_tree(process.pid)
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            pass
                    if tracked_process_ids:
                        wait_for_processes_to_exit(tracked_process_ids, 15)
                    for thread in threads:
                        thread.join(timeout=1)
                    process = None
                    threads = []
        finally:
            if process is not None and process.poll() is None:
                force_kill_process_tree(process.pid)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass
            if tracked_process_ids:
                wait_for_processes_to_exit(tracked_process_ids, 15)
            for thread in threads:
                thread.join(timeout=1)
            if is_windows and install_dir is not None:
                uninstall_windows_artifact(install_dir, arguments.timeout)
            if xvfb_process is not None:
                terminate_process_tree(xvfb_process)
                xvfb_process.wait(timeout=15)
            remove_tree_with_retry(temporary_root)

    print("Packaged desktop E2E passed")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        token = PROCESS_OUTPUT.get("api_token", "")
        for stream_name in ("stdout", "stderr"):
            output = "".join(PROCESS_OUTPUT[stream_name])
            if token:
                output = output.replace(token, "[redacted]")
            if output:
                print(f"--- {stream_name} ---\n{output}", file=sys.stderr)
        raise
