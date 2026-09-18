// studio_frontend/src/player/PlayerShell.tsx —— 所有 layout 的外壳。
//
// 主题（CSS 变量）、页头、全局提示条都在这里，所以新加一种 layout 只用写它
// 自己的正文，配色、明暗、密度、错误提示自动就是对的。
import { themeStyle } from "./theme";
import type { AgentInfo } from "./types";

export default function PlayerShell({
  info,
  connected,
  compact,
  actions,
  children,
}: {
  info: AgentInfo;
  connected: boolean;
  compact: boolean;
  /** 页头右侧的东西（看板布局把"运行"按钮放这儿） */
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div
      className="h-full overflow-y-auto bg-[var(--bg)] text-[var(--text)]"
      style={themeStyle(info.theme)}
    >
      <header className="border-b border-[var(--border)] bg-[var(--surface)]">
        <div
          className={`mx-auto flex max-w-5xl items-center gap-4 ${
            compact ? "px-4 py-3" : "px-6 py-5"
          }`}
        >
          {info.theme?.logo && (
            // 作者给的是一个 URL 或 data: URI。加载不出来就整个藏掉——一个
            // 裂图标比没有 logo 难看得多。
            <img
              src={info.theme.logo}
              alt=""
              className="h-8 w-auto shrink-0 object-contain"
              onError={(e) => {
                (e.currentTarget as HTMLImageElement).style.display = "none";
              }}
            />
          )}
          <div className="min-w-0 flex-1">
            <h1
              className={`truncate font-semibold ${compact ? "text-base" : "text-lg"}`}
            >
              {info.title}
            </h1>
            {info.description && (
              <p className="mt-1 text-sm text-[var(--text-muted)]">{info.description}</p>
            )}
          </div>
          {actions}
        </div>
      </header>

      <main
        className={`mx-auto max-w-5xl space-y-4 ${compact ? "px-4 py-4" : "p-[var(--pad-page)]"}`}
      >
        {info.error && (
          <div className="rounded-lg border border-[var(--danger-border)] bg-[var(--danger-bg)] px-4 py-3 text-sm text-[var(--danger-text)]">
            这个 agent 没法运行：{info.error}
          </div>
        )}
        {!connected && (
          <div className="rounded-lg border border-[var(--warn-border)] bg-[var(--warn-bg)] px-4 py-3 text-sm text-[var(--warn-text)]">
            与服务的连接已断开，刷新页面重试。
          </div>
        )}
        {children}
      </main>
    </div>
  );
}
