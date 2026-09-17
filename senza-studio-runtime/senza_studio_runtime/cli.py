"""`senza-studio-runtime` 命令行入口（Phase 7 切片三）。

导出项目的 README 里写的就是这一条：

    senza-studio-runtime serve pipeline.yaml --port 8000
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="senza-studio-runtime",
        description="运行从 Senza Studio 导出的 Agent 项目",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve_cmd = sub.add_parser("serve", help="启动流程的 web 界面")
    serve_cmd.add_argument(
        "pipeline",
        nargs="?",
        default="pipeline.yaml",
        help="pipeline.yaml 路径（默认当前目录下的 pipeline.yaml）",
    )
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)

    if args.command == "serve":
        pipeline = Path(args.pipeline)
        if not pipeline.is_file():
            # 最常见的错法就是在错的目录里敲命令，直接说清楚，别抛 traceback
            print(
                f"找不到 {pipeline}。请在导出目录里运行，或显式给出路径。",
                file=sys.stderr,
            )
            return 2
        from .serve import serve

        serve(pipeline, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
