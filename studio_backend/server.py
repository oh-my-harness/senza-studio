"""Senza Studio 后端启动入口。"""
import uvicorn
import os
from .app import create_app

def backend_port():
    configured_port = os.environ.get("SENZA_STUDIO_PORT", "")
    if not configured_port:
        return 7878
    if not configured_port.isdecimal():
        raise ValueError("SENZA_STUDIO_PORT must be an integer")
    port = int(configured_port)
    if not 1 <= port <= 65535:
        raise ValueError("SENZA_STUDIO_PORT must be between 1 and 65535")
    return port


def main():
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=backend_port())


if __name__ == "__main__":
    main()
