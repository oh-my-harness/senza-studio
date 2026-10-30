#!/usr/bin/env python3
"""Apply explicit, persistent startup exclusions without probing or changing proxies.

语义沿用旧 Runtime 仓库的启动包装器;拆分后的 agent-team 仓库不再自带
该包装器,因此本脚本只服务 Studio,与 Runtime 的配置互不同步:
- Studio(本脚本)读取 $SENZA_STUDIO_HOME/provider-network.json(默认 ~/.senza-studio);
- Runtime 由独立仓库启动,直接继承启动 shell 的代理环境,不读取此文件。
两边如需不同策略,分别在各自的启动环境里配置。只在子进程环境追加大小写 NO_PROXY 条目。
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys


class PolicyError(ValueError):
    pass


def exclusions(env):
    root = Path(env.get("SENZA_STUDIO_HOME", str(Path.home() / ".senza-studio")))
    path = root / "provider-network.json"
    if "STUDIO_NO_PROXY_APPEND" in env:
        values = [x.strip() for x in env["STUDIO_NO_PROXY_APPEND"].split(",") if x.strip()]
        source = "environment override"
    elif path.exists():
        try:
            with path.open() as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise PolicyError("network policy exceeds size limit")
            policy = json.loads(raw)
        except (OSError, ValueError):
            raise PolicyError("cannot read valid provider-network.json") from None
        if not isinstance(policy, dict) or set(policy) != {"version", "no_proxy"}:
            raise PolicyError("network policy requires only version and no_proxy")
        if type(policy["version"]) is not int or policy["version"] != 1:
            raise PolicyError("unsupported network policy version")
        values = policy["no_proxy"]
        source = "persistent file"
    else:
        return [], "inherited environment"
    if not isinstance(values, list) or len(values) > 128:
        raise PolicyError("no_proxy must be a bounded list of hostnames")
    result = []
    for value in values:
        # Plain hostnames only: no URLs, credentials, ports, wildcards or executable text.
        if not isinstance(value, str) or len(value) > 253:
            raise PolicyError("invalid no_proxy hostname")
        host = value.lower().rstrip(".")
        if not host or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part)
                           for part in host.split(".")):
            raise PolicyError("no_proxy entries must be plain hostnames")
        if host not in result:
            result.append(host)
    return result, source


def child_environment(env):
    hosts, source = exclusions(env)
    child = dict(env)
    if hosts:
        for name, other in (("NO_PROXY", "no_proxy"), ("no_proxy", "NO_PROXY")):
            original = env.get(name, env.get(other, ""))
            entries = [x.strip() for x in original.split(",") if x.strip()]
            known = {x.lower().rstrip(".") for x in entries}
            entries.extend(x for x in hosts if x not in known)
            child[name] = ",".join(entries)
    return child, source, len(hosts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="validate policy only; no network or startup")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        child, source, count = child_environment(os.environ)
    except PolicyError as error:
        print(f"provider network policy: {error}; process not started", file=sys.stderr)
        return 2
    if args.check:
        print(f"provider network policy: {source}; {count} explicit exclusions; startup-only")
        return 0
    command = args.command
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        parser.error("a command after -- is required")
    try:
        os.execvpe(command[0], command, child)
    except OSError:
        print("provider network policy: cannot start requested command", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
