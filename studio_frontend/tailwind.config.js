export default {
  content: [
    "./index.html",
    "./src/**/*.{ts,tsx}",
    // 导出 Agent 界面是另一个构建，但共用这份 tailwind 配置
    "./agent/**/*.{html,ts,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};
