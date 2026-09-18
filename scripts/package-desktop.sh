#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-current}"
AGENT_TEAM_BIN="${SENZA_STUDIO_AGENT_TEAM_BIN:-}"
CACHE_DIR="$ROOT/.cache/desktop-python"
RESOURCE_DIR="$ROOT/build/desktop-resources"

if [[ -z "$AGENT_TEAM_BIN" ]]; then
  echo "SENZA_STUDIO_AGENT_TEAM_BIN is required" >&2
  exit 1
fi
if [[ ! -f "$AGENT_TEAM_BIN" || ! -x "$AGENT_TEAM_BIN" ]]; then
  echo "SENZA_STUDIO_AGENT_TEAM_BIN is not an executable file: $AGENT_TEAM_BIN" >&2
  exit 1
fi
if [[ "$(uname -s)" == "Linux" ]] && command -v file >/dev/null 2>&1; then
  if file "$AGENT_TEAM_BIN" | grep -q "with debug_info"; then
    echo "SENZA_STUDIO_AGENT_TEAM_BIN must be a release build without debug info" >&2
    exit 1
  fi
fi

cd "$ROOT/studio_frontend"
ELECTRON_SKIP_BINARY_DOWNLOAD=1 npm ci
npm run build
npm test -- --run
cd "$ROOT"

case "$TARGET" in
  current)
    case "$(uname -s):$(uname -m)" in
      Linux:x86_64) TARGET="linux" ;;
      Darwin:x86_64) TARGET="mac" ;;
      Darwin:arm64) TARGET="mac" ;;
      MINGW*:x86_64|CYGWIN*:x86_64|MSYS*:x86_64) TARGET="win" ;;
      *) echo "Unsupported packaging host: $(uname -s) $(uname -m)" >&2; exit 1 ;;
    esac
    ;;
  linux|mac|win) ;;
  *)
    echo "Usage: $0 [current|linux|mac|win]" >&2
    exit 1
    ;;
esac

case "$(uname -s):$(uname -m)" in
  Linux:x86_64) HOST_PLATFORM="linux-x86_64" ;;
  Darwin:x86_64) HOST_PLATFORM="mac-x86_64" ;;
  Darwin:arm64) HOST_PLATFORM="mac-arm64" ;;
  MINGW*:x86_64|CYGWIN*:x86_64|MSYS*:x86_64) HOST_PLATFORM="windows-x86_64" ;;
  *) HOST_PLATFORM="" ;;
esac

if [[ "$TARGET" == "linux" ]]; then
  PYTHON_PLATFORM="linux-x86_64"
  BUILDER_ARGS=(--linux AppImage)
elif [[ "$TARGET" == "mac" ]]; then
  PYTHON_PLATFORM="$HOST_PLATFORM"
  BUILDER_ARGS=(--mac dmg)
elif [[ "$TARGET" == "win" ]]; then
  PYTHON_PLATFORM="windows-x86_64"
  BUILDER_ARGS=(--win nsis)
fi

if [[ -z "$PYTHON_PLATFORM" || -z "$HOST_PLATFORM" ]]; then
  echo "Unable to determine the host Python runtime platform" >&2
  exit 1
fi
if [[ "$PYTHON_PLATFORM" != "$HOST_PLATFORM" ]]; then
  echo "Cross-platform desktop packaging is not supported; build on the target platform" >&2
  exit 1
fi
if [[ "$TARGET" == "win" ]]; then
  if [[ -z "${SIGNTOOL_PATH:-}" ]]; then
    while IFS= read -r candidate; do
      if [[ -f "$candidate" ]]; then
        SIGNTOOL_PATH="$(cygpath -w "$candidate")"
        break
      fi
    done < <(find "/c/Program Files (x86)/Windows Kits/10/bin" \
      -type f -name signtool.exe -path '*/x64/*' 2>/dev/null | sort -rV)
  fi
  if [[ -z "${SIGNTOOL_PATH:-}" ]]; then
    echo "SIGNTOOL_PATH or Windows SDK signtool.exe is required" >&2
    exit 1
  fi
  export SIGNTOOL_PATH
  if [[ -z "${WIN_CSC_LINK:-}" && -z "${CSC_LINK:-}" ]]; then
    echo "WIN_CSC_LINK (or CSC_LINK) is required for Windows code signing" >&2
    exit 1
  fi
  if [[ -z "${WIN_CSC_KEY_PASSWORD:-}" && -z "${CSC_KEY_PASSWORD:-}" ]]; then
    echo "WIN_CSC_KEY_PASSWORD (or CSC_KEY_PASSWORD) is required for Windows code signing" >&2
    exit 1
  fi
fi

RUNTIME_METADATA="$(node -e '
const fs = require("fs");
const metadata = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const platform = metadata.platforms[process.argv[2]];
if (!platform) process.exit(1);
process.stdout.write([platform.url, platform.sha256, platform.archive].join("\t"));
' "$ROOT/packaging/python-runtime.json" "$PYTHON_PLATFORM")"
IFS=$'\t' read -r PYTHON_ARCHIVE_URL PYTHON_ARCHIVE_SHA256 PYTHON_ARCHIVE_NAME <<< "$RUNTIME_METADATA"

file_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

copy_python_tree() {
  local source="$1"
  local destination="$2"
  mkdir -p "$destination"
  tar -cf - \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    -C "$source" . | tar -xf - -C "$destination"
}

mkdir -p "$CACHE_DIR"
PYTHON_ARCHIVE_PATH="$CACHE_DIR/$PYTHON_ARCHIVE_NAME"
CURL_CA_ARGS=()
if [[ -n "${SENZA_STUDIO_CACERT:-}" ]]; then
  CURL_CA_ARGS=(--cacert "$SENZA_STUDIO_CACERT")
fi
if [[ ! -f "$PYTHON_ARCHIVE_PATH" ]] || [[ "$(file_sha256 "$PYTHON_ARCHIVE_PATH")" != "$PYTHON_ARCHIVE_SHA256" ]]; then
  curl --fail --location --retry 5 --retry-delay 2 \
    --connect-timeout 15 --max-time 600 \
    --speed-limit 1024 --speed-time 30 \
    "${CURL_CA_ARGS[@]}" \
    --output "$PYTHON_ARCHIVE_PATH" "$PYTHON_ARCHIVE_URL"
fi
ACTUAL_PYTHON_SHA256="$(file_sha256 "$PYTHON_ARCHIVE_PATH")"
if [[ "$ACTUAL_PYTHON_SHA256" != "$PYTHON_ARCHIVE_SHA256" ]]; then
  echo "Bundled Python runtime checksum mismatch" >&2
  exit 1
fi

rm -rf "$RESOURCE_DIR"
mkdir -p "$RESOURCE_DIR" "$CACHE_DIR"
tar -xzf "$PYTHON_ARCHIVE_PATH" -C "$RESOURCE_DIR"
PYTHON_BIN="$RESOURCE_DIR/python/bin/python"
if [[ "$PYTHON_PLATFORM" == "windows-x86_64" ]]; then
  PYTHON_BIN="$RESOURCE_DIR/python/python.exe"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Bundled Python executable is missing: $PYTHON_BIN" >&2
  exit 1
fi

BACKEND_DIR="$RESOURCE_DIR/senza-studio-backend"
mkdir -p "$BACKEND_DIR"
PYTHONNOUSERSITE=1 "$PYTHON_BIN" -m pip install \
  --no-cache-dir \
  --ignore-installed \
  --no-compile \
  --only-binary=:all: \
  --require-hashes \
  --target "$BACKEND_DIR" \
  --requirement "$ROOT/packaging/desktop-python.lock"
copy_python_tree "$ROOT/studio_backend" "$BACKEND_DIR/studio_backend"
copy_python_tree "$ROOT/senza-studio-runtime/senza_studio_runtime" "$BACKEND_DIR/senza_studio_runtime"
copy_python_tree "$ROOT/senza-studio-components/senza_studio_components" "$BACKEND_DIR/senza_studio_components"
cp "$ROOT/senza-sdk.lock" "$BACKEND_DIR/senza-sdk.lock"
cp "$ROOT/packaging/python-runtime.json" "$RESOURCE_DIR/python-runtime.json"

if [[ "$PYTHON_PLATFORM" == "windows-x86_64" ]]; then
  cp "$AGENT_TEAM_BIN" "$RESOURCE_DIR/agent-studio.exe"
else
  cp "$AGENT_TEAM_BIN" "$RESOURCE_DIR/agent-studio"
  chmod 0755 "$RESOURCE_DIR/agent-studio"
fi

mkdir -p "$RESOURCE_DIR/studio_frontend"
cp -a "$ROOT/studio_frontend/dist" "$RESOURCE_DIR/studio_frontend/dist"
find "$RESOURCE_DIR" -depth -type d -name '__pycache__' -exec rm -rf -- {} +
find "$RESOURCE_DIR" -type f -name '*.pyc' -delete
SENZA_SDK_VERSION="$(sed -n 's/^senza-sdk==\([^[:space:]]*\).*/\1/p' "$ROOT/packaging/desktop-python.lock" | head -1)"
node "$ROOT/studio_frontend/electron/resource-manifest.cjs" \
  "$RESOURCE_DIR" \
  "$ACTUAL_PYTHON_SHA256" \
  "$SENZA_SDK_VERSION" \
  "$AGENT_TEAM_BIN"

cd "$ROOT/studio_frontend"
ELECTRON_CACHE="${ELECTRON_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/electron}"
export ELECTRON_CACHE
if [[ "$TARGET" == "win" ]]; then
  export SENZA_STUDIO_UPDATE_RESOURCE_MANIFEST=1
fi
npx electron-builder "${BUILDER_ARGS[@]}"

for artifact in "$ROOT"/dist/desktop/*; do
  [[ -f "$artifact" ]] || continue
  case "$(basename "$artifact")" in
    *.exe|*.AppImage|*.dmg)
      printf '%s  %s\n' "$(file_sha256 "$artifact")" "$(basename "$artifact")" \
        > "$artifact.sha256"
      ;;
  esac
done

if [[ "$TARGET" == "win" ]]; then
  installer="$(find "$ROOT/dist/desktop" -maxdepth 1 -type f -name 'senza-studio-*-win-x64.exe' -print -quit)"
  if [[ -z "$installer" ]]; then
    echo "Windows NSIS installer was not created" >&2
    exit 1
  fi
  powershell.exe -NoProfile -ExecutionPolicy Bypass \
    -File "$ROOT/scripts/verify-windows-artifact.ps1" \
    -ArtifactPath "$installer" \
    -ExpectedThumbprint "${SENZA_STUDIO_WINDOWS_CERTIFICATE_THUMBPRINT:-}"
fi

echo "Desktop artifacts:"
find "$ROOT/dist/desktop" -maxdepth 1 -type f -print
