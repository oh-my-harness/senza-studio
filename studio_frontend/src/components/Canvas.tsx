// studio_frontend/src/components/Canvas.tsx
import { useMemo } from "react";
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
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

const RUN_STATUS_BG: Record<string, string> = {
  running: "#fef3c7",
  done: "#dcfce7",
  error: "#fee2e2",
};

const H_SPACING = 220;
const V_SPACING = 140;

/** 按 next_on_* 边把 step 分层（每层 = 到根节点的最长路径长度），
 * 同层内的节点水平排开，避免分支被压成一条纵向直线导致边互相重叠。 */
function layoutStages(stages: Step[]): Record<string, { x: number; y: number }> {
  const names = new Set(stages.map((s) => s.name));
  const children: Record<string, Set<string>> = {};
  const parentCount: Record<string, number> = {};
  for (const s of stages) {
    children[s.name] = new Set();
    parentCount[s.name] = 0;
  }
  for (const s of stages) {
    for (const [key, val] of Object.entries(s)) {
      if (key.startsWith("next_on_") && typeof val === "string" && names.has(val)) {
        children[s.name].add(val);
      }
    }
  }
  for (const s of stages) {
    for (const child of children[s.name]) {
      parentCount[child] += 1;
    }
  }

  const rank: Record<string, number> = {};
  const remaining = { ...parentCount };
  let queue = stages.filter((s) => remaining[s.name] === 0).map((s) => s.name);
  if (queue.length === 0 && stages.length > 0) queue = [stages[0].name];
  for (const name of queue) rank[name] = 0;

  const visited = new Set(queue);
  while (queue.length > 0) {
    const next: string[] = [];
    for (const cur of queue) {
      for (const child of children[cur]) {
        rank[child] = Math.max(rank[child] ?? 0, rank[cur] + 1);
        remaining[child] -= 1;
        if (remaining[child] <= 0 && !visited.has(child)) {
          visited.add(child);
          next.push(child);
        }
      }
    }
    queue = next;
  }
  // 环 / 孤立节点兜底：排在已知层级之后，保证仍能渲染
  let maxRank = Math.max(0, ...Object.values(rank));
  for (const s of stages) {
    if (!(s.name in rank)) {
      maxRank += 1;
      rank[s.name] = maxRank;
    }
  }

  const byRank: Record<number, string[]> = {};
  for (const s of stages) {
    (byRank[rank[s.name]] ||= []).push(s.name);
  }

  const positions: Record<string, { x: number; y: number }> = {};
  for (const [rankStr, rankNames] of Object.entries(byRank)) {
    const r = Number(rankStr);
    const width = rankNames.length * H_SPACING;
    rankNames.forEach((name, i) => {
      positions[name] = {
        x: i * H_SPACING - width / 2 + H_SPACING / 2,
        y: r * V_SPACING,
      };
    });
  }
  return positions;
}

export default function Canvas() {
  const spec = useStudioStore((s) => s.spec);
  const selectStep = useStudioStore((s) => s.selectStep);
  const selectedStep = useStudioStore((s) => s.selectedStep);
  const stepStatus = useStudioStore((s) => s.stepStatus);

  const { nodes, edges } = useMemo(() => {
    const stages = spec.stages || [];
    const positions = layoutStages(stages);

    const nodes: Node[] = stages.map((step) => ({
      id: step.name,
      data: {
        label: (
          <div className="text-center">
            <div className="font-medium text-sm">{step.name}</div>
            <div className="text-xs text-gray-500">{step.type}</div>
          </div>
        ),
      },
      position: positions[step.name],
      style: {
        border: `2px solid ${TYPE_COLORS[step.type] || "#ccc"}`,
        borderRadius: "8px",
        padding: "8px 16px",
        background:
          RUN_STATUS_BG[stepStatus[step.name]] ??
          (selectedStep?.name === step.name ? "#eff6ff" : "#fff"),
      },
      sourcePosition: Position.Bottom,
      targetPosition: Position.Top,
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
            markerEnd: { type: MarkerType.ArrowClosed },
          });
        }
      }
    }

    return { nodes, edges };
  }, [spec, selectedStep, stepStatus]);

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
