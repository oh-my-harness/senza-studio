#!/usr/bin/env bash
# Senza Studio 本地一键启动脚本
# 用法: ./dev.sh
set -euo pipefail

cd "$(dirname "$0")"

# ── 配置 ────────────────────────────────────────────────
MODEL="${SENZA_STUDIO_MODEL:-glm-5.2}"
BACKEND_PORT=7878
FRONTEND_PORT=5173

# ── 清理函数 ────────────────────────────────────────────
cleanup() {
  echo ""
  echo "正在停止服务..."
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null
  wait 2>/dev/null
  echo "已停止。"
}
trap cleanup EXIT INT TERM

# ── 杀死已有进程 ────────────────────────────────────────
echo "🧹 清理已有进程..."

# 杀后端: 占用 7878 端口的进程
BACKEND_PIDS=$(lsof -ti tcp:$BACKEND_PORT 2>/dev/null || true)
if [ -n "$BACKEND_PIDS" ]; then
  echo "  杀死后端 (port $BACKEND_PORT): $BACKEND_PIDS"
  kill $BACKEND_PIDS 2>/dev/null || true
  sleep 1
fi

# 杀前端: 占用 5173 端口的进程
FRONTEND_PIDS=$(lsof -ti tcp:$FRONTEND_PORT 2>/dev/null || true)
if [ -n "$FRONTEND_PIDS" ]; then
  echo "  杀死前端 (port $FRONTEND_PORT): $FRONTEND_PIDS"
  kill $FRONTEND_PIDS 2>/dev/null || true
  sleep 1
fi

# 杀残留的 studio_backend.server 进程
STUDIO_PIDS=$(pgrep -f "studio_backend.server" 2>/dev/null || true)
if [ -n "$STUDIO_PIDS" ]; then
  echo "  杀死残留 studio_backend: $STUDIO_PIDS"
  kill $STUDIO_PIDS 2>/dev/null || true
fi

# 杀残留的 vite dev server
VITE_PIDS=$(pgrep -f "vite" 2>/dev/null || true)
if [ -n "$VITE_PIDS" ]; then
  echo "  杀死残留 vite: $VITE_PIDS"
  kill $VITE_PIDS 2>/dev/null || true
fi

sleep 1

# ── 检查 .venv ──────────────────────────────────────────
if [ ! -d ".venv" ]; then
  echo "❌ .venv 不存在，正在创建..."
  uv venv --python 3.12
  source .venv/bin/activate
  pip install -e ../Senza
  pip install fastapi uvicorn pydantic pyyaml websockets
else
  source .venv/bin/activate
fi

# ── 检查 node_modules ───────────────────────────────────
if [ ! -d "studio_frontend/node_modules" ]; then
  echo "❌ node_modules 不存在，正在安装..."
  cd studio_frontend && npm install && cd ..
fi

# ── 启动后端 ────────────────────────────────────────────
echo "🚀 启动后端 (model=$MODEL, port=$BACKEND_PORT)..."
SENZA_STUDIO_MODEL="$MODEL" PYTHONPATH=studio_backend \
  python -m studio_backend.server &
BACKEND_PID=$!

# ── 等待后端就绪 ────────────────────────────────────────
echo "⏳ 等待后端就绪..."
for i in $(seq 1 15); do
  if curl -sf "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null 2>&1; then
    echo "✅ 后端就绪"
    break
  fi
  [ "$i" -eq 15 ] && { echo "❌ 后端启动超时"; exit 1; }
  sleep 1
done

# ── 启动前端 ────────────────────────────────────────────
echo "🚀 启动前端 (port=$FRONTEND_PORT)..."
cd studio_frontend
npm run dev &
FRONTEND_PID=$!
cd ..

# ── 等待前端就绪 ────────────────────────────────────────
echo "⏳ 等待前端就绪..."
for i in $(seq 1 15); do
  if curl -sf "http://localhost:$FRONTEND_PORT/" >/dev/null 2>&1; then
    echo "✅ 前端就绪"
    break
  fi
  [ "$i" -eq 15 ] && { echo "❌ 前端启动超时"; exit 1; }
  sleep 1
done

# ── 完成 ────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════"
echo "  Senza Studio 已启动"
echo "  前端: http://localhost:$FRONTEND_PORT"
echo "  后端: http://127.0.0.1:$BACKEND_PORT"
echo "  模型: $MODEL"
echo "  按 Ctrl+C 停止"
echo "════════════════════════════════════════════"
echo ""

wait
