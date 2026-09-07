"""全局设置：<home>/settings.json，可在 webui 的设置面板里改。

为什么落到环境变量：预制件工具（senza_studio_components 里的
send_email 等）是独立的 pip 包，不该依赖 Studio 的内部结构——它们只读
os.environ。Studio 启动时把 settings.json 注入 os.environ，保存设置时
再注入一次（不用重启后端就生效）。这样：

- 预制件包保持独立可移植（Phase 7 导出的项目也能直接用同一套工具）；
- 直接 export 环境变量的老用法依然有效，而且优先级更高（见
  apply_to_environ 的 override 参数）——CI/脚本里不该被一个 GUI 写的
  文件悄悄覆盖掉显式设置的值。

密钥（SMTP 密码、API key 等）明文存在这个文件里：文件权限设 0600，且
位于 ~/.senza-studio/ 而不是任何 git 仓库里。GET /api/settings 不回传
明文密钥（见 masked_values），避免密钥出现在浏览器 devtools 的网络面板/
前端内存里。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .config import StudioConfig

# 设置面板左侧导航的分区说明（key 对应字段的 group）。加新分区时在这里
# 加一条说明、在 SETTINGS_SCHEMA 里加对应 group 的字段即可，前端不用改。
SETTINGS_SECTIONS: dict[str, str] = {
    "邮件": "供 send_email 预制件使用的 SMTP 配置。",
}

# 前端据此渲染表单；secret=True 的字段用密码框，且不回传明文。
SETTINGS_SCHEMA: list[dict] = [
    {
        "group": "邮件",
        "key": "SENZA_SMTP_HOST",
        "label": "SMTP 服务器",
        "placeholder": "smtp.gmail.com",
        "secret": False,
    },
    {
        "group": "邮件",
        "key": "SENZA_SMTP_PORT",
        "label": "端口",
        "placeholder": "587",
        "secret": False,
    },
    {
        "group": "邮件",
        "key": "SENZA_SMTP_USER",
        "label": "用户名",
        "placeholder": "you@example.com",
        "secret": False,
    },
    {
        "group": "邮件",
        "key": "SENZA_SMTP_PASSWORD",
        "label": "密码",
        "placeholder": "Gmail 等需要用应用专用密码",
        "secret": True,
    },
    {
        "group": "邮件",
        "key": "SENZA_SMTP_FROM",
        "label": "发件人地址（可选）",
        "placeholder": "默认与用户名相同",
        "secret": False,
    },
    {
        "group": "邮件",
        "key": "SENZA_SMTP_USE_TLS",
        "label": "使用 STARTTLS",
        "placeholder": "1 开启（默认），0 关闭",
        "secret": False,
    },
]

_KEYS = [item["key"] for item in SETTINGS_SCHEMA]
_SECRET_KEYS = {item["key"] for item in SETTINGS_SCHEMA if item["secret"]}

# GET 时代替明文密钥回传的哨兵；PUT 收到这个值表示"没改，保留原值"。
SECRET_PLACEHOLDER = "__SENZA_UNCHANGED__"


def settings_path(config: StudioConfig) -> Path:
    return Path(config.home_dir) / "settings.json"


def load_settings(config: StudioConfig) -> dict[str, str]:
    """读 settings.json。文件不存在/损坏都返回空 dict，不抛异常——设置是
    锦上添花，不该让整个后端起不来。"""
    path = settings_path(config)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: str(v) for k, v in data.items() if k in _KEYS and v is not None}


def save_settings(config: StudioConfig, values: dict[str, str]) -> dict[str, str]:
    """合并进已有设置并写盘（0600）。值为 SECRET_PLACEHOLDER 表示保留原
    值（前端没有明文，不该因为用户没重新输入密码就把它清空）；空字符串
    表示真的要清空这一项。"""
    current = load_settings(config)
    for key, value in values.items():
        if key not in _KEYS:
            continue  # 忽略未知 key，别让任意内容写进这个文件
        if value == SECRET_PLACEHOLDER:
            continue
        current[key] = str(value)

    path = settings_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    # 含密钥，只给当前用户读写
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return current


def masked_values(values: dict[str, str]) -> dict[str, str]:
    """密钥字段替换成哨兵——前端只需要知道"设过了"，不需要明文。"""
    return {
        key: (SECRET_PLACEHOLDER if key in _SECRET_KEYS and value else value)
        for key, value in values.items()
    }


def apply_to_environ(values: dict[str, str], override: bool = False) -> None:
    """把设置注入 os.environ，供预制件工具读取。

    override=False（启动时）：已经显式 export 过的环境变量优先，不被
    settings.json 覆盖——CI/脚本里的显式配置不该被一个 GUI 写的文件悄悄
    改掉。override=True（用户刚在设置面板点了保存）：以刚保存的为准，
    否则用户改了没反应，还得重启后端才生效。
    """
    for key, value in values.items():
        if not value:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
