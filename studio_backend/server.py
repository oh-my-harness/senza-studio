"""Senza Studio 后端启动入口。"""
import uvicorn
from .app import create_app


def main():
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=7878)


if __name__ == "__main__":
    main()
