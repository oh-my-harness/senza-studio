# arcgensenza 基础设施调研报告

调研对象：`../arcgensenza`（EDA Agent，pipeline/webui/打包参考实现）。

## 1. 整体架构

```
arcgensenza = pipeline.yaml → Senza WorkflowEngine + FastAPI/React WebUI + Electron 壳
├── pipeline.yaml              # 唯一编排真相
├── eda_agent_py/
│   ├── orchestrator/config.py # pipeline 解析
│   ├── workflow_adapter/ffi_bridge.py  # stages→workflow, executor, judge
│   ├── executor.py            # 按 type 分派 (agent/tool/checker)
│   ├── tools/registry.py      # ~35 个预制工具
│   └── agent_call.py          # LLM 调用
├── webui/ (FastAPI + React)
├── electron/main.cjs          # sidecar 壳
├── pack_python.sh             # 完整包
└── pack_code_only.sh          # 轻量包
```

## 2. pipeline.yaml 格式

pipeline.yaml 是唯一的编排真相，通过 `stages_to_workflow` 编译为 Senza WorkflowEngine 可执行的 workflow dict。

senza 1.0 移除了 Python 侧的 `stages_to_workflow` 方法，所以 arcgensenza 在 Python 侧自行构建 workflow dict。但 SDK 的 Rust 侧 `stages_to_workflow`（`pyworkflow.rs:642`）仍然存在，Studio 应直接使用 SDK 侧。

## 3. executor/judge 分派模式

**路由模型**：executor 产 `route_key` → judge 结合 `next_on_*` 映射到转移字符串 → Rust 推进。

```python
# executor callback
def executor_cb(ctx):
    route_key = execute_stage(stage, ctx)  # 按 type 分派
    return {"output": ..., "structured": {"route_key": route_key}}

# judge callback
def judge_cb(ctx):
    route_key = ctx["structured"]["route_key"]
    next_stage = resolve_next(current_step, route_key, loop_counter)
    return f"to:{next_stage}"  # or "abort:done" / "fail:reason"
```

executor 按 `type` 字段分派：
- `type: agent` — 调用 LLM agent
- `type: tool` — 执行工具
- `type: checker` — 执行检查器

## 4. WebUI 模式

- 后端：FastAPI REST（薄包装）+ WebSocket（SnapshotWatcher 2s 轮询快照，SHA256 hash 去重推送）
- 前端：React + Vite + zustand，SessionSocket 指数退避重连

## 5. 打包

| 脚本 | 产出 | 说明 |
|---|---|---|
| `pack_python.sh` | 完整包 | Python3.14+stdlib+site-packages，可选 `--bundle-glibc` |
| `pack_code_only.sh` | 轻量包 | 仅代码 |

## 6. Electron 壳

**文件**：`electron/main.cjs`

sidecar 模式：spawn Python webserver → 轮询 `/api/health` → BrowserWindow → 退出杀进程组。

## 7. 预制工具系统

**文件**：`eda_agent_py/tools/registry.py`

约 35 个预制工具，按类别组织。工具函数与注册分离，类似 senza-agent 的模式。

## 8. Studio 可借鉴要点

| 模式 | 来源 | Studio 用途 |
|---|---|---|
| pipeline.yaml 格式 | pipeline.yaml | Studio pipeline 格式直接兼容 |
| executor/judge 分派 | ffi_bridge.py | type: agent/checker/tool 语义执行 |
| FastAPI + WebSocket | webui/ | 导出项目 webui 的后端参考 |
| React + zustand | webui/ | 导出项目 webui 的前端参考 |
| pack_python.sh | pack_python.sh | 导出项目打包参考 |
| Electron sidecar | electron/main.cjs | 导出项目桌面壳参考 |
