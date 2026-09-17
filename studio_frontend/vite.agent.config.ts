// 导出 Agent 界面的构建（studio_frontend/agent/）。
//
// 单独一个 config 而不是往主构建里加第二个入口：两边要打进完全不同的东西。
// 主构建带 reactflow、zustand store、Inspector/Canvas；这边一个都不能有——
// 交付给最终用户的产物里不该存在编辑器的代码。分成两次 build，产物目录也
// 分开（dist/ 和 dist-agent/），谁也污染不了谁。
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const here = fileURLToPath(new URL(".", import.meta.url));
const backendPort = process.env.SENZA_AGENT_PORT || 8000;

export default defineConfig({
  root: fileURLToPath(new URL("./agent", import.meta.url)),
  plugins: [react()],
  // root 换成了 agent/，postcss/tailwind 的配置还在 studio_frontend/ 下，
  // 不指明的话找不到，打出来的页面没有任何样式。
  css: { postcss: here },
  build: {
    outDir: fileURLToPath(new URL("./dist-agent", import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    port: 5174,
    proxy: {
      "/api": `http://127.0.0.1:${backendPort}`,
      "/ws": { target: `ws://127.0.0.1:${backendPort}`, ws: true },
    },
  },
});
