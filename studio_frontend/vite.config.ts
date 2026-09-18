import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const backendPort = process.env.SENZA_STUDIO_PORT || 7878;

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": `http://127.0.0.1:${backendPort}`,
      // /auth 不在 /api 底下，必须单独代理。前端是用相对路径 fetch
      // ("/auth/bootstrap") 换会话 cookie 的（api.ts），不代理的话这个请求会落到
      // vite 自己身上、返回 404，然后 ensureAuthenticated() 永久失败，后面每一个
      // API 调用都拿不到 cookie——表现就是"项目列表空了、点什么都没反应、设置里
      // 报 authentication failed: 404"。
      //
      // 打包后的桌面版不会踩到：Electron 直接把 cookie 写进 session 并从后端
      // origin 加载 UI，构建产物里 import.meta.env.DEV 是 false，压根不会去调
      // /auth/bootstrap。所以只有 ./dev.sh 这条浏览器开发链路会坏，桌面端 E2E
      // 和后端测试都照常绿。
      "/auth": `http://127.0.0.1:${backendPort}`,
      "/ws": {
        target: `ws://127.0.0.1:${backendPort}`,
        ws: true,
      },
    },
  },
});
