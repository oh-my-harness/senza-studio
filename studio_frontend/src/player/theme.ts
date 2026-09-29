// studio_frontend/src/player/theme.ts
//
// 主题 → CSS 变量。所有 layout、所有卡片都只认这些变量，所以换主题不用碰任何
// 一个组件，加一种 layout 也自动就是对的配色。
//
// 用 CSS 变量而不是 Tailwind 的 dark: 前缀：accent 是作者填的任意颜色，
// 编译期的类名表达不了；明暗两套色板也就没必要分两种机制。
import type { CSSProperties } from "react";

export interface AgentTheme {
  accent: string;
  mode: string;
  density: string;
  logo: string;
}

export const FALLBACK_THEME: AgentTheme = {
  accent: "#2563eb",
  mode: "light",
  density: "comfortable",
  logo: "",
};

const LIGHT = {
  "--bg": "#f8fafc",
  "--surface": "#ffffff",
  "--surface-2": "#f1f5f9",
  "--border": "#e2e8f0",
  "--text": "#1e293b",
  "--text-muted": "#64748b",
  "--text-faint": "#94a3b8",
  "--warn-bg": "#fffbeb",
  "--warn-border": "#fcd34d",
  "--warn-text": "#92400e",
  "--danger-bg": "#fef2f2",
  "--danger-border": "#fecaca",
  "--danger-text": "#991b1b",
  "--ok-bg": "#ecfdf5",
  "--ok-border": "#a7f3d0",
};

const DARK = {
  "--bg": "#0f172a",
  "--surface": "#1e293b",
  "--surface-2": "#334155",
  "--border": "#334155",
  "--text": "#e2e8f0",
  "--text-muted": "#94a3b8",
  "--text-faint": "#64748b",
  "--warn-bg": "#422006",
  "--warn-border": "#a16207",
  "--warn-text": "#fde68a",
  "--danger-bg": "#450a0a",
  "--danger-border": "#7f1d1d",
  "--danger-text": "#fecaca",
  "--ok-bg": "#052e16",
  "--ok-border": "#166534",
};

/** accent 上面的文字用黑还是白。作者可能填一个很浅的品牌色（#fbbf24），
 *  永远用白字就会糊成一片看不见。按感知亮度算，不猜。 */
function accentForeground(accent: string): string {
  const hex = accent.trim().replace("#", "");
  const full =
    hex.length === 3
      ? hex
          .split("")
          .map((c) => c + c)
          .join("")
      : hex;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return "#ffffff"; // 认不出来（比如 rgb()）就按深色处理
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
  const lin = (c: number) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
  const luminance = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
  return luminance > 0.5 ? "#111827" : "#ffffff";
}

export function themeStyle(theme: AgentTheme | undefined): CSSProperties {
  const t = { ...FALLBACK_THEME, ...(theme ?? {}) };
  const palette = t.mode === "dark" ? DARK : LIGHT;
  const compact = t.density === "compact";
  return {
    ...palette,
    "--accent": t.accent,
    "--accent-fg": accentForeground(t.accent),
    // 密度只调间距，不调字号——字号一改，作者在 Studio 里对着调的排版就全变了
    "--pad-card": compact ? "0.5rem 0.75rem" : "0.75rem 1rem",
    "--gap": compact ? "0.5rem" : "0.75rem",
    "--pad-page": compact ? "1rem" : "1.5rem",
    colorScheme: t.mode === "dark" ? "dark" : "light",
  } as CSSProperties;
}
