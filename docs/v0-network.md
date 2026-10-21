# V0 网络、代理及公司 CA

这是按需调整项。先使用本组织正常网络配置；不要求所有人使用维护者的代理端口、域名或 CA。
运行 Runtime 的 WSL 终端、tmux 或服务环境决定 Rust 模型请求走向，Windows 浏览器的代理不是其配置源。
Windows 的 `setx`、Windows CA 安装也不会自动配置已经运行的 WSL 进程。

## Studio 后端的 Provider 网络包装器

Studio 的开发启动脚本 `dev.sh` 在启动 Python 后端前，会先经
`scripts/provider-network.py` 包装，把配置名单内的直连域名追加进后端子进程的
`NO_PROXY` / `no_proxy`，使后端内的模型请求（经 Senza SDK 的 reqwest）绕过代理直连。

### 两份独立配置，不自动同步

| 使用方 | 配置文件 | 包装脚本 |
|---|---|---|
| Studio（本仓库） | `~/.senza-studio/provider-network.json` | `senza-studio/scripts/provider-network.py` |
| Agent Team Runtime | `~/.harness/agent-team-studio/provider-network.json` | `llm-harness-runtime/scripts/provider-network.py` |

两份脚本语义一致，但**各自读取各自的文件**：改一边不会影响另一边，两个组件要分别配置。
Runtime 侧入口见 llm-harness-runtime 仓库 `docs/provider-network.md`。

### 文件格式

```json
{"version":1,"no_proxy":["api.hyper-op.com"]}
```

- `version` 必须是 `1`；`no_proxy` 是普通主机名列表（不允许 URL、端口、通配符）。
- `api.hyper-op.com` 只是当前环境的**示例**，换成你自己的 Provider 域名；
  不是所有人都要写这一条。必须经代理的 Provider 不要加进名单。
- 文件必须显式创建；**不创建该文件时包装器完整继承当前代理环境**，行为与
  没有包装器时一致。

### 相关环境变量

| 变量 | 作用 |
|---|---|
| `SENZA_STUDIO_DATA_ROOT` | 覆盖 Studio 包装器读取配置的目录（默认 `~/.senza-studio`）。仅影响本包装器。 |
| `SENZA_STUDIO_HOME` | **不**控制包装器的配置位置；它只决定 Studio 的项目/会话数据目录。 |
| `STUDIO_NO_PROXY_APPEND` | 临时覆盖：逗号分隔域名，优先于配置文件；**显式空值**表示忽略文件、完整继承原环境。 |

### 生效时机与失败行为

- 配置只在**启动后端时**应用一次（reqwest 在构造时快照代理环境，运行中修改无效）。
  `dev.sh` 每次启动后端都会重新读取；改了文件后需经 `dev.sh` 重新启动后端。
- 配置文件**非法**（坏 JSON、版本不是 1、含 URL/端口/通配符、超过 128 条等）时，
  包装器拒绝启动后端并以退出码 2 退出，不打印配置内容。
- 已有条目保留、顺序不变、大小写与尾点去重；代理变量与凭据环境变量原样透传。

### 验证配置（不发起模型请求）

```bash
python3 scripts/provider-network.py --check
```

`--check` 只解析并打印策略来源与条目数，不执行 `--` 后的命令，不发任何网络请求。
输出示例：`provider network policy: persistent file; 1 explicit exclusions; startup-only`。

## 本次恢复事实（2026-10-19）

同一合成流式请求经本机 `127.0.0.1:7890` 代理返回 502、0 字节正文、无所检查的请求标识；
直连返回 200。随后一次绕过验证观察到到目标解析 IP 的网络连接、未观察到代理 7890 网络连接，且 HTTP 200。
当前本机原生适配器使用 reqwest 0.12.28 的默认 ClientBuilder，支持环境代理和 NO_PROXY；没有在客户端强制指定代理。
这支持本次绕过措施，不证明所有 502 同源，也不代表当前任务/所有网络路径已验收。

本机实际恢复是：tmux 的 Runtime 启动改用本地一次性的启动封装脚本（位于未提交的诊断目录），
向已有 `NO_PROXY`、`no_proxy` 分别追加 `api.hyper-op.com`，保留 HTTP(S)_PROXY 和既有条目。
原值为 `localhost,127.0.0.1,::1`。诊断的 bypass-verification.json 记录 HTTP 200 及直连网络连接。
该脚本已落盘，**只有再次通过它启动才会重复应用**；未修改全局终端配置、系统服务或仓库启动脚本，
也没有证明 tmux/Windows 重启会自动重建该启动命令。重新手动执行原 `cargo run` 不保证保留绕过。
证据与个人绝对路径只是本机恢复记录，不是同事安装的输入依赖。
本次审查可读取保存的验证记录和启动脚本；当前执行环境无法读取记录中 PID 的 `/proc` 环境，
因此未额外声称已独立重验当前业务进程的继承值，更未做重启试验。

## 选择自己的配置

本地连接描述文件、Studio HTTP/WS 必须能访问本机回环地址。需要代理时，在启动 Runtime 和 Studio 的环境中配置
`HTTP_PROXY`、`HTTPS_PROXY`（可能还包括 `ALL_PROXY`）及小写变体，值使用自己的可达代理地址。
WSL 中 `127.0.0.1` 指向当前网络环境，不能假定 Windows 代理必定在那里监听；先确认代理的监听地址、
WSL 网络模式及可达性。已有大小写冲突要消除；reqwest 的 NO_PROXY 优先于 no_proxy，两个应包含相同必要例外。

仅当组织允许且证据表明目标应该直连时，在**两终端启动前**按如下方式追加必要条目：

```bash
append_no_proxy() {
  case ",${NO_PROXY-}," in
    *,"$1",*) ;; *) export NO_PROXY="${NO_PROXY:+${NO_PROXY},}$1" ;;
  esac
  case ",${no_proxy-}," in
    *,"$1",*) ;; *) export no_proxy="${no_proxy:+${no_proxy},}$1" ;;
  esac
}
append_no_proxy localhost
append_no_proxy 127.0.0.1
append_no_proxy ::1
# 仅本次同类、已确认允许直连的网络场景才需要：
# append_no_proxy api.hyper-op.com
```

如需跨启动保留，把该段放进自己受控的启动封装脚本（放在 Runtime `cargo run` 之前），每次从它启动；
Studio 终端同样加载所需网络设置。不要把个人域名绕过写进项目所有人的必选启动脚本。
tmux、服务端或桌面宿主的旧环境不会自动刷新；改完等待所有团队空闲，再正常重启相应进程。

检查时只读取必要的环境名，不要完整输出整个 `/proc/<pid>/environ`（里面可能有密钥）。
仅看变量存在不足以证明绕过。可由获准的运维检查实际目标网络连接／代理日志，并发一次小请求验证 HTTP 结果。
`curl` 的代理/直连对照只能验证 curl 路径，最终仍需 Runtime 的一次最小任务。
不要为了排错全局关代理、改变工具选择逻辑、反复提交正在运行的任务。

## 公司 CA（只针对 TLS 证书失败）

向 IT 获取组织签发、可信的 PEM CA 文件。在 Ubuntu/WSL 内按组织流程安装，例如：

```bash
# 将占位路径换成 IT 提供的真实 CA 文件；不是项目自带文件。
sudo install -m 0644 /path/to/company-ca.crt /usr/local/share/ca-certificates/company-ca.crt
sudo update-ca-certificates
```

Runtime 工作区 启用了 `rustls-tls-native-roots`，会读取其运行操作系统信任根。
Windows 系统信任与 WSL 的 Linux 信任库分别维护。必要时在启动环境显式指定包含公共及公司根的证书集合：

```bash
export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
# 以下仅对应工具仍有证书问题时按需设置：
export UV_NATIVE_TLS=true
export PIP_CERT="$SSL_CERT_FILE"
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
export NODE_EXTRA_CA_CERTS=/path/to/company-ca.crt
export npm_config_cafile="$SSL_CERT_FILE"
export CARGO_HTTP_CAINFO="$SSL_CERT_FILE"
export GIT_SSL_CAINFO="$SSL_CERT_FILE"
```

`SSL_CERT_FILE` 会影响 rustls-native-certs 的加载路径，不要指向不存在的旧本机文件或只含不完整根的证书集合。
Python/npm/Cargo/Git 各有自己的 TLS 配置；只设置 REQUESTS_CA_BUNDLE 不会配置 Rust 适配器。
适配器单独构建的默认特性仅为 rustls 公共信任根，不应把 Runtime 的系统信任根行为推广到所有适配器消费者。
TLS CA 配置不能解释明文 HTTP 端点返回的 502。不要用关闭 TLS 校验代替正确安装 CA。

本次没有在新 Windows/WSL 上安装 CA 或重启系统验证上述持久化；按需调整后应重新验证所用工具和最小任务。
