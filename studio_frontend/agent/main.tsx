// studio_frontend/agent/main.tsx —— 导出 Agent 的入口。
//
// 和 src/main.tsx 是**两个独立的构建**：这边打出来的包里没有 reactflow、
// 没有 store、没有 Inspector/Canvas/ControlBar。不是"运行时藏起来"，是根本
// 没打进去——交付给最终用户的产物里不该存在编辑器的代码。
import React from "react";
import ReactDOM from "react-dom/client";
import AgentApp from "./AgentApp";
import "../src/index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AgentApp />
  </React.StrictMode>
);
