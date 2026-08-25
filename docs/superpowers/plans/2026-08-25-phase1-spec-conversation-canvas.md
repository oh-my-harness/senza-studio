# Phase 1: Spec 构建 + 对话 + 画布 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用户能和元 agent 对话构建 spec，画布实时显示 DAG，项目可持久化。

**Architecture:** Python 后端（FastAPI + Senza SDK）管理 spec 内存 dict + 元 agent AgentHarness + Session 持久化。Electron 前端（React + ReactFlow）提供对话面板 + 画布编辑态 + Inspector。通过 WebSocket 推送元 agent streaming 事件。

**Tech Stack:** Python 3.12+, Senza SDK, FastAPI, uvicorn, React 18, TypeScript, Vite, Tailwind, ReactFlow, Electron, Zustand

**Spec:** `docs/senza-studio-design-v2.md` §3 (数据模型), §4 (元 Agent 层), §9 (前端架构)

## Global Constraints

- Python 后端在 `studio_backend/` 目录
- 前端在 `studio_frontend/` 目录
- Python 3.12+, 依赖管理用 `pyproject.toml`
- Senza SDK 通过本地 `pip install -e ../Senza` 安装（开发期），生产用 `pip install senza-sdk`
- 前端用 Vite + React 18 + TypeScript
- 测试：后端用 pytest，前端用 vitest
- 遵循 senza-agent 的最佳实践：try/except 条件装配、工具函数与注册分离
- `~/.senza-studio/` 是 Studio 数据根目录
- 项目目录结构遵循 design-v2.md §3
- 元 agent 不直接写 YAML，通过工具 API 增量构建 spec
- 元 agent 是 AgentHarness，与 Play 引擎的 Harness 隔离（各自独立工具集）
- system prompt 动态组装：固定段（角色/规则/spec 构建规范）+ 动态段（当前 spec 摘要、预制件清单、文档列表）

---

## File Structure

```
senza-studio/
├── pyproject.toml                        # Python 依赖
├── studio_backend/
│   ├── __init__.py
│   ├── app.py                            # FastAPI app 工厂 + REST 端点 + WebSocket
│   ├── server.py                         # uvicorn 启动入口
│   ├── config.py                         # StudioConfig: model, api_key, home_dir
│   ├── project.py                        # 项目管理: create/open/list, meta.json, pipeline.yaml
│   ├── spec.py                           # Spec 内存 dict + CRUD + validate + YAML 序列化
│   ├── agent.py                          # 元 agent Harness 组装 (参考 senza-agent create_agent)
│   ├── system_prompt.py                  # 动态 system prompt 组装
│   ├── session.py                        # 元 agent session 生命周期管理
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── spec_tools.py                 # add_step/add_edge/remove_step/... 回调函数
│   │   ├── doc_tools.py                  # write_document 回调函数
│   │   ├── prefab_tools.py               # list_prefabs/search_prefabs/recommend_prefabs (返回空)
│   │   └── registry.py                   # get_studio_tools(spec, project) -> [Tool]
│   └── ws.py                             # WebSocket 连接管理 + 事件转发
├── studio_frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── postcss.config.js
│   ├── index.html
│   ├── electron/
│   │   └── main.cjs                      # Electron 主进程: spawn Python 后端 + BrowserWindow
│   └── src/
│       ├── main.tsx                      # React 入口
│       ├── App.tsx                       # 顶层布局 + 状态切换
│       ├── store.ts                      # Zustand store
│       ├── api.ts                        # HTTP + WebSocket 客户端
│       ├── types.ts                      # TypeScript 类型定义
│       ├── components/
│       │   ├── ChatPanel.tsx             # 对话面板: 消息列表 + streaming + 输入框
│       │   ├── Canvas.tsx                # ReactFlow 画布: spec → DAG 节点/边
│       │   ├── Inspector.tsx             # 编辑态属性面板
│       │   └── StatusBar.tsx             # 底栏: 项目状态
│       └── index.css                     # Tailwind 指令
└── tests/
    ├── test_spec.py                      # Spec CRUD + validate
    ├── test_project.py                   # 项目管理
    ├── test_tools.py                     # 元 agent 工具回调
    ├── test_system_prompt.py             # 动态 system prompt
    └── test_agent.py                     # 元 agent Harness 组装
```

---

### Task 1: 项目脚手架 + 依赖配置

**Files:**
- Create: `pyproject.toml`
- Create: `studio_backend/__init__.py`
- Create: `studio_backend/server.py`
- Create: `studio_backend/app.py`
- Create: `studio_frontend/package.json`
- Create: `studio_frontend/vite.config.ts`
- Create: `studio_frontend/tsconfig.json`
- Create: `studio_frontend/tailwind.config.js`
- Create: `studio_frontend/postcss.config.js`
- Create: `studio_frontend/index.html`
- Create: `studio_frontend/src/main.tsx`
- Create: `studio_frontend/src/App.tsx`
- Create: `studio_frontend/src/index.css`

**Interfaces:**
- Produces: `studio_backend/server.py` 提供 `main()` 入口，启动 uvicorn 在 `localhost:7878`
- Produces: `studio_backend/app.py` 提供 `create_app()` → FastAPI 实例
- Produces: `studio_frontend/` 可 `npm run dev` 启动 Vite dev server

- [ ] **Step 1: 创建 Python pyproject.toml**

```toml
[project]
name = "senza-studio"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "pyyaml",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "httpx"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

> **Note:** `senza-sdk` 不写在 dependencies 里——开发期用 `pip install -e ../Senza` 安装。写进去会导致 pip 从 PyPI 拉取可能不存在的包名。

- [ ] **Step 2: 创建 Python 后端入口和最小 app**

```python
# studio_backend/__init__.py
```

```python
# studio_backend/server.py
"""Senza Studio 后端启动入口。"""
import uvicorn
from .app import create_app


def main():
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=7878)


if __name__ == "__main__":
    main()
```

```python
# studio_backend/app.py
"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app() -> FastAPI:
    app = FastAPI(title="Senza Studio")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    return app
```

- [ ] **Step 3: 创建前端 package.json**

```json
{
  "name": "senza-studio-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc && vite build",
    "test": "vitest"
  },
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "reactflow": "^11.11.0",
    "zustand": "^4.5.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.5.0",
    "vite": "^5.4.0",
    "vitest": "^2.0.0"
  }
}
```

- [ ] **Step 4: 创建 Vite + TS + Tailwind 配置**

```typescript
// studio_frontend/vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:7878",
      "/ws": { target: "ws://127.0.0.1:7878", ws: true },
    },
  },
});
```

```json
// studio_frontend/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "outDir": "dist"
  },
  "include": ["src"]
}
```

```javascript
// studio_frontend/tailwind.config.js
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};
```

```javascript
// studio_frontend/postcss.config.js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

- [ ] **Step 5: 创建前端入口文件**

```html
<!-- studio_frontend/index.html -->
<!DOCTYPE html>
<html lang="zh">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Senza Studio</title>
  </head>
  <body class="h-screen overflow-hidden">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

```css
/* studio_frontend/src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

```typescript
// studio_frontend/src/main.tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "reactflow/dist/style.css";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

```typescript
// studio_frontend/src/App.tsx
export default function App() {
  return (
    <div className="h-full w-full flex items-center justify-center text-gray-500">
      <p>Senza Studio — loading…</p>
    </div>
  );
}
```

- [ ] **Step 6: 验证后端启动**

Run: `cd /Users/hhl/Documents/projs/oh-my-harness/senza-studio && python -c "from studio_backend.app import create_app; print(create_app())"`
Expected: 无报错，打印 FastAPI 对象

- [ ] **Step 7: 验证前端启动**

Run: `cd studio_frontend && npm install && npm run dev`
Expected: Vite dev server 在 localhost:5173 启动，浏览器显示 "Senza Studio — loading…"

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml studio_backend/ studio_frontend/
git commit -m "scaffold: Python 后端 + React 前端脚手架"
```

---

### Task 2: Spec 数据模型 + CRUD

**Files:**
- Create: `studio_backend/spec.py`
- Create: `tests/test_spec.py`

**Interfaces:**
- Produces: `Spec` 类，方法: `add_step(name, description, type, prompt_template=None, **extra)`, `add_edge(from_step, to_step, condition)`, `remove_step(name)`, `remove_edge(from_step, to_step, condition)`, `set_step_property(step_name, key, value)`, `get_current_spec() -> dict`, `validate()`, `to_yaml() -> str`, `Spec.from_yaml(yaml_str) -> Spec`
- Produces: `SpecError` 异常类
- Produces: spec dict 结构: `{"stages": [{"name": str, "type": str, ...}]}`，边以 `next_on_<condition>` 字段存储在 step 上

- [ ] **Step 1: 写 Spec 的失败测试**

```python
# tests/test_spec.py
"""Spec 数据模型 CRUD 测试。"""
import pytest
from studio_backend.spec import Spec, SpecError


def test_empty_spec_validate_fails():
    """空 spec（无 stages）validate 应失败。"""
    spec = Spec()
    with pytest.raises(SpecError, match="no stages"):
        spec.validate()


def test_add_step():
    spec = Spec()
    spec.add_step("classify", "分类步骤", "agent", prompt_template="分类：{input}")
    data = spec.get_current_spec()
    assert len(data["stages"]) == 1
    assert data["stages"][0]["name"] == "classify"
    assert data["stages"][0]["type"] == "agent"


def test_add_step_duplicate_name_fails():
    spec = Spec()
    spec.add_step("classify", "分类", "agent")
    with pytest.raises(SpecError, match="already exists"):
        spec.add_step("classify", "重复", "agent")


def test_add_step_invalid_type_fails():
    spec = Spec()
    with pytest.raises(SpecError, match="invalid step type"):
        spec.add_step("x", "x", "invalid_type")


def test_add_edge():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    spec.add_step("b", "step b", "agent")
    spec.add_edge("a", "b", "success")
    data = spec.get_current_spec()
    assert data["stages"][0].get("next_on_success") == "b"


def test_add_edge_unknown_from_fails():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    with pytest.raises(SpecError, match="not found"):
        spec.add_edge("unknown", "a", "success")


def test_add_edge_unknown_to_fails():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    with pytest.raises(SpecError, match="not found"):
        spec.add_edge("a", "ghost", "success")


def test_remove_step():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    spec.add_step("b", "step b", "agent")
    spec.add_edge("a", "b", "success")
    spec.remove_step("a")
    data = spec.get_current_spec()
    assert len(data["stages"]) == 1
    assert data["stages"][0]["name"] == "b"
    # edges to removed step should be cleaned
    assert "next_on_success" not in data["stages"][0]


def test_remove_step_not_found_fails():
    spec = Spec()
    with pytest.raises(SpecError, match="not found"):
        spec.remove_step("ghost")


def test_set_step_property():
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    spec.set_step_property("a", "output_key", "result_a")
    data = spec.get_current_spec()
    assert data["stages"][0]["output_key"] == "result_a"


def test_set_step_property_step_not_found_fails():
    spec = Spec()
    with pytest.raises(SpecError, match="not found"):
        spec.set_step_property("ghost", "key", "val")


def test_validate_no_terminal_fails():
    """有 step 但没有 terminal step → validate 失败。"""
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    with pytest.raises(SpecError, match="no terminal"):
        spec.validate()


def test_validate_passes_with_terminal():
    """有 step + terminal → validate 通过。"""
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    spec.add_step("b", "step b", "terminal")
    spec.add_edge("a", "b", "success")
    spec.validate()  # should not raise


def test_validate_dangling_edge():
    """edge 指向不存在的 step → validate 失败。"""
    spec = Spec()
    spec.add_step("a", "step a", "agent", next_on_success="ghost")
    spec.add_step("b", "step b", "terminal")
    with pytest.raises(SpecError, match="ghost"):
        spec.validate()


def test_to_yaml_and_from_yaml():
    spec = Spec()
    spec.add_step("a", "step a", "agent", prompt_template="hello")
    spec.add_step("b", "step b", "terminal", message="done")
    spec.add_edge("a", "b", "success")
    yaml_str = spec.to_yaml()
    spec2 = Spec.from_yaml(yaml_str)
    data = spec2.get_current_spec()
    assert len(data["stages"]) == 2
    assert data["stages"][0]["name"] == "a"
    assert data["stages"][1]["name"] == "b"


def test_get_current_spec_returns_deep_copy():
    """get_current_spec 返回深拷贝，修改返回值不影响原 spec。"""
    spec = Spec()
    spec.add_step("a", "step a", "agent")
    data = spec.get_current_spec()
    data["stages"][0]["name"] = "modified"
    data2 = spec.get_current_spec()
    assert data2["stages"][0]["name"] == "a"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_spec.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'studio_backend.spec'`

- [ ] **Step 3: 实现 Spec 类**

```python
# studio_backend/spec.py
"""Spec 内存 dict + CRUD + 校验 + YAML 序列化。

Spec 是 pipeline.yaml 的内存表示，元 agent 通过工具 API 增量构建。
YAML 只是序列化输出，元 agent 不直接写 YAML。
"""
from __future__ import annotations

import copy
from typing import Any

import yaml


class SpecError(Exception):
    """Spec 操作错误。"""


_VALID_TYPES = {"agent", "checker", "tool", "terminal"}
_EDGE_PREFIX = "next_on_"


class Spec:
    """Pipeline spec 的内存表示。

    内部格式与 pipeline.yaml 一致：
        {"stages": [{"name": str, "type": str, ...}]}

    边以 next_on_<condition> 字段存储在 step 上。
    """

    def __init__(self, data: dict | None = None) -> None:
        self._data: dict = copy.deepcopy(data) if data else {"stages": []}

    # ── 查询 ──────────────────────────────────────────────

    def get_current_spec(self) -> dict:
        """返回 spec 的深拷贝。"""
        return copy.deepcopy(self._data)

    def _find_step(self, name: str) -> dict | None:
        for step in self._data.get("stages", []):
            if step.get("name") == name:
                return step
        return None

    def _step_names(self) -> set[str]:
        return {s.get("name", "") for s in self._data.get("stages", [])}

    # ── CRUD ──────────────────────────────────────────────

    def add_step(
        self,
        name: str,
        description: str,
        type: str,
        prompt_template: str | None = None,
        **extra: Any,
    ) -> None:
        if not name or not name.strip():
            raise SpecError("step name cannot be empty")
        if type not in _VALID_TYPES:
            raise SpecError(f"invalid step type: {type}")
        if self._find_step(name):
            raise SpecError(f"step '{name}' already exists")

        step: dict[str, Any] = {"name": name, "type": type}
        if prompt_template is not None:
            step["prompt_template"] = prompt_template
        if type == "terminal":
            step.setdefault("message", description)
        step.update(extra)

        self._data.setdefault("stages", []).append(step)

    def remove_step(self, name: str) -> None:
        step = self._find_step(name)
        if step is None:
            raise SpecError(f"step '{name}' not found")
        self._data["stages"] = [
            s for s in self._data["stages"] if s.get("name") != name
        ]
        # 清理指向该 step 的边
        for s in self._data["stages"]:
            for key in list(s.keys()):
                if key.startswith(_EDGE_PREFIX) and s[key] == name:
                    del s[key]

    def add_edge(self, from_step: str, to_step: str, condition: str) -> None:
        src = self._find_step(from_step)
        if src is None:
            raise SpecError(f"step '{from_step}' not found")
        if to_step not in self._step_names():
            raise SpecError(f"step '{to_step}' not found")
        key = f"{_EDGE_PREFIX}{condition}"
        src[key] = to_step

    def remove_edge(self, from_step: str, to_step: str, condition: str) -> None:
        src = self._find_step(from_step)
        if src is None:
            raise SpecError(f"step '{from_step}' not found")
        key = f"{_EDGE_PREFIX}{condition}"
        if key in src and src[key] == to_step:
            del src[key]
        else:
            raise SpecError(
                f"edge {from_step} --{condition}--> {to_step} not found"
            )

    def set_step_property(self, step_name: str, key: str, value: Any) -> None:
        step = self._find_step(step_name)
        if step is None:
            raise SpecError(f"step '{step_name}' not found")
        step[key] = value

    # ── 校验 ──────────────────────────────────────────────

    def validate(self) -> None:
        """校验 spec 完整性。失败时 raise SpecError。"""
        stages = self._data.get("stages", [])
        if not stages:
            raise SpecError("spec has no stages")

        # 校验重名
        names = self._step_names()
        if len(names) != len(stages):
            seen: set[str] = set()
            for s in stages:
                n = s.get("name", "")
                if n in seen:
                    raise SpecError(f"duplicate step name: {n}")
                seen.add(n)

        # 校验边指向
        for s in stages:
            for key, val in s.items():
                if key.startswith(_EDGE_PREFIX) and isinstance(val, str):
                    if val not in names:
                        raise SpecError(
                            f"edge from '{s['name']}' points to unknown step '{val}'"
                        )

        # 至少有一个 terminal step
        has_terminal = any(s.get("type") == "terminal" for s in stages)
        if not has_terminal:
            raise SpecError("spec has no terminal step")

    # ── 序列化 ────────────────────────────────────────────

    def to_yaml(self) -> str:
        return yaml.dump(self._data, allow_unicode=True, sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> Spec:
        data = yaml.safe_load(yaml_str)
        return cls(data)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_spec.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add studio_backend/spec.py tests/test_spec.py
git commit -m "feat: Spec 数据模型 + CRUD + 校验"
```

---

### Task 3: 项目管理 + 配置

**Files:**
- Create: `studio_backend/config.py`
- Create: `studio_backend/project.py`
- Create: `tests/test_project.py`

**Interfaces:**
- Consumes: `Spec` from `studio_backend.spec`
- Produces: `StudioConfig` dataclass — fields: `home_dir: str`, `model: str`, `api_key: str`, `api_base: str`; classmethod `from_env()`; property `projects_dir -> Path`
- Produces: `Project` class — classmethods `create(config, name) -> Project`, `open(config, project_id) -> Project`, `list_all(config) -> list[dict]`; instance methods `save_spec(spec)`, `load_spec() -> Spec`, `create_session() -> str`, `set_active_session(session_id)`; property `sessions_dir -> Path`; attribute `meta: dict`, `path: Path`

- [ ] **Step 1: 写项目管理的失败测试**

```python
# tests/test_project.py
"""项目管理测试。"""
import pytest
from studio_backend.project import Project
from studio_backend.config import StudioConfig


@pytest.fixture
def tmp_config(tmp_path):
    return StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="test-key",
        api_base="",
    )


def test_create_project(tmp_config):
    proj = Project.create(tmp_config, "测试项目")
    assert proj.meta["name"] == "测试项目"
    assert proj.meta["status"] == "editing"
    assert proj.path.is_dir()
    assert (proj.path / "pipeline.yaml").exists()
    assert (proj.path / "tools" / "generated").is_dir()
    assert (proj.path / "tools" / "custom").is_dir()
    assert (proj.path / "plugins").is_dir()
    assert (proj.path / ".studio" / "sessions").is_dir()


def test_open_project(tmp_config):
    proj = Project.create(tmp_config, "测试")
    proj2 = Project.open(tmp_config, proj.meta["id"])
    assert proj2.meta["name"] == "测试"
    assert proj2.meta["id"] == proj.meta["id"]


def test_open_project_not_found(tmp_config):
    with pytest.raises(FileNotFoundError):
        Project.open(tmp_config, "nonexistent-id")


def test_list_projects(tmp_config):
    Project.create(tmp_config, "项目A")
    Project.create(tmp_config, "项目B")
    projects = Project.list_all(tmp_config)
    assert len(projects) == 2


def test_list_projects_empty(tmp_config):
    projects = Project.list_all(tmp_config)
    assert projects == []


def test_save_and_load_spec(tmp_config):
    from studio_backend.spec import Spec
    proj = Project.create(tmp_config, "测试")
    spec = Spec()
    spec.add_step("a", "step a", "agent", prompt_template="hello")
    spec.add_step("b", "step b", "terminal", message="done")
    spec.add_edge("a", "b", "success")
    proj.save_spec(spec)
    # 重新打开
    proj2 = Project.open(tmp_config, proj.meta["id"])
    spec2 = proj2.load_spec()
    data = spec2.get_current_spec()
    assert len(data["stages"]) == 2


def test_create_session(tmp_config):
    proj = Project.create(tmp_config, "测试")
    sid = proj.create_session()
    assert sid in proj.meta["sessions"]
    assert proj.meta["active_session"] == sid


def test_switch_session(tmp_config):
    proj = Project.create(tmp_config, "测试")
    sid1 = proj.create_session()
    sid2 = proj.create_session()
    proj.set_active_session(sid1)
    assert proj.meta["active_session"] == sid1


def test_set_active_session_invalid(tmp_config):
    proj = Project.create(tmp_config, "测试")
    with pytest.raises(ValueError):
        proj.set_active_session("invalid-sid")


def test_save_updates_timestamp(tmp_config):
    proj = Project.create(tmp_config, "测试")
    old_ts = proj.meta["updated_at"]
    import time
    time.sleep(0.01)
    from studio_backend.spec import Spec
    spec = Spec()
    spec.add_step("a", "a", "terminal", message="done")
    proj.save_spec(spec)
    proj2 = Project.open(tmp_config, proj.meta["id"])
    assert proj2.meta["updated_at"] >= old_ts


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("SENZA_STUDIO_HOME", "/tmp/test-studio")
    monkeypatch.setenv("SENZA_STUDIO_MODEL", "gpt-4o")
    monkeypatch.setenv("SENZA_STUDIO_API_KEY", "sk-test")
    monkeypatch.setenv("SENZA_STUDIO_API_BASE", "https://api.test.com")
    config = StudioConfig.from_env()
    assert config.home_dir == "/tmp/test-studio"
    assert config.model == "gpt-4o"
    assert config.api_key == "sk-test"
    assert config.api_base == "https://api.test.com"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_project.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 StudioConfig**

```python
# studio_backend/config.py
"""Studio 全局配置。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StudioConfig:
    """Studio 全局配置。"""
    home_dir: str = ""
    model: str = "deepseek-chat"
    api_key: str = ""
    api_base: str = ""

    @classmethod
    def from_env(cls) -> StudioConfig:
        home = os.environ.get(
            "SENZA_STUDIO_HOME",
            str(Path.home() / ".senza-studio"),
        )
        return cls(
            home_dir=home,
            model=os.environ.get("SENZA_STUDIO_MODEL", "deepseek-chat"),
            api_key=os.environ.get(
                "SENZA_STUDIO_API_KEY", os.environ.get("OPENAI_API_KEY", "")
            ),
            api_base=os.environ.get(
                "SENZA_STUDIO_API_BASE",
                os.environ.get("OPENAI_API_BASE", ""),
            ),
        )

    @property
    def projects_dir(self) -> Path:
        return Path(self.home_dir) / "projects"
```

- [ ] **Step 4: 实现 Project**

```python
# studio_backend/project.py
"""项目管理：创建/打开/列出项目，meta.json 维护。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .config import StudioConfig
from .spec import Spec


def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _gen_id(prefix: str = "proj") -> str:
    return f"{prefix}-{int(time.time() * 1000)}"


class Project:
    """单个 Studio 项目。"""

    def __init__(self, config: StudioConfig, meta: dict, path: Path) -> None:
        self.config = config
        self.meta = meta
        self.path = path

    # ── 创建/打开/列出 ────────────────────────────────────

    @classmethod
    def create(cls, config: StudioConfig, name: str) -> Project:
        proj_id = _gen_id("proj")
        path = config.projects_dir / proj_id
        path.mkdir(parents=True, exist_ok=True)

        # 创建目录结构 (design-v2 §3)
        (path / ".studio" / "docs").mkdir(parents=True, exist_ok=True)
        (path / ".studio" / "specs").mkdir(parents=True, exist_ok=True)
        (path / ".studio" / "sessions").mkdir(parents=True, exist_ok=True)
        (path / "tools" / "generated").mkdir(parents=True, exist_ok=True)
        (path / "tools" / "custom").mkdir(parents=True, exist_ok=True)
        (path / "plugins").mkdir(parents=True, exist_ok=True)
        (path / "exports").mkdir(parents=True, exist_ok=True)

        meta = {
            "id": proj_id,
            "name": name,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "status": "editing",
            "model": config.model,
            "active_session": None,
            "sessions": [],
            "last_played_at": None,
            "last_export_dir": None,
        }

        # 初始空 spec
        spec = Spec()
        (path / "pipeline.yaml").write_text(spec.to_yaml(), encoding="utf-8")

        proj = cls(config, meta, path)
        proj._save_meta()
        return proj

    @classmethod
    def open(cls, config: StudioConfig, project_id: str) -> Project:
        path = config.projects_dir / project_id
        meta_path = path / ".studio" / "meta.json"
        if not meta_path.exists():
            raise FileNotFoundError(f"project {project_id} not found")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return cls(config, meta, path)

    @classmethod
    def list_all(cls, config: StudioConfig) -> list[dict]:
        projects_dir = config.projects_dir
        if not projects_dir.exists():
            return []
        result = []
        for p in sorted(projects_dir.iterdir()):
            meta_path = p / ".studio" / "meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                result.append(meta)
        return result

    # ── Spec 持久化 ───────────────────────────────────────

    def save_spec(self, spec: Spec) -> None:
        yaml_path = self.path / "pipeline.yaml"
        yaml_path.write_text(spec.to_yaml(), encoding="utf-8")
        self.meta["updated_at"] = _utc_now()
        self._save_meta()

    def load_spec(self) -> Spec:
        yaml_path = self.path / "pipeline.yaml"
        if not yaml_path.exists():
            return Spec()
        return Spec.from_yaml(yaml_path.read_text(encoding="utf-8"))

    # ── Session 管理 ──────────────────────────────────────

    def create_session(self) -> str:
        sid = _gen_id("sess")
        self.meta.setdefault("sessions", []).append(sid)
        self.meta["active_session"] = sid
        self._save_meta()
        return sid

    def set_active_session(self, session_id: str) -> None:
        if session_id not in self.meta.get("sessions", []):
            raise ValueError(f"session {session_id} not found")
        self.meta["active_session"] = session_id
        self._save_meta()

    @property
    def sessions_dir(self) -> Path:
        return self.path / ".studio" / "sessions"

    # ── 内部 ──────────────────────────────────────────────

    def _save_meta(self) -> None:
        meta_path = self.path / ".studio" / "meta.json"
        meta_path.write_text(
            json.dumps(self.meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_project.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add studio_backend/config.py studio_backend/project.py tests/test_project.py
git commit -m "feat: 项目管理 + Session 管理 + 配置"
```

---

### Task 4: 元 agent 工具集 — spec/doc/prefab 工具回调

**Files:**
- Create: `studio_backend/tools/__init__.py`
- Create: `studio_backend/tools/spec_tools.py`
- Create: `studio_backend/tools/doc_tools.py`
- Create: `studio_backend/tools/prefab_tools.py`
- Create: `tests/test_tools.py`

**Interfaces:**
- Consumes: `Spec` from `studio_backend.spec`, `Project` from `studio_backend.project`
- Produces: `make_spec_tools(spec: Spec) -> list[Tool]` — 返回绑定到 spec 实例的 Senza Tool 列表
- Produces: `make_doc_tools(project: Project) -> list[Tool]` — 返回绑定到 project 的文档工具
- Produces: `make_prefab_tools() -> list[Tool]` — 返回预制件工具（Phase 1 返回空列表占位）
- Each Tool is created via `senza.create_tool(name, description, parameters_schema, callback)` where callback signature is `(args: dict, ctx: Any) -> str`

**Tool list (spec_tools):** `add_step`, `add_edge`, `remove_step`, `remove_edge`, `set_step_property`, `bind_tool`, `set_ui_config`, `get_current_spec`, `validate_spec`

**Tool list (doc_tools):** `write_document`, `list_documents`

**Tool list (prefab_tools):** `list_prefabs`, `search_prefabs`, `recommend_prefabs` (all return empty in Phase 1)

- [ ] **Step 1: 写工具回调的失败测试**

```python
# tests/test_tools.py
"""元 agent 工具回调测试。"""
import json
import pytest
from studio_backend.spec import Spec
from studio_backend.project import Project
from studio_backend.config import StudioConfig
from studio_backend.tools.spec_tools import make_spec_tools
from studio_backend.tools.doc_tools import make_doc_tools
from studio_backend.tools.prefab_tools import make_prefab_tools


def _find_tool(tools, name):
    for t in tools:
        if t.name == name:
            return t
    raise KeyError(name)


def test_add_step_tool():
    spec = Spec()
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "add_step")
    result = tool.callback(
        {"name": "classify", "description": "分类", "type": "agent",
         "prompt_template": "hi"},
        None,
    )
    assert "added" in result.lower() or "ok" in result.lower()
    data = spec.get_current_spec()
    assert data["stages"][0]["name"] == "classify"


def test_add_edge_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    spec.add_step("b", "b", "terminal")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "add_edge")
    tool.callback({"from": "a", "to": "b", "condition": "success"}, None)
    data = spec.get_current_spec()
    assert data["stages"][0]["next_on_success"] == "b"


def test_remove_step_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "remove_step")
    tool.callback({"name": "a"}, None)
    data = spec.get_current_spec()
    assert len(data["stages"]) == 0


def test_set_step_property_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "set_step_property")
    tool.callback({"step": "a", "key": "output_key", "value": "result_a"}, None)
    data = spec.get_current_spec()
    assert data["stages"][0]["output_key"] == "result_a"


def test_bind_tool_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "bind_tool")
    tool.callback({"step": "a", "tool_ref": "db_query"}, None)
    data = spec.get_current_spec()
    assert data["stages"][0]["tool"] == "db_query"


def test_set_ui_config_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "set_ui_config")
    tool.callback({"step": "a", "display": "chat"}, None)
    data = spec.get_current_spec()
    assert data["stages"][0]["ui"]["display"] == "chat"


def test_get_current_spec_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "get_current_spec")
    result = tool.callback({}, None)
    data = json.loads(result)
    assert len(data["stages"]) == 1
    assert data["stages"][0]["name"] == "a"


def test_validate_spec_tool_passes():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    spec.add_step("b", "b", "terminal")
    spec.add_edge("a", "b", "success")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "validate_spec")
    result = tool.callback({}, None)
    assert "valid" in result.lower() or "ok" in result.lower()


def test_validate_spec_tool_fails():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "validate_spec")
    result = tool.callback({}, None)
    assert "error" in result.lower() or "fail" in result.lower()


def test_remove_edge_tool():
    spec = Spec()
    spec.add_step("a", "a", "agent")
    spec.add_step("b", "b", "terminal")
    spec.add_edge("a", "b", "success")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "remove_edge")
    tool.callback({"from": "a", "to": "b", "condition": "success"}, None)
    data = spec.get_current_spec()
    assert "next_on_success" not in data["stages"][0]


def test_add_step_error_returns_error_message():
    """工具回调不抛异常，返回错误字符串。"""
    spec = Spec()
    spec.add_step("a", "a", "agent")
    tools = make_spec_tools(spec)
    tool = _find_tool(tools, "add_step")
    result = tool.callback(
        {"name": "a", "description": "dup", "type": "agent"}, None
    )
    assert "error" in result.lower()


def test_write_document_tool(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test", api_key="k", api_base="",
    )
    proj = Project.create(config, "测试")
    tools = make_doc_tools(proj)
    tool = _find_tool(tools, "write_document")
    tool.callback({"name": "design.md", "content": "# 设计笔记"}, None)
    doc_path = proj.path / ".studio" / "docs" / "design.md"
    assert doc_path.exists()
    assert "设计笔记" in doc_path.read_text(encoding="utf-8")


def test_list_documents_tool(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test", api_key="k", api_base="",
    )
    proj = Project.create(config, "测试")
    (proj.path / ".studio" / "docs" / "note.md").write_text("hi", encoding="utf-8")
    tools = make_doc_tools(proj)
    tool = _find_tool(tools, "list_documents")
    result = tool.callback({}, None)
    assert "note.md" in result


def test_prefab_tools_return_empty():
    tools = make_prefab_tools()
    assert len(tools) == 3
    list_tool = _find_tool(tools, "list_prefabs")
    result = list_tool.callback({}, None)
    assert "[]" in result or "empty" in result.lower() or "no" in result.lower()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 spec_tools.py**

```python
# studio_backend/tools/__init__.py
```

```python
# studio_backend/tools/spec_tools.py
"""Spec 构建工具——元 agent 通过这些工具增量构建 spec。

每个工具是一个闭包，绑定到 Spec 实例。
工具回调不抛异常——捕获 SpecError 返回错误字符串。
"""
from __future__ import annotations

import json
from typing import Any

import senza

from ..spec import Spec, SpecError


def make_spec_tools(spec: Spec) -> list:
    """创建绑定到 spec 实例的 spec 构建工具列表。"""
    tools = []

    def _add_step(args, ctx):
        try:
            spec.add_step(
                name=args["name"],
                description=args.get("description", ""),
                type=args["type"],
                prompt_template=args.get("prompt_template"),
            )
            return f"Step '{args['name']}' added."
        except SpecError as e:
            return f"Error: {e}"

    tools.append(senza.create_tool(
        name="add_step",
        description="Add a step to the spec. type must be one of: agent, checker, tool, terminal.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Unique step name"},
                "description": {"type": "string", "description": "Step description"},
                "type": {"type": "string", "enum": ["agent", "checker", "tool", "terminal"],
                          "description": "Step type"},
                "prompt_template": {"type": "string", "description": "Prompt template for agent steps"},
            },
            "required": ["name", "description", "type"],
        },
        callback=_add_step,
    ))

    def _add_edge(args, ctx):
        try:
            spec.add_edge(
                from_step=args["from"],
                to_step=args["to"],
                condition=args["condition"],
            )
            return f"Edge {args['from']} --{args['condition']}--> {args['to']} added."
        except SpecError as e:
            return f"Error: {e}"

    tools.append(senza.create_tool(
        name="add_edge",
        description="Add an edge (transition) between two steps with a condition.",
        parameters={
            "type": "object",
            "properties": {
                "from": {"type": "string", "description": "Source step name"},
                "to": {"type": "string", "description": "Target step name"},
                "condition": {"type": "string", "description": "Condition name (e.g. success, reject)"},
            },
            "required": ["from", "to", "condition"],
        },
        callback=_add_edge,
    ))

    def _remove_step(args, ctx):
        try:
            spec.remove_step(args["name"])
            return f"Step '{args['name']}' removed."
        except SpecError as e:
            return f"Error: {e}"

    tools.append(senza.create_tool(
        name="remove_step",
        description="Remove a step from the spec. Edges pointing to it are cleaned up.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Step name to remove"},
            },
            "required": ["name"],
        },
        callback=_remove_step,
    ))

    def _remove_edge(args, ctx):
        try:
            spec.remove_edge(
                from_step=args["from"],
                to_step=args["to"],
                condition=args["condition"],
            )
            return "Edge removed."
        except SpecError as e:
            return f"Error: {e}"

    tools.append(senza.create_tool(
        name="remove_edge",
        description="Remove an edge between two steps.",
        parameters={
            "type": "object",
            "properties": {
                "from": {"type": "string"},
                "to": {"type": "string"},
                "condition": {"type": "string"},
            },
            "required": ["from", "to", "condition"],
        },
        callback=_remove_edge,
    ))

    def _set_step_property(args, ctx):
        try:
            spec.set_step_property(
                step_name=args["step"],
                key=args["key"],
                value=args["value"],
            )
            return f"Property '{args['key']}' set on '{args['step']}'."
        except SpecError as e:
            return f"Error: {e}"

    tools.append(senza.create_tool(
        name="set_step_property",
        description="Set an arbitrary property on a step.",
        parameters={
            "type": "object",
            "properties": {
                "step": {"type": "string", "description": "Step name"},
                "key": {"type": "string", "description": "Property key"},
                "value": {"description": "Property value (any JSON type)"},
            },
            "required": ["step", "key", "value"],
        },
        callback=_set_step_property,
    ))

    def _bind_tool(args, ctx):
        try:
            spec.set_step_property(args["step"], "tool", args["tool_ref"])
            return f"Tool '{args['tool_ref']}' bound to '{args['step']}'."
        except SpecError as e:
            return f"Error: {e}"

    tools.append(senza.create_tool(
        name="bind_tool",
        description="Bind a prefab tool to a step.",
        parameters={
            "type": "object",
            "properties": {
                "step": {"type": "string", "description": "Step name"},
                "tool_ref": {"type": "string", "description": "Tool name from prefab registry"},
            },
            "required": ["step", "tool_ref"],
        },
        callback=_bind_tool,
    ))

    def _set_ui_config(args, ctx):
        try:
            ui: dict[str, Any] = {"display": args["display"]}
            if args.get("fields"):
                ui["fields"] = args["fields"]
            spec.set_step_property(args["step"], "ui", ui)
            return f"UI config set on '{args['step']}'."
        except SpecError as e:
            return f"Error: {e}"

    tools.append(senza.create_tool(
        name="set_ui_config",
        description="Set the UI display config for a step. display: chat/status/table/chart/approval_form/none.",
        parameters={
            "type": "object",
            "properties": {
                "step": {"type": "string"},
                "display": {
                    "type": "string",
                    "enum": ["chat", "status", "table", "chart", "approval_form", "none"],
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional field names to display",
                },
            },
            "required": ["step", "display"],
        },
        callback=_set_ui_config,
    ))

    def _get_current_spec(args, ctx):
        return json.dumps(spec.get_current_spec(), ensure_ascii=False, indent=2)

    tools.append(senza.create_tool(
        name="get_current_spec",
        description="Get the current spec as JSON. Use this to review the spec before making changes.",
        parameters={"type": "object", "properties": {}},
        callback=_get_current_spec,
    ))

    def _validate_spec(args, ctx):
        try:
            spec.validate()
            return "Spec is valid."
        except SpecError as e:
            return f"Validation error: {e}"

    tools.append(senza.create_tool(
        name="validate_spec",
        description="Validate the spec for completeness. Checks edges, terminal steps, etc.",
        parameters={"type": "object", "properties": {}},
        callback=_validate_spec,
    ))

    return tools
```

- [ ] **Step 4: 实现 doc_tools.py**

```python
# studio_backend/tools/doc_tools.py
"""文档工具——元 agent 写笔记/设计记录，列出项目文档。

Phase 1 只实现 write_document 和 list_documents。
ingest_document / read_document 在 Phase 6 实现。
"""
from __future__ import annotations

import json

import senza

from ..project import Project


def make_doc_tools(project: Project) -> list:
    """创建绑定到 project 的文档工具列表。"""
    tools = []

    def _write_document(args, ctx):
        name = args["name"]
        content = args["content"]
        doc_path = project.path / ".studio" / "docs" / name
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(content, encoding="utf-8")
        return f"Document '{name}' saved."

    tools.append(senza.create_tool(
        name="write_document",
        description="Write a document (design notes, decision records, etc.) to the project.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "File name (e.g. 'design-notes.md')"},
                "content": {"type": "string", "description": "Document content"},
            },
            "required": ["name", "content"],
        },
        callback=_write_document,
    ))

    def _list_documents(args, ctx):
        docs_dir = project.path / ".studio" / "docs"
        if not docs_dir.exists():
            return "[]"
        files = sorted(f.name for f in docs_dir.iterdir() if f.is_file())
        return json.dumps(files, ensure_ascii=False)

    tools.append(senza.create_tool(
        name="list_documents",
        description="List all documents in the project.",
        parameters={"type": "object", "properties": {}},
        callback=_list_documents,
    ))

    return tools
```

- [ ] **Step 5: 实现 prefab_tools.py**

```python
# studio_backend/tools/prefab_tools.py
"""预制件工具——Phase 1 返回空列表占位。Phase 4 填充。"""
from __future__ import annotations

import json

import senza


def make_prefab_tools() -> list:
    """创建预制件工具列表。Phase 1 返回空结果占位。"""
    tools = []

    def _list_prefabs(args, ctx):
        return json.dumps({"tools": [], "components": []}, ensure_ascii=False)

    tools.append(senza.create_tool(
        name="list_prefabs",
        description="List available prefab tools and components. Returns empty in Phase 1.",
        parameters={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["tool", "component", "all"]},
            },
        },
        callback=_list_prefabs,
    ))

    def _search_prefabs(args, ctx):
        return json.dumps([], ensure_ascii=False)

    tools.append(senza.create_tool(
        name="search_prefabs",
        description="Search prefabs by keyword. Returns empty in Phase 1.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
            },
            "required": ["query"],
        },
        callback=_search_prefabs,
    ))

    def _recommend_prefabs(args, ctx):
        return json.dumps([], ensure_ascii=False)

    tools.append(senza.create_tool(
        name="recommend_prefabs",
        description="Recommend prefabs based on a requirement description. Returns empty in Phase 1.",
        parameters={
            "type": "object",
            "properties": {
                "description": {"type": "string"},
            },
            "required": ["description"],
        },
        callback=_recommend_prefabs,
    ))

    return tools
```

- [ ] **Step 6: 运行测试验证通过**

Run: `pytest tests/test_tools.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add studio_backend/tools/ tests/test_tools.py
git commit -m "feat: 元 agent 工具集 — spec/doc/prefab 工具"
```

---

### Task 5: 动态 system prompt

**Files:**
- Create: `studio_backend/system_prompt.py`
- Create: `tests/test_system_prompt.py`

**Interfaces:**
- Consumes: `Spec` from `studio_backend.spec`, `Project` from `studio_backend.project`
- Produces: `build_system_prompt(spec: Spec, project: Project) -> str`

- [ ] **Step 1: 写 system prompt 的失败测试**

```python
# tests/test_system_prompt.py
"""动态 system prompt 组装测试。"""
import pytest
from studio_backend.spec import Spec
from studio_backend.project import Project
from studio_backend.config import StudioConfig
from studio_backend.system_prompt import build_system_prompt


@pytest.fixture
def tmp_project(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test", api_key="k", api_base="",
    )
    return Project.create(config, "测试项目")


def test_prompt_has_fixed_section(tmp_project):
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "Senza Studio" in prompt
    assert "spec" in prompt.lower()


def test_prompt_has_dynamic_spec_summary(tmp_project):
    spec = Spec()
    spec.add_step("classify", "分类", "agent", prompt_template="分类：{input}")
    spec.add_step("done", "完成", "terminal", message="done")
    spec.add_edge("classify", "done", "success")
    prompt = build_system_prompt(spec, tmp_project)
    assert "classify" in prompt
    assert "done" in prompt


def test_prompt_has_empty_spec_indicator(tmp_project):
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "empty" in prompt.lower() or "no steps" in prompt.lower()


def test_prompt_has_document_list(tmp_project):
    (tmp_project.path / ".studio" / "docs" / "design.md").write_text(
        "hi", encoding="utf-8"
    )
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "design.md" in prompt


def test_prompt_has_project_name(tmp_project):
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "测试项目" in prompt


def test_prompt_has_tool_instructions(tmp_project):
    spec = Spec()
    prompt = build_system_prompt(spec, tmp_project)
    assert "add_step" in prompt
    assert "add_edge" in prompt
    assert "validate_spec" in prompt
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_system_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 system_prompt.py**

```python
# studio_backend/system_prompt.py
"""动态 system prompt 组装。

固定段：角色定义、对话规则、spec 构建规范、工具列表
动态段：当前 spec 摘要、项目文档列表

每轮对话前重新组装，确保元 agent 看到最新上下文。
"""
from __future__ import annotations

from .project import Project
from .spec import Spec


_ROLE = """\
You are the meta-agent of Senza Studio, an Agent development workbench for business people. \
Your role is to help users build agent workflows through conversation.

You don't write code. You build specs by calling tools (add_step, add_edge, etc.). \
The spec is a pipeline of steps (agent/checker/tool/terminal) connected by conditional edges. \
When the user describes their needs, you:
1. Understand the business workflow they want to automate.
2. Ask clarifying questions when information is insufficient.
3. Incrementally build the spec using the provided tools.
4. Call validate_spec when you think the spec is complete.
5. Write design notes using write_document when useful.

Prioritize prefab tools over custom generation. When prefabs can't cover a need, \
note it for later (custom tool generation comes in a later phase)."""


_RULES = """\
## Spec Building Rules

- Step types: agent (LLM step), checker (conditional routing), tool (execute a tool), terminal (end).
- Edges use next_on_<condition> semantics. Common conditions: success, reject, approve, return.
- Every spec must have at least one terminal step.
- The first step is the entry point (no incoming edges needed).
- UI config: use set_ui_config to set display type (chat/status/table/chart/approval_form/none).
- Use get_current_spec to review the spec before making changes.
- Use validate_spec to check completeness after modifications.

## Available Tools

### Spec Building
- add_step(name, description, type, prompt_template?) — add a step
- add_edge(from, to, condition) — add a conditional edge
- remove_step(name) — remove a step (cleans up edges)
- remove_edge(from, to, condition) — remove an edge
- set_step_property(step, key, value) — set any property on a step
- bind_tool(step, tool_ref) — bind a prefab tool to a step
- set_ui_config(step, display, fields?) — set UI display config
- get_current_spec() — read current spec as JSON
- validate_spec() — validate spec completeness

### Documents
- write_document(name, content) — write a design note or decision record
- list_documents() — list project documents

### Prefabs
- list_prefabs(kind?) — list available prefabs (empty in current phase)
- search_prefabs(query) — search prefabs (empty in current phase)
- recommend_prefabs(description) — recommend prefabs (empty in current phase)"""


def _spec_summary(spec: Spec) -> str:
    data = spec.get_current_spec()
    stages = data.get("stages", [])
    if not stages:
        return "Current spec: empty (no steps yet)."
    lines = ["Current spec:"]
    for s in stages:
        name = s.get("name", "?")
        stype = s.get("type", "?")
        edges = [
            f"{k.replace('next_on_', '')}→{v}"
            for k, v in s.items()
            if k.startswith("next_on_") and isinstance(v, str)
        ]
        edge_str = f" [{', '.join(edges)}]" if edges else ""
        lines.append(f"  - {name} ({stype}){edge_str}")
    return "\n".join(lines)


def _document_list(project: Project) -> str:
    docs_dir = project.path / ".studio" / "docs"
    if not docs_dir.exists():
        return "Documents: none"
    files = sorted(f.name for f in docs_dir.iterdir() if f.is_file())
    if not files:
        return "Documents: none"
    return "Documents:\n" + "\n".join(f"  - {f}" for f in files)


def build_system_prompt(spec: Spec, project: Project) -> str:
    """组装动态 system prompt。"""
    sections = [
        _ROLE,
        _RULES,
        f"## Project\nName: {project.meta['name']}",
        _spec_summary(spec),
        _document_list(project),
    ]
    return "\n\n".join(sections)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_system_prompt.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add studio_backend/system_prompt.py tests/test_system_prompt.py
git commit -m "feat: 动态 system prompt 组装"
```

---

### Task 6: 元 agent Harness 组装 + Session 管理

**Files:**
- Create: `studio_backend/agent.py`
- Create: `studio_backend/session.py`
- Create: `tests/test_agent.py`

**Interfaces:**
- Consumes: `StudioConfig`, `Project`, `Spec`, `build_system_prompt`, `make_spec_tools`, `make_doc_tools`, `make_prefab_tools`
- Produces: `StudioAgent` class:
  - `__init__(config: StudioConfig, project: Project, spec: Spec)` — stores refs, does NOT build
  - `start_session(session_id: str | None = None) -> str` — builds harness with session_repo, returns session_id
  - `prompt(text: str, timeout_ms: int = 30000) -> list[dict]` — calls `harness.prompt_and_collect(text, timeout_ms)`
  - `subscribe()` — returns event receiver (call before prompt for streaming)
  - `abort()` — cancels current prompt
  - `rebuild()` — rebuilds harness (call when spec or prompt changes between turns). Preserves session_id.

**Key SDK APIs used (verified from source):**
- `senza.HarnessBuilder(model)` → builder
- `.provider("*", provider)` — register provider
- `.system_prompt(text)` — set system prompt
- `.env(senza.create_os_env(working_dir))` — set execution env
- `.plugin(senza.create_fs_tools_plugin())` — file tools
- `.plugin(senza.strategy.safety_defaults())` / `.loop_safety()` / `.tool_output_guard(env)` / `.injection_filter()`
- `.tools(tool_list)` — register tools (each from `senza.create_tool(...)`)
- `.session_repo(repo, session_id)` — JSONL session persistence (`senza.knowledge.jsonl_session_repo(dir)`)
- `.auto_compact(True)` / `.retry(3, 1000)`
- `.build()` → `AgentHarness`
- `harness.prompt_and_collect(text, timeout_ms=30000)` → `list[dict]`
- `harness.subscribe()` → event receiver
- `harness.abort()` — cancel
- `senza.providers.openai(api_key=..., base_url=...)`

- [ ] **Step 1: 写 agent 组装的失败测试**

```python
# tests/test_agent.py
"""元 agent Harness 组装测试。"""
import pytest
from studio_backend.spec import Spec
from studio_backend.project import Project
from studio_backend.config import StudioConfig
from studio_backend.agent import StudioAgent


@pytest.fixture
def tmp_project(tmp_path):
    config = StudioConfig(
        home_dir=str(tmp_path / ".senza-studio"),
        model="test-model",
        api_key="test-key",
        api_base="",
    )
    return Project.create(config, "测试")


def test_studio_agent_init(tmp_project):
    """StudioAgent 初始化不 build harness（延迟到 start_session）。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    assert agent._harness is None


def test_start_session_creates_harness(tmp_project):
    """start_session 后 harness 非 None。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    session_id = agent.start_session()
    assert session_id is not None
    assert agent._harness is not None


def test_start_session_with_existing_session(tmp_project):
    """用已有 session_id 启动。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    sid = tmp_project.create_session()
    session_id = agent.start_session(sid)
    assert session_id == sid


def test_rebuild_after_spec_change(tmp_project):
    """spec 变化后 rebuild 更新 system prompt。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    agent.start_session()
    old_prompt = agent._system_prompt_text
    spec.add_step("a", "a", "terminal", message="done")
    agent.rebuild()
    new_prompt = agent._system_prompt_text
    assert old_prompt != new_prompt
    assert "a" in new_prompt


def test_rebuild_preserves_session(tmp_project):
    """rebuild 后 session_id 不变。"""
    spec = Spec()
    agent = StudioAgent(tmp_project.config, tmp_project, spec)
    sid = agent.start_session()
    agent.rebuild()
    assert agent._session_id == sid
```

> **Note:** 这些测试不调用 `prompt()` — 那需要真实 LLM API。prompt 的集成测试在手动验收阶段做。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_agent.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 session.py**

```python
# studio_backend/session.py
"""元 agent session 生命周期管理。

Session 是元 agent 的对话历史持久化。每个 session 对应一个 JSONL 文件。
"""
from __future__ import annotations

from pathlib import Path


def session_file_path(sessions_dir: Path, session_id: str) -> Path:
    """返回 session JSONL 文件路径。"""
    return sessions_dir / f"{session_id}.jsonl"


def session_exists(sessions_dir: Path, session_id: str) -> bool:
    """检查 session 是否存在。"""
    return session_file_path(sessions_dir, session_id).exists()
```

- [ ] **Step 4: 实现 agent.py**

```python
# studio_backend/agent.py
"""元 agent Harness 组装。

参考 senza-agent create_agent() 模式，简化：
- 去掉 advisor / acceptance gate / behavior bundle（Studio 元 agent 不需要）
- 去掉 web tools / code exec（元 agent 只做 spec 构建）
- 保留 safety / loop_safety / tool_output_guard / injection_filter
- 加 session_repo 实现持久化
- system prompt 动态组装
"""
from __future__ import annotations

import sys
from typing import Any

from .config import StudioConfig
from .project import Project
from .spec import Spec
from .system_prompt import build_system_prompt
from .tools.spec_tools import make_spec_tools
from .tools.doc_tools import make_doc_tools
from .tools.prefab_tools import make_prefab_tools


def _create_provider(config: StudioConfig) -> Any:
    """创建 LLM provider。参考 senza-agent config.create_provider。"""
    import senza

    api_key = config.api_key
    api_base = config.api_base if config.api_base else None
    return senza.providers.openai(api_key=api_key, base_url=api_base)


class StudioAgent:
    """管理一个元 agent Harness 实例。

    生命周期：
    1. __init__ — 存储引用，不 build
    2. start_session(session_id?) — build harness，绑定 session
    3. prompt(text) — 发送 prompt，返回事件列表
    4. rebuild() — spec/prompt 变化后重建 harness（保留 session）
    """

    def __init__(
        self,
        config: StudioConfig,
        project: Project,
        spec: Spec,
    ) -> None:
        self._config = config
        self._project = project
        self._spec = spec
        self._harness: Any = None
        self._session_id: str | None = None
        self._system_prompt_text: str = ""

    def start_session(self, session_id: str | None = None) -> str:
        """Build harness 并绑定 session。"""
        if session_id is None:
            session_id = self._project.create_session()
        elif session_id not in self._project.meta.get("sessions", []):
            self._project.meta.setdefault("sessions", []).append(session_id)
            self._project._save_meta()

        self._project.set_active_session(session_id)
        self._session_id = session_id
        self._build_harness()
        return session_id

    def _build_harness(self) -> None:
        """Build harness with current spec/prompt/tools/session."""
        import senza

        # ── Provider ────────────────────────────────────────
        try:
            provider = _create_provider(self._config)
        except Exception as e:
            print(f"Warning: provider setup failed: {e}", file=sys.stderr)
            raise

        # ── Execution env ───────────────────────────────────
        working_dir = str(self._project.path)
        env = senza.create_os_env(working_dir)

        # ── System prompt (dynamic) ─────────────────────────
        self._system_prompt_text = build_system_prompt(self._spec, self._project)

        # ── Build harness ───────────────────────────────────
        builder = (
            senza.HarnessBuilder(self._config.model)
            .provider("*", provider)
            .system_prompt(self._system_prompt_text)
            .env(env)
            # File tools (read/write for write_document etc.)
            .plugin(senza.create_fs_tools_plugin())
            # Strategy plugins
            .plugin(senza.strategy.safety_defaults())
            .plugin(senza.strategy.loop_safety())
            .plugin(senza.strategy.tool_output_guard(env))
            .plugin(senza.strategy.injection_filter())
            # Studio spec/doc/prefab tools
            .tools(make_spec_tools(self._spec))
            .tools(make_doc_tools(self._project))
            .tools(make_prefab_tools())
            .auto_compact(True)
            .retry(3, 1000)
        )

        # ── Session persistence ─────────────────────────────
        if self._session_id:
            try:
                repo = senza.knowledge.jsonl_session_repo(
                    str(self._project.sessions_dir)
                )
                builder = builder.session_repo(repo, self._session_id)
            except Exception as e:
                print(f"Warning: session_repo setup failed: {e}", file=sys.stderr)

        # ── Build ───────────────────────────────────────────
        self._harness = builder.build()

    def prompt(self, text: str, timeout_ms: int = 30000) -> list[dict]:
        """Send prompt and collect events until settled.

        Returns list of event dicts. Raises RuntimeError on LLM errors.
        """
        if self._harness is None:
            raise RuntimeError("Harness not started. Call start_session() first.")
        return self._harness.prompt_and_collect(text, timeout_ms=timeout_ms)

    def subscribe(self):
        """Return event receiver for streaming. Call before prompt()."""
        if self._harness is None:
            raise RuntimeError("Harness not started. Call start_session() first.")
        return self._harness.subscribe()

    def abort(self) -> None:
        """Cancel current prompt if running."""
        if self._harness is not None:
            self._harness.abort()

    def rebuild(self) -> None:
        """Rebuild harness with current spec/prompt. Preserves session_id."""
        if self._session_id is None:
            raise RuntimeError("No session. Call start_session() first.")
        self._build_harness()
```

- [ ] **Step 5: 运行测试验证通过**

Run: `pytest tests/test_agent.py -v`
Expected: 全部 PASS

- [ ] **Step 6: Commit**

```bash
git add studio_backend/agent.py studio_backend/session.py tests/test_agent.py
git commit -m "feat: 元 agent Harness 组装 + Session 管理"
```

---

### Task 7: WebSocket + REST API 端点

**Files:**
- Modify: `studio_backend/app.py` — 添加 REST 端点 + WebSocket
- Create: `studio_backend/ws.py` — WebSocket 连接管理

**Interfaces:**
- Consumes: `StudioConfig`, `Project`, `Spec`, `StudioAgent` from previous tasks
- Produces REST endpoints:
  - `GET /api/projects` — 列出项目
  - `POST /api/projects` — 创建项目 `{"name": str}` → `{"id": str}`
  - `GET /api/projects/{id}` — 获取项目 meta
  - `GET /api/projects/{id}/spec` — 获取当前 spec
  - `PUT /api/projects/{id}/spec` — 更新 spec（Inspector 直接编辑）
  - `POST /api/projects/{id}/sessions` — 创建 session → `{"session_id": str}`
  - `GET /api/projects/{id}/sessions` — 列出 sessions
- Produces WebSocket endpoint:
  - `WS /ws/projects/{id}` — 双向通信：前端发 `{"type": "prompt", "text": str}`，后端推送元 agent streaming 事件

**Design:**
- 全局 `studio_state` dict 管理活跃项目 + agent 实例
- WebSocket 消息格式：前端→后端 `{"type": "prompt"|"abort", "text"?: str}`，后端→前端 `{"type": "text_delta"|"tool_call_start"|"tool_call_end"|"tool_result"|"message_end"|"settled"|"aborted"|"spec_updated", ...}`
- 元 agent prompt 在后台线程运行，事件通过 `subscribe()` 迭代推送到 WebSocket
- 每次元 agent 完成一轮对话后，自动 save_spec 并推送 `spec_updated` 事件

- [ ] **Step 1: 实现 ws.py**

```python
# studio_backend/ws.py
"""WebSocket 连接管理 + 事件转发。

将元 agent 的 streaming 事件转发给前端 WebSocket。
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from fastapi import WebSocket

from .agent import StudioAgent
from .project import Project
from .spec import Spec


async def run_prompt_streaming(
    websocket: WebSocket,
    agent: StudioAgent,
    project: Project,
    spec: Spec,
    text: str,
) -> None:
    """在后台线程运行 prompt，将事件推送到 WebSocket。

    元 agent prompt_and_collect 是阻塞调用。
    用 subscribe() + 后台线程实现 streaming。
    """
    import senza

    # 订阅事件流
    receiver = agent.subscribe()

    # 在后台线程发送 prompt
    loop = asyncio.get_event_loop()

    def _do_prompt():
        try:
            agent.prompt(text, timeout_ms=120000)
        except Exception as e:
            print(f"Prompt error: {e}", file=sys.stderr)

    # 启动 prompt 线程
    import threading
    prompt_thread = threading.Thread(target=_do_prompt, daemon=True)
    prompt_thread.start()

    # 迭代事件并推送
    try:
        while True:
            # 在线程中获取下一个事件
            event = await loop.run_in_executor(
                None, _next_event, receiver, 2000
            )
            if event is None:
                # 检查 prompt 线程是否结束
                if not prompt_thread.is_alive():
                    break
                continue

            # 推送到 WebSocket
            await websocket.send_json(event)

            # 终止事件
            if event.get("type") in ("settled", "aborted"):
                break
    finally:
        prompt_thread.join(timeout=5)

        # 保存 spec（元 agent 可能修改了它）
        project.save_spec(spec)
        # 推送 spec_updated 事件
        await websocket.send_json({
            "type": "spec_updated",
            "spec": spec.get_current_spec(),
        })


def _next_event(receiver, timeout_ms: int) -> dict | None:
    """从事件接收器获取下一个事件。阻塞最多 timeout_ms 毫秒。"""
    try:
        # Senza 的 subscribe() 返回的 receiver 有 recv 方法
        # 事件迭代器接口：next(receiver) 阻塞
        import senza
        # 使用 senza 的事件迭代
        # receiver 是 harness.subscribe() 的返回值
        # 它支持 next() 调用，超时后返回 None
        event = next(receiver)
        if isinstance(event, dict):
            return event
        # PyO3 对象转 dict
        return dict(event) if event else None
    except StopIteration:
        return None
    except Exception:
        return None
```

- [ ] **Step 2: 修改 app.py 添加 REST + WebSocket 端点**

```python
# studio_backend/app.py
"""FastAPI application factory + REST endpoints + WebSocket."""
from __future__ import annotations

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import StudioConfig
from .project import Project
from .spec import Spec, SpecError
from .agent import StudioAgent
from .ws import run_prompt_streaming


# ── 全局状态 ──────────────────────────────────────────────
# 活跃项目缓存: {project_id: {"project": Project, "spec": Spec, "agent": StudioAgent}}
_studio_state: dict = {}


def _get_or_load_project(config: StudioConfig, project_id: str) -> dict:
    """获取或加载项目到缓存。"""
    if project_id not in _studio_state:
        project = Project.open(config, project_id)
        spec = project.load_spec()
        agent = StudioAgent(config, project, spec)
        _studio_state[project_id] = {
            "project": project,
            "spec": spec,
            "agent": agent,
        }
    return _studio_state[project_id]


def create_app(config: StudioConfig | None = None) -> FastAPI:
    app = FastAPI(title="Senza Studio")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    cfg = config or StudioConfig.from_env()

    # ── Health ────────────────────────────────────────────
    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    # ── Projects ─────────────────────────────────────────
    @app.get("/api/projects")
    async def list_projects():
        return Project.list_all(cfg)

    class CreateProjectReq(BaseModel):
        name: str

    @app.post("/api/projects")
    async def create_project(req: CreateProjectReq):
        proj = Project.create(cfg, req.name)
        return {"id": proj.meta["id"], "name": proj.meta["name"]}

    @app.get("/api/projects/{project_id}")
    async def get_project(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        return state["project"].meta

    # ── Spec ─────────────────────────────────────────────
    @app.get("/api/projects/{project_id}/spec")
    async def get_spec(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        return state["spec"].get_current_spec()

    class UpdateSpecReq(BaseModel):
        spec: dict

    @app.put("/api/projects/{project_id}/spec")
    async def update_spec(project_id: str, req: UpdateSpecReq):
        state = _get_or_load_project(cfg, project_id)
        # 替换 spec 内容
        new_spec = Spec(req.spec)
        state["spec"] = new_spec
        state["project"].save_spec(new_spec)
        # 重建 agent（system prompt 需更新）
        if state["agent"]._session_id is not None:
            state["agent"].rebuild()
        return {"status": "ok"}

    # ── Sessions ─────────────────────────────────────────
    @app.get("/api/projects/{project_id}/sessions")
    async def list_sessions(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        return {
            "sessions": state["project"].meta.get("sessions", []),
            "active": state["project"].meta.get("active_session"),
        }

    @app.post("/api/projects/{project_id}/sessions")
    async def create_session(project_id: str):
        state = _get_or_load_project(cfg, project_id)
        sid = state["project"].create_session()
        return {"session_id": sid}

    # ── WebSocket ────────────────────────────────────────
    @app.websocket("/ws/projects/{project_id}")
    async def project_ws(websocket: WebSocket, project_id: str):
        await websocket.accept()
        state = _get_or_load_project(cfg, project_id)
        agent = state["agent"]
        project = state["project"]
        spec = state["spec"]

        # 如果 agent 还没启动 session，启动一个
        if agent._harness is None:
            active = project.meta.get("active_session")
            agent.start_session(active)

        try:
            while True:
                msg = await websocket.receive_json()
                msg_type = msg.get("type")

                if msg_type == "prompt":
                    text = msg.get("text", "")
                    await run_prompt_streaming(
                        websocket, agent, project, spec, text
                    )

                elif msg_type == "abort":
                    agent.abort()

                elif msg_type == "switch_session":
                    sid = msg.get("session_id")
                    if sid:
                        agent.start_session(sid)
                        await websocket.send_json({
                            "type": "session_switched",
                            "session_id": sid,
                        })

        except WebSocketDisconnect:
            pass

    return app
```

- [ ] **Step 3: 验证 REST 端点**

Run: `cd /Users/hhl/Documents/projs/oh-my-harness/senza-studio && python -c "
from studio_backend.app import create_app
from studio_backend.config import StudioConfig
from fastapi.testclient import TestClient
import tempfile, os
with tempfile.TemporaryDirectory() as tmp:
    os.environ['SENZA_STUDIO_HOME'] = tmp
    app = create_app(StudioConfig(home_dir=tmp, model='m', api_key='k', api_base=''))
    client = TestClient(app)
    r = client.get('/api/health')
    assert r.json()['status'] == 'ok'
    r = client.post('/api/projects', json={'name': '测试'})
    assert r.status_code == 200
    pid = r.json()['id']
    r = client.get(f'/api/projects/{pid}')
    assert r.json()['name'] == '测试'
    r = client.get(f'/api/projects/{pid}/spec')
    assert 'stages' in r.json()
    print('REST endpoints OK')
`
Expected: 打印 "REST endpoints OK"

- [ ] **Step 4: Commit**

```bash
git add studio_backend/app.py studio_backend/ws.py
git commit -m "feat: REST API + WebSocket 端点"
```

---

### Task 8: 前端类型定义 + API 客户端 + Zustand store

**Files:**
- Create: `studio_frontend/src/types.ts`
- Create: `studio_frontend/src/api.ts`
- Create: `studio_frontend/src/store.ts`

**Interfaces:**
- Produces: TypeScript 类型: `Step`, `Spec`, `ProjectMeta`, `WsEvent`
- Produces: `api` 对象 — HTTP 客户端方法: `listProjects()`, `createProject(name)`, `getProject(id)`, `getSpec(id)`, `updateSpec(id, spec)`, `createSession(id)`, `listSessions(id)`
- Produces: `useStudioStore` Zustand store — state: `project`, `spec`, `status`, `messages`, `selectedStep`; actions: `setProject`, `setSpec`, `addMessage`, `setStatus`, `selectStep`

- [ ] **Step 1: 实现 types.ts**

```typescript
// studio_frontend/src/types.ts

export type StepType = "agent" | "checker" | "tool" | "terminal";
export type DisplayType = "chat" | "status" | "table" | "chart" | "approval_form" | "none";

export interface Step {
  name: string;
  type: StepType;
  prompt_template?: string;
  output_key?: string;
  tool?: string;
  component?: string;
  message?: string;
  ui?: { display: DisplayType; fields?: string[] };
  [key: string]: unknown; // next_on_* edges, _component, etc.
}

export interface Spec {
  stages: Step[];
}

export interface ProjectMeta {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  status: string;
  model: string;
  active_session: string | null;
  sessions: string[];
}

export interface ChatMessage {
  role: "user" | "assistant" | "tool";
  content: string;
  toolName?: string;
  timestamp: number;
}

export type StudioStatus = "idle" | "conversing" | "spec_ready";

export interface WsEvent {
  type: string;
  text?: string;
  step_id?: string;
  spec?: Spec;
  [key: string]: unknown;
}
```

- [ ] **Step 2: 实现 api.ts**

```typescript
// studio_frontend/src/api.ts
import type { ProjectMeta, Spec } from "./types";

const BASE = "/api";

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${r.status}: ${await r.text()}`);
  return r.json();
}

export const api = {
  listProjects: () => fetchJson<ProjectMeta[]>(`${BASE}/projects`),
  createProject: (name: string) =>
    fetchJson<{ id: string; name: string }>(`${BASE}/projects`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }),
  getProject: (id: string) => fetchJson<ProjectMeta>(`${BASE}/projects/${id}`),
  getSpec: (id: string) => fetchJson<Spec>(`${BASE}/projects/${id}/spec`),
  updateSpec: (id: string, spec: Spec) =>
    fetchJson<{ status: string }>(`${BASE}/projects/${id}/spec`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ spec }),
    }),
  createSession: (id: string) =>
    fetchJson<{ session_id: string }>(`${BASE}/projects/${id}/sessions`, {
      method: "POST",
    }),
  listSessions: (id: string) =>
    fetchJson<{ sessions: string[]; active: string | null }>(
      `${BASE}/projects/${id}/sessions`
    ),
};

export function createWebSocket(projectId: string): WebSocket {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return new WebSocket(`${proto}//${location.host}/ws/projects/${projectId}`);
}
```

- [ ] **Step 3: 实现 store.ts**

```typescript
// studio_frontend/src/store.ts
import { create } from "zustand";
import type { ProjectMeta, Spec, ChatMessage, StudioStatus, Step } from "./types";

interface StudioStore {
  project: ProjectMeta | null;
  spec: Spec;
  status: StudioStatus;
  messages: ChatMessage[];
  selectedStep: Step | null;
  ws: WebSocket | null;

  setProject: (p: ProjectMeta | null) => void;
  setSpec: (s: Spec) => void;
  setStatus: (s: StudioStatus) => void;
  addMessage: (m: ChatMessage) => void;
  selectStep: (s: Step | null) => void;
  setWs: (ws: WebSocket | null) => void;
}

export const useStudioStore = create<StudioStore>((set) => ({
  project: null,
  spec: { stages: [] },
  status: "idle",
  messages: [],
  selectedStep: null,
  ws: null,

  setProject: (project) => set({ project }),
  setSpec: (spec) => set({ spec }),
  setStatus: (status) => set({ status }),
  addMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  selectStep: (selectedStep) => set({ selectedStep }),
  setWs: (ws) => set({ ws }),
}));
```

- [ ] **Step 4: Commit**

```bash
git add studio_frontend/src/types.ts studio_frontend/src/api.ts studio_frontend/src/store.ts
git commit -m "feat: 前端类型 + API 客户端 + Zustand store"
```

---

### Task 9: 前端组件 — 对话面板 + 画布 + Inspector

**Files:**
- Create: `studio_frontend/src/components/ChatPanel.tsx`
- Create: `studio_frontend/src/components/Canvas.tsx`
- Create: `studio_frontend/src/components/Inspector.tsx`
- Create: `studio_frontend/src/components/StatusBar.tsx`
- Modify: `studio_frontend/src/App.tsx`

**Interfaces:**
- Consumes: `useStudioStore`, `api`, `createWebSocket`, types from Task 8
- Produces: editing 模式布局 — 左侧对话面板 + 中间画布 + 右侧 Inspector + 底部状态栏

- [ ] **Step 1: 实现 ChatPanel.tsx**

```typescript
// studio_frontend/src/components/ChatPanel.tsx
import { useState, useRef, useEffect } from "react";
import { useStudioStore } from "../store";
import { createWebSocket } from "../api";
import type { ChatMessage } from "../types";

export default function ChatPanel({ projectId }: { projectId: string }) {
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const messages = useStudioStore((s) => s.messages);
  const addMessage = useStudioStore((s) => s.addMessage);
  const setSpec = useStudioStore((s) => s.setSpec);
  const setStatus = useStudioStore((s) => s.setStatus);
  const ws = useStudioStore((s) => s.ws);
  const setWs = useStudioStore((s) => s.setWs);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 连接 WebSocket
  useEffect(() => {
    const socket = createWebSocket(projectId);
    setWs(socket);

    socket.onmessage = (e) => {
      const event = JSON.parse(e.data);

      if (event.type === "text_delta") {
        // 流式文本追加到最近的 assistant 消息
        addMessage({
          role: "assistant",
          content: event.text || "",
          timestamp: Date.now(),
        });
      } else if (event.type === "tool_call_start") {
        addMessage({
          role: "tool",
          content: `调用工具: ${event.tool_name}`,
          toolName: event.tool_name,
          timestamp: Date.now(),
        });
      } else if (event.type === "tool_result") {
        addMessage({
          role: "tool",
          content: `结果: ${event.result}`,
          toolName: event.tool_name,
          timestamp: Date.now(),
        });
      } else if (event.type === "settled" || event.type === "aborted") {
        setStreaming(false);
        setStatus("spec_ready");
      } else if (event.type === "spec_updated") {
        if (event.spec) setSpec(event.spec);
      }
    };

    return () => socket.close();
  }, [projectId]);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [messages]);

  const send = () => {
    if (!input.trim() || !ws || streaming) return;
    addMessage({ role: "user", content: input, timestamp: Date.now() });
    ws.send(JSON.stringify({ type: "prompt", text: input }));
    setInput("");
    setStreaming(true);
    setStatus("conversing");
  };

  return (
    <div className="flex flex-col h-full w-96 border-r border-gray-200 bg-white">
      <div className="px-4 py-3 border-b border-gray-200 font-medium text-gray-700">
        对话
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-3">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`rounded-lg p-3 text-sm ${
              m.role === "user"
                ? "bg-blue-50 text-blue-900 ml-8"
                : m.role === "tool"
                ? "bg-gray-50 text-gray-600 text-xs font-mono"
                : "bg-gray-50 text-gray-800 mr-8"
            }`}
          >
            {m.content}
          </div>
        ))}
      </div>
      <div className="p-4 border-t border-gray-200">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
            placeholder="描述你想要的 Agent 流程…"
            className="flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:border-blue-400"
            disabled={streaming}
          />
          <button
            onClick={send}
            disabled={streaming || !input.trim()}
            className="rounded-lg bg-blue-500 px-4 py-2 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
          >
            发送
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 实现 Canvas.tsx**

```typescript
// studio_frontend/src/components/Canvas.tsx
import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  type Node,
  type Edge,
  Position,
} from "reactflow";
import { useStudioStore } from "../store";
import type { Step } from "../types";

const TYPE_COLORS: Record<string, string> = {
  agent: "#3b82f6",
  checker: "#f59e0b",
  tool: "#10b981",
  terminal: "#6b7280",
};

export default function Canvas() {
  const spec = useStudioStore((s) => s.spec);
  const selectStep = useStudioStore((s) => s.selectStep);
  const selectedStep = useStudioStore((s) => s.selectedStep);

  const { nodes, edges } = useMemo(() => {
    const stages = spec.stages || [];

    // 简单布局：垂直排列
    const nodes: Node[] = stages.map((step, i) => ({
      id: step.name,
      data: {
        label: (
          <div className="text-center">
            <div className="font-medium text-sm">{step.name}</div>
            <div className="text-xs text-gray-500">{step.type}</div>
          </div>
        ),
      },
      position: { x: 250, y: i * 120 },
      style: {
        border: `2px solid ${TYPE_COLORS[step.type] || "#ccc"}`,
        borderRadius: "8px",
        padding: "8px 16px",
        background: selectedStep?.name === step.name ? "#eff6ff" : "#fff",
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    }));

    // 从 next_on_* 字段提取边
    const edges: Edge[] = [];
    for (const step of stages) {
      for (const [key, val] of Object.entries(step)) {
        if (key.startsWith("next_on_") && typeof val === "string") {
          const condition = key.replace("next_on_", "");
          edges.push({
            id: `${step.name}-${condition}-${val}`,
            source: step.name,
            target: val,
            label: condition,
            type: "smoothstep",
            animated: true,
          });
        }
      }
    }

    return { nodes, edges };
  }, [spec, selectedStep]);

  return (
    <div className="flex-1 h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        onNodeClick={(_, node) => {
          const step = spec.stages.find((s) => s.name === node.id);
          if (step) selectStep(step as Step);
        }}
      >
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
```

- [ ] **Step 3: 实现 Inspector.tsx**

```typescript
// studio_frontend/src/components/Inspector.tsx
import { useStudioStore } from "../store";
import { api } from "../api";

export default function Inspector({ projectId }: { projectId: string }) {
  const selectedStep = useStudioStore((s) => s.selectedStep);
  const spec = useStudioStore((s) => s.spec);
  const setSpec = useStudioStore((s) => s.setSpec);

  if (!selectedStep) {
    return (
      <div className="w-80 border-l border-gray-200 bg-white p-4 text-sm text-gray-400">
        选择一个节点查看属性
      </div>
    );
  }

  const updateField = (key: string, value: unknown) => {
    const newStages = spec.stages.map((s) =>
      s.name === selectedStep.name ? { ...s, [key]: value } : s
    );
    const newSpec = { ...spec, stages: newStages };
    setSpec(newSpec);
    api.updateSpec(projectId, newSpec).catch(console.error);
  };

  return (
    <div className="w-80 border-l border-gray-200 bg-white p-4 overflow-y-auto">
      <h3 className="font-medium text-gray-700 mb-3">属性</h3>
      <div className="space-y-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">name</label>
          <input
            value={selectedStep.name}
            readOnly
            className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-500 mb-1">type</label>
          <input
            value={selectedStep.type}
            readOnly
            className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
          />
        </div>
        {selectedStep.prompt_template !== undefined && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">prompt_template</label>
            <textarea
              value={selectedStep.prompt_template || ""}
              onChange={(e) => updateField("prompt_template", e.target.value)}
              rows={5}
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm font-mono"
            />
          </div>
        )}
        {selectedStep.tool && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">tool</label>
            <input
              value={selectedStep.tool}
              readOnly
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
            />
          </div>
        )}
        {selectedStep.message !== undefined && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">message</label>
            <input
              value={selectedStep.message || ""}
              onChange={(e) => updateField("message", e.target.value)}
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm"
            />
          </div>
        )}
        {selectedStep.ui && (
          <div>
            <label className="block text-xs text-gray-500 mb-1">ui.display</label>
            <input
              value={selectedStep.ui.display}
              readOnly
              className="w-full rounded border border-gray-200 px-2 py-1 text-sm bg-gray-50"
            />
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 实现 StatusBar.tsx**

```typescript
// studio_frontend/src/components/StatusBar.tsx
import { useStudioStore } from "../store";

export default function StatusBar() {
  const project = useStudioStore((s) => s.project);
  const status = useStudioStore((s) => s.status);
  const spec = useStudioStore((s) => s.spec);

  const stepCount = spec.stages.length;

  return (
    <div className="flex items-center justify-between px-4 py-2 border-t border-gray-200 bg-gray-50 text-xs text-gray-600">
      <div className="flex items-center gap-4">
        {project && <span>{project.name}</span>}
        <span>状态: {status}</span>
        <span>{stepCount} 步骤</span>
      </div>
      <div>{project?.model || ""}</div>
    </div>
  );
}
```

- [ ] **Step 5: 修改 App.tsx 组装布局**

```typescript
// studio_frontend/src/App.tsx
import { useEffect, useState } from "react";
import { useStudioStore } from "./store";
import { api } from "./api";
import ChatPanel from "./components/ChatPanel";
import Canvas from "./components/Canvas";
import Inspector from "./components/Inspector";
import StatusBar from "./components/StatusBar";
import type { ProjectMeta } from "./types";

export default function App() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const setProject = useStudioStore((s) => s.setProject);
  const setSpec = useStudioStore((s) => s.setSpec);
  const [projects, setProjects] = useState<ProjectMeta[]>([]);
  const [newName, setNewName] = useState("");

  // 加载项目列表
  useEffect(() => {
    api.listProjects().then(setProjects).catch(console.error);
  }, []);

  // 打开项目
  const openProject = async (id: string) => {
    const meta = await api.getProject(id);
    const spec = await api.getSpec(id);
    setProject(meta);
    setSpec(spec);
    setProjectId(id);
  };

  // 创建项目
  const createProject = async () => {
    if (!newName.trim()) return;
    const { id } = await api.createProject(newName);
    setNewName("");
    const meta = await api.getProject(id);
    const spec = await api.getSpec(id);
    setProject(meta);
    setSpec(spec);
    setProjectId(id);
  };

  if (!projectId) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center bg-gray-50 gap-6">
        <h1 className="text-2xl font-bold text-gray-700">Senza Studio</h1>
        <div className="flex gap-2">
          <input
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && createProject()}
            placeholder="项目名称…"
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm"
          />
          <button
            onClick={createProject}
            className="rounded-lg bg-blue-500 px-4 py-2 text-sm text-white hover:bg-blue-600"
          >
            创建项目
          </button>
        </div>
        {projects.length > 0 && (
          <div className="w-96">
            <h2 className="text-sm text-gray-500 mb-2">已有项目</h2>
            <div className="space-y-1">
              {projects.map((p) => (
                <button
                  key={p.id}
                  onClick={() => openProject(p.id)}
                  className="block w-full text-left rounded-lg border border-gray-200 px-4 py-2 text-sm hover:bg-gray-100"
                >
                  {p.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="h-full w-full flex flex-col">
      <div className="flex-1 flex overflow-hidden">
        <ChatPanel projectId={projectId} />
        <Canvas />
        <Inspector projectId={projectId} />
      </div>
      <StatusBar />
    </div>
  );
}
```

- [ ] **Step 6: 验证前端编译**

Run: `cd studio_frontend && npx tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 7: 验证前端运行**

Run: `cd studio_frontend && npm run dev`
Expected: 浏览器显示项目创建/选择界面

- [ ] **Step 8: Commit**

```bash
git add studio_frontend/src/components/ studio_frontend/src/App.tsx
git commit -m "feat: 前端组件 — 对话面板 + 画布 + Inspector + 状态栏"
```

---

### Task 10: Electron 壳 + 端到端验收

**Files:**
- Create: `studio_frontend/electron/main.cjs`
- Modify: `studio_frontend/package.json` — 加 electron 依赖和 main 入口

**Interfaces:**
- Produces: Electron 应用，启动时自动 spawn Python 后端，加载 `http://localhost:5173`（开发期）或 `http://localhost:7878`（生产期）

- [ ] **Step 1: 实现 Electron 主进程**

```javascript
// studio_frontend/electron/main.cjs
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");

let pythonProcess = null;
let mainWindow = null;

function startBackend() {
  // 开发期：从项目根目录启动 Python 后端
  const backendPath = path.resolve(__dirname, "../../studio_backend");
  pythonProcess = spawn("python", ["-m", "studio_backend.server"], {
    cwd: path.resolve(__dirname, "../../"),
    env: { ...process.env, PYTHONPATH: backendPath },
  });

  pythonProcess.stdout.on("data", (data) => {
    console.log(`[backend] ${data}`);
  });
  pythonProcess.stderr.on("data", (data) => {
    console.error(`[backend] ${data}`);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // 开发期加载 Vite dev server，生产期加载后端
  const isDev = !app.isPackaged;
  if (isDev) {
    mainWindow.loadURL("http://localhost:5173");
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadURL("http://localhost:7878");
  }
}

app.whenReady().then(() => {
  startBackend();
  // 等后端启动
  setTimeout(createWindow, 2000);

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  if (pythonProcess) {
    pythonProcess.kill();
  }
});
```

- [ ] **Step 2: 修改 package.json 加 electron**

在 `studio_frontend/package.json` 的 `devDependencies` 中加:
```json
    "electron": "^31.0.0"
```

在 `scripts` 中加:
```json
    "electron:dev": "electron electron/main.cjs"
```

- [ ] **Step 3: 安装 electron 依赖**

Run: `cd studio_frontend && npm install`
Expected: electron 安装成功

- [ ] **Step 4: 端到端验收**

Prerequisites:
- 后端: `pip install -e ../Senza && pip install fastapi uvicorn[standard] pyyaml`
- 前端: `cd studio_frontend && npm install`
- 环境变量: `export SENZA_STUDIO_API_KEY=<your-api-key>` 和 `export SENZA_STUDIO_MODEL=<model-name>`

Manual test steps:
1. 启动后端: `python -m studio_backend.server` (在项目根目录)
2. 启动前端: `cd studio_frontend && npm run dev`
3. 打开浏览器 `http://localhost:5173`
4. 创建项目 "测试项目"
5. 在对话面板输入 "帮我创建一个简单的客服分类流程，有3个步骤：分类(agent)、处理(agent)、完成(terminal)"
6. 观察元 agent 调用 add_step / add_edge 工具
7. 画布应实时显示 DAG（3 个节点 + 边）
8. 在画布选中一个节点，Inspector 显示属性
9. 在 Inspector 编辑 prompt_template，画布/状态应反映变更
10. 关闭浏览器，重新打开 → 选择同一项目 → spec 和对话历史恢复

- [ ] **Step 5: Commit**

```bash
git add studio_frontend/electron/ studio_frontend/package.json
git commit -m "feat: Electron 壳 + 端到端验收"
```

---

## Self-Review Notes

### Spec coverage (design-v2.md §3, §4, §9)

- §3 数据模型: Project 目录结构 ✓ (Task 3), Spec dict + YAML ✓ (Task 2), meta.json ✓ (Task 3), pipeline.yaml ui 字段 ✓ (Task 2 spec dict preserves arbitrary fields), component 字段 ✓ (spec dict preserves, Phase 4 展开)
- §4 元 Agent 层: AgentHarness 组装 ✓ (Task 6), 动态 system prompt ✓ (Task 5), 工具集 ✓ (Task 4), Session 管理 ✓ (Task 6), 4.7 所有工具 ✓ (Task 4)
- §9 前端架构: editing 布局 ✓ (Task 9), Zustand store ✓ (Task 8), ReactFlow 画布 ✓ (Task 9), Inspector 编辑态 ✓ (Task 9), 对话面板 ✓ (Task 9)

### Phase 1 不做项 (implementation-phases.md)
- Play / 运行 spec — Phase 2
- 预制件实际内容 — Phase 4 (Task 4 返回空占位)
- 文档解析 — Phase 6 (Task 4 只有 write/list)
- Export — Phase 7
- generate_tool — Phase 5 (Task 4 无 generate_tool)

### Type consistency check
- `Spec.get_current_spec()` 返回 dict — 所有 task 一致
- `make_spec_tools(spec)` 返回 list — Task 4/6 一致
- `StudioAgent.__init__(config, project, spec)` — Task 6 定义，Task 7 消费
- `build_system_prompt(spec, project)` — Task 5 定义，Task 6 消费
- 前端 `Spec` / `Step` 类型 — Task 8 定义，Task 9 消费