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
    os.killpg(process.pid, signal.SIGTERM)
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

def main():
    arguments = parse_arguments()
    is_windows = sys.platform == "win32"
    if sys.platform not in ("linux", "win32"):
        raise SystemExit("This packaged desktop E2E supports Linux and Windows")
    if not arguments.artifact.is_file() or not os.access(arguments.artifact, os.X_OK):
        raise SystemExit(f"Artifact is not executable: {arguments.artifact}")

    xvfb_run = shutil.which("xvfb-run") if sys.platform == "linux" else None
    if sys.platform == "linux" and not arguments.no_xvfb and not xvfb_run:
        raise SystemExit("xvfb-run is required for headless packaged desktop E2E")

    port = reserve_port()
    api_token = secrets.token_urlsafe(32)
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
            command = [str(app_executable)]
            if is_windows:
                command.append(f"--user-data-dir={user_data}")
            if not is_windows:
                command.extend(["--appimage-extract-and-run", "--no-sandbox"])
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
            remove_tree_with_retry(temporary_root)

    print("Packaged desktop E2E passed")


if __name__ == "__main__":
    main()
