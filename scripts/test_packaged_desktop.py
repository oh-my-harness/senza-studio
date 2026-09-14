import argparse
import json
import os
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


def request(url, api_token=None):
    headers = {}
    if api_token:
        headers["Cookie"] = f"senza_studio_api={api_token}"
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


def descendants(process_id):
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


def process_command(process_id):
    try:
        return Path(f"/proc/{process_id}/cmdline").read_bytes().replace(
            b"\0", b" "
        ).decode("utf-8", errors="replace")
    except OSError:
        return ""


def process_environment(process_id):
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
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=timeout)


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


def main():
    arguments = parse_arguments()
    if sys.platform != "linux":
        raise SystemExit("This packaged desktop E2E currently supports Linux")
    if not arguments.artifact.is_file() or not os.access(arguments.artifact, os.X_OK):
        raise SystemExit(f"Artifact is not executable: {arguments.artifact}")

    xvfb_run = shutil.which("xvfb-run")
    if not arguments.no_xvfb and not xvfb_run:
        raise SystemExit("xvfb-run is required for headless packaged desktop E2E")

    port = reserve_port()
    api_token = secrets.token_urlsafe(32)
    base_url = f"http://127.0.0.1:{port}"
    with tempfile.TemporaryDirectory(prefix="senza-studio-e2e-") as temporary_directory:
        temporary_root = Path(temporary_directory)
        home = temporary_root / "home"
        config_home = temporary_root / "config"
        cache_home = temporary_root / "cache"
        python_user_base = temporary_root / "python-user"
        python_user_site = (
            python_user_base / "lib" / "python3.12" / "site-packages"
        )
        home.mkdir()
        config_home.mkdir()
        cache_home.mkdir()
        python_user_site.mkdir(parents=True)
        user_site_marker = temporary_root / "user-site-loaded"
        (python_user_site / "sitecustomize.py").write_text(
            f'from pathlib import Path\nPath({str(user_site_marker)!r}).touch()\n',
            encoding="utf-8",
        )
        environment = {
            **os.environ,
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(config_home),
            "XDG_CACHE_HOME": str(cache_home),
            "PYTHONUSERBASE": str(python_user_base),
            "SENZA_STUDIO_API_TOKEN": api_token,
            "SENZA_STUDIO_PORT": str(port),
            "ELECTRON_DISABLE_GPU": "1",
        }
        command = [
            str(arguments.artifact),
            "--appimage-extract-and-run",
            "--no-sandbox",
        ]
        if xvfb_run and not arguments.no_xvfb:
            command = [xvfb_run, "-a", *command]

        stdout = []
        stderr = []
        process = subprocess.Popen(
            command,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        threads = [
            threading.Thread(target=drain, args=(process.stdout, stdout), daemon=True),
            threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True),
        ]
        for thread in threads:
            thread.start()

        try:
            wait_for_health(base_url, arguments.timeout, (stdout, stderr))
            if user_site_marker.exists():
                raise AssertionError("Backend loaded packages from user site")
            unauthenticated_status, _ = request(f"{base_url}/")
            if unauthenticated_status not in (401, 403):
                raise AssertionError(
                    f"Static UI was not protected: HTTP {unauthenticated_status}"
                )
            authenticated_status, body = request(f"{base_url}/", api_token)
            if authenticated_status != 200 or b"<title>Senza Studio</title>" not in body:
                raise AssertionError("Authenticated static UI did not load")

            process_ids = descendants(process.pid)
            agent_processes = [
                process_id
                for process_id in process_ids
                if "agent-studio" in process_command(process_id)
            ]
            backend_processes = [
                process_id
                for process_id in process_ids
                if "studio_backend.server" in process_command(process_id)
            ]
            if not agent_processes or not backend_processes:
                raise AssertionError("Agent Team or backend process was not running")
            for process_id in agent_processes:
                environment_data = process_environment(process_id)
                if (
                    "SENZA_STUDIO_API_TOKEN" in environment_data
                    or api_token.encode() in environment_data.values()
                ):
                    raise AssertionError("Agent Team runtime received the Studio API token")
            if not any(
                api_token.encode() in process_environment(process_id).values()
                for process_id in backend_processes
            ):
                raise AssertionError("Backend did not receive the Studio API token")

            wait_for_startup_diagnostics(config_home, 15.0)
            terminate_process_tree(process)
            if not wait_for_processes_to_exit(process_ids, 15.0):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if not wait_for_processes_to_exit(process_ids, 2.0):
                leaked = [
                    {
                        "pid": process_id,
                        "command": process_command(process_id),
                    }
                    for process_id in process_ids
                    if process_alive(process_id)
                ]
                raise AssertionError(f"Packaged desktop leaked processes: {leaked}")
            assert_diagnostics(config_home)
        finally:
            terminate_process_tree(process)
            for thread in threads:
                thread.join(timeout=1)

    print("Packaged desktop E2E passed")


if __name__ == "__main__":
    main()
