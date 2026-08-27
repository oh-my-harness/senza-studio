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

  # Senza 的 Cargo.toml 里 runtime 依赖故意留 PLACEHOLDER（真实 commit
  # 记在 senza-pkg/runtime.lock），只有 scripts/build_wheel.sh 会做替换
  # 再构建。所以这里不能 `pip install -e ../Senza`（等价于绕过替换直接
  # 对着 PLACEHOLDER 编译，一定失败）——必须先构建 wheel 再安装。
  echo "📦 构建 Senza SDK wheel..."
  (cd ../Senza && ./scripts/build_wheel.sh)
  SENZA_WHEEL=$(ls -t ../Senza/dist/senza_sdk*.whl ../Senza/dist/senza*.whl 2>/dev/null | head -1)
  if [ -z "$SENZA_WHEEL" ]; then
    echo "❌ 未在 ../Senza/dist/ 找到构建好的 wheel"
    exit 1
  fi
  echo "📦 安装 Senza wheel: $SENZA_WHEEL"
  uv pip install "$SENZA_WHEEL" --force-reinstall
  # 用 uv pip 而非裸 `pip`——某些 shell 环境里 `pip` 被 alias 到系统/
  # 全局 pip3，会绕过当前 venv 并可能撞上不同的网络/证书配置。
  uv pip install fastapi uvicorn pydantic pyyaml websockets

  # 记录本次验证过的 senza-sdk 版本/commit——Studio 的 SDK 知识（system
  # prompt、tool 调用）只在这个 pin 之下被验证过；drift 检测和启动时的
  # 校验都以这个文件为准，而不是"whatever happens to be installed"。
  SENZA_COMMIT=$(git -C ../Senza rev-parse HEAD)
  SENZA_VERSION=$(python -c "import importlib.metadata as m; print(m.version('senza-sdk'))")
  cat > senza-sdk.lock <<EOF
{
  "senza_version": "$SENZA_VERSION",
  "senza_commit": "$SENZA_COMMIT",
  "verified_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
  echo "🔒 已记录 senza-sdk.lock (version=$SENZA_VERSION, commit=${SENZA_COMMIT:0:12})"
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
