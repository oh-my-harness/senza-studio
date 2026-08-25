// studio_frontend/src/components/Canvas.tsx
import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  type Node,
  type Edge,
  Position,
} from "reactflow";
import { useStudioStore } from "../store";
import type { Step } from "../types";

const TYPE_COLORS: Record<string, string> = {
  agent: "#3b82f6",
  checker: "#f59e0b",
  tool: "#10b981",
  terminal: "#6b7280",
};

export default function Canvas() {
  const spec = useStudioStore((s) => s.spec);
  const selectStep = useStudioStore((s) => s.selectStep);
  const selectedStep = useStudioStore((s) => s.selectedStep);

  const { nodes, edges } = useMemo(() => {
    const stages = spec.stages || [];

    // 简单布局：垂直排列
    const nodes: Node[] = stages.map((step, i) => ({
      id: step.name,
      data: {
        label: (
          <div className="text-center">
            <div className="font-medium text-sm">{step.name}</div>
            <div className="text-xs text-gray-500">{step.type}</div>
          </div>
        ),
      },
      position: { x: 250, y: i * 120 },
      style: {
        border: `2px solid ${TYPE_COLORS[step.type] || "#ccc"}`,
        borderRadius: "8px",
        padding: "8px 16px",
        background: selectedStep?.name === step.name ? "#eff6ff" : "#fff",
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
    }));

    // 从 next_on_* 字段提取边
    const edges: Edge[] = [];
    for (const step of stages) {
      for (const [key, val] of Object.entries(step)) {
        if (key.startsWith("next_on_") && typeof val === "string") {
          const condition = key.replace("next_on_", "");
          edges.push({
            id: `${step.name}-${condition}-${val}`,
            source: step.name,
            target: val,
            label: condition,
            type: "smoothstep",
            animated: true,
          });
        }
      }
    }

    return { nodes, edges };
  }, [spec, selectedStep]);

  return (
    <div className="flex-1 h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        onNodeClick={(_, node) => {
          const step = spec.stages.find((s) => s.name === node.id);
          if (step) selectStep(step as Step);
        }}
      >
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
