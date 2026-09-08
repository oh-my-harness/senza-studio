// studio_frontend/src/components/Canvas.tsx
import { useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  Background,
  Controls,
  MarkerType,
  type Node,
  type Edge,
  type ReactFlowInstance,
  Position,
} from "reactflow";
import { useStudioStore } from "../store";
import { api } from "../api";
import type { Spec, Step } from "../types";

const TYPE_COLORS: Record<string, string> = {
  agent: "#3b82f6",
  checker: "#f59e0b",
  tool: "#10b981",
  terminal: "#6b7280",
};

const COMPONENT_COLOR = "#8b5cf6";

const RUN_STATUS_BG: Record<string, string> = {
  running: "#fef3c7",
  done: "#dcfce7",
  error: "#fee2e2",
};

const H_SPACING = 220;
const V_SPACING = 140;

// 展开后的组件容器尺寸——内部 step 竖着排（一个组件通常就 1~3 步）。
// 所有尺寸都配合 boxSizing: "border-box"：React Flow 默认节点自带
// padding/border，不统一盒模型的话子节点会比容器还宽，直接溢出到框外
// （实测截图里就是这样）。
const GROUP_WIDTH = 230;
const GROUP_HEADER = 46; // 两行表头：实例名 + 组件名
const CHILD_HEIGHT = 46;
const CHILD_GAP = 12;
const GROUP_PADDING = 12;
const PLAIN_NODE_HEIGHT = 60;
// 普通节点宽度是 max-content，这里取个代表值用于居中——差几十像素不影响
// 可读性，重要的是组件容器和普通节点用同一套居中规则。
const PLAIN_NODE_WIDTH = 120;

function groupHeight(childCount: number): number {
  return (
    GROUP_HEADER + childCount * (CHILD_HEIGHT + CHILD_GAP) + GROUP_PADDING
  );
}

// 布局只认 name + next_on_* 两件事。单独定义而不是复用 Step：折叠后的
// 组件项不是真正的 step（它没有 StepType，只是画布上的一个占位），硬塞进
// Step 类型只能靠放宽 StepType，那会让真正的 spec 校验也跟着松掉。
type LayoutItem = { name: string; [key: string]: unknown };

/** 按 next_on_* 边把 step 分层（每层 = 到根节点的最长路径长度），
 * 同层内的节点水平排开，避免分支被压成一条纵向直线导致边互相重叠。 */
function layoutStages(
  stages: LayoutItem[],
  heightOf: (name: string) => number = () => PLAIN_NODE_HEIGHT,
  widthOf: (name: string) => number = () => PLAIN_NODE_WIDTH,
): Record<string, { x: number; y: number }> {
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

  // 纵向按每层实际高度累加，而不是固定 V_SPACING：展开的组件容器有两三
  // 个 step 那么高，固定间距会让它直接压到下一层的节点上（实测截图里
  // 组件框和 terminal 节点重叠了）。
  const positions: Record<string, { x: number; y: number }> = {};
  const ranks = Object.keys(byRank)
    .map(Number)
    .sort((a, b) => a - b);
  let y = 0;
  for (const r of ranks) {
    const rankNames = byRank[r];
    const width = rankNames.length * H_SPACING;
    rankNames.forEach((name, i) => {
      // 节点坐标是左上角，所以要按各自宽度居中到槽位中心，不能所有节点
      // 共用一个左边界——展开后的组件容器比普通节点宽一倍多，共用左边界
      // 会让它整个偏到右边去（实测截图里组件框贴着右边缘）。
      const slotCenter = i * H_SPACING - width / 2 + H_SPACING / 2;
      positions[name] = { x: slotCenter - widthOf(name) / 2, y };
    });
    const tallest = Math.max(...rankNames.map(heightOf));
    y += tallest + (V_SPACING - PLAIN_NODE_HEIGHT);
  }
  return positions;
}

/** 展开后的 step 名 -> 它属于哪个组件实例。普通 step 不在表里。 */
function ownerMap(stages: Step[]): Record<string, string> {
  const owner: Record<string, string> = {};
  for (const stage of stages) {
    const instance = stage["_component_instance"];
    if (typeof instance === "string") owner[stage.name] = instance;
  }
  return owner;
}

export default function Canvas({ projectId }: { projectId: string }) {
  const spec = useStudioStore((s) => s.spec);
  const selectStep = useStudioStore((s) => s.selectStep);
  const selectedStepName = useStudioStore((s) => s.selectedStepName);
  const stepStatus = useStudioStore((s) => s.stepStatus);
  const runtimeSpec = useStudioStore((s) => s.runtimeSpec);

  const [fetchedSpec, setFetchedSpec] = useState<Spec | null>(null);
  const [expandError, setExpandError] = useState<string | null>(null);
  // 哪些组件实例当前是展开的（默认全部折叠——组件的意义就是把细节收起来）
  const [openInstances, setOpenInstances] = useState<Set<string>>(new Set());
  const flowRef = useRef<ReactFlowInstance | null>(null);
  const firstRender = useRef(true);

  const hasComponents = (spec.stages || []).some(
    (s) => typeof s["component"] === "string",
  );

  // 编辑态也要能展开组件看内部 step，所以不能只靠 Play 时下发的 runtimeSpec
  // ——编辑的时候根本没在跑。有 runtimeSpec 时优先用它，省一次请求，也保证
  // 画布和正在跑的那份完全一致。
  useEffect(() => {
    if (!hasComponents || runtimeSpec) {
      setFetchedSpec(null);
      setExpandError(null);
      return;
    }
    let cancelled = false;
    api
      .getExpandedSpec(projectId)
      .then((res) => {
        if (cancelled) return;
        setFetchedSpec(res.spec);
        setExpandError(res.error);
      })
      .catch((e) => {
        if (!cancelled) setExpandError(String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, spec, hasComponents, runtimeSpec]);

  // 展开失败就退回编辑态 spec：组件仍然画成一个未展开的引用节点，外加一条
  // 错误提示，而不是整块画布报错——spec 编到一半展不开是常态。
  const graphSpec: Spec = runtimeSpec ?? fetchedSpec ?? spec;

  const { nodes, edges, instanceCounts } = useMemo(() => {
    const stages = graphSpec.stages || [];
    const owner = ownerMap(stages);

    const instanceCounts: Record<string, number> = {};
    const instanceComponent: Record<string, string> = {};
    for (const stage of stages) {
      const instance = owner[stage.name];
      if (!instance) continue;
      instanceCounts[instance] = (instanceCounts[instance] || 0) + 1;
      const componentName = stage["_component"];
      if (typeof componentName === "string") instanceComponent[instance] = componentName;
    }

    const isOpen = (instance: string) => openInstances.has(instance);
    // 一个展开后的 step 在画布上归到哪个节点：折叠时归到组件实例，展开时
    // 就是它自己。
    const displayId = (name: string) => {
      const instance = owner[name];
      return instance && !isOpen(instance) ? instance : name;
    };

    // ── 顶层布局项 ──────────────────────────────────────
    // 组件实例（不论展开与否）在布局里都只占一个位置；展开的实例之后再把
    // 内部 step 摆进容器里。
    const topLevel: LayoutItem[] = [];
    const seenInstance = new Set<string>();
    for (const stage of stages) {
      const instance = owner[stage.name];
      if (!instance) {
        const mapped: LayoutItem = { ...stage };
        for (const [key, val] of Object.entries(stage)) {
          if (key.startsWith("next_on_") && typeof val === "string") {
            mapped[key] = displayId(val);
          }
        }
        topLevel.push(mapped);
        continue;
      }
      if (seenInstance.has(instance)) continue;
      seenInstance.add(instance);
      // 组件对外的出边 = 内部 step 指向组件外部的那些边
      const outward: LayoutItem = { name: instance };
      for (const inner of stages) {
        if (owner[inner.name] !== instance) continue;
        for (const [key, val] of Object.entries(inner)) {
          if (!key.startsWith("next_on_") || typeof val !== "string") continue;
          if (owner[val] === instance) continue; // 组件内部边，不外露
          outward[key] = displayId(val);
        }
      }
      topLevel.push(outward);
    }

    const positions = layoutStages(
      topLevel,
      (name) =>
        seenInstance.has(name) && isOpen(name)
          ? groupHeight(instanceCounts[name] || 0)
          : PLAIN_NODE_HEIGHT,
      (name) =>
        seenInstance.has(name) && isOpen(name) ? GROUP_WIDTH : PLAIN_NODE_WIDTH,
    );

    // ── 节点 ────────────────────────────────────────────
    const nodes: Node[] = [];
    for (const item of topLevel) {
      const instance = seenInstance.has(item.name) ? item.name : null;
      if (instance && isOpen(instance)) {
        // 展开：容器节点（父）必须排在子节点前面，React Flow 要求如此
        const childCount = instanceCounts[instance] || 0;
        nodes.push({
          id: instance,
          data: {
            label: (
              <div className="text-left w-full">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpenInstances((prev) => {
                      const next = new Set(prev);
                      next.delete(instance);
                      return next;
                    });
                  }}
                  className="text-xs font-medium text-violet-700 hover:underline"
                >
                  ▾ {instance}
                </button>
                <div className="text-[10px] text-violet-400 leading-tight">
                  {instanceComponent[instance]}
                </div>
              </div>
            ),
          },
          position: positions[instance],
          style: {
            boxSizing: "border-box",
            width: GROUP_WIDTH,
            height: groupHeight(childCount),
            border: `2px dashed ${COMPONENT_COLOR}`,
            borderRadius: "10px",
            background: "rgba(139,92,246,0.06)",
            padding: "6px 8px",
            fontSize: "12px",
          },
          selectable: false,
        });
        continue;
      }
      if (instance) {
        // 折叠：一个节点代表整个组件
        nodes.push({
          id: instance,
          data: {
            label: (
              <div className="text-center">
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpenInstances((prev) => new Set(prev).add(instance));
                  }}
                  className="font-medium text-sm hover:underline"
                >
                  ▸ {instance}
                </button>
                <div className="text-xs text-violet-500">
                  {instanceComponent[instance]} · {instanceCounts[instance]} 步
                </div>
              </div>
            ),
          },
          position: positions[instance],
          style: {
            border: `2px dashed ${COMPONENT_COLOR}`,
            borderRadius: "8px",
            padding: "8px 16px",
            width: "max-content",
            maxWidth: 200,
            whiteSpace: "normal",
            wordBreak: "break-word",
            background:
              RUN_STATUS_BG[stepStatus[instance]] ??
              (selectedStepName === instance ? "#f5f3ff" : "#fff"),
          },
          sourcePosition: Position.Bottom,
          targetPosition: Position.Top,
        });
        continue;
      }

      const step = item as Step;
      nodes.push({
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
          // width 固定值 + nowrap 会让长 step name 溢出边框；改成按内容
          // 自适应宽度（封顶），超过封顶再换行，而不是简单裁切/溢出。
          width: "max-content",
          maxWidth: 200,
          whiteSpace: "normal",
          wordBreak: "break-word",
          background:
            RUN_STATUS_BG[stepStatus[step.name]] ??
            (selectedStepName === step.name ? "#eff6ff" : "#fff"),
        },
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
      });
    }

    // 展开实例的内部 step——子节点坐标相对父节点
    for (const instance of seenInstance) {
      if (!isOpen(instance)) continue;
      let index = 0;
      for (const stage of stages) {
        if (owner[stage.name] !== instance) continue;
        nodes.push({
          id: stage.name,
          parentId: instance,
          extent: "parent",
          draggable: false,
          data: {
            label: (
              <div className="text-center">
                <div className="text-xs font-medium">{stage.name}</div>
                <div className="text-[10px] text-gray-500">{stage.type}</div>
              </div>
            ),
          },
          position: {
            x: GROUP_PADDING,
            y: GROUP_HEADER + index * (CHILD_HEIGHT + CHILD_GAP),
          },
          style: {
            boxSizing: "border-box",
            width: GROUP_WIDTH - GROUP_PADDING * 2,
            height: CHILD_HEIGHT,
            padding: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: `2px solid ${TYPE_COLORS[stage.type] || "#ccc"}`,
            borderRadius: "6px",
            background: RUN_STATUS_BG[stepStatus[stage.name]] ?? "#fff",
          },
          sourcePosition: Position.Bottom,
          targetPosition: Position.Top,
        });
        index += 1;
      }
    }

    // ── 边 ──────────────────────────────────────────────
    const edges: Edge[] = [];
    const seenEdge = new Set<string>();
    const pushEdge = (source: string, target: string, condition: string) => {
      if (source === target) return; // 折叠后组件内部的边退化成自环，丢掉
      const id = `${source}-${condition}-${target}`;
      if (seenEdge.has(id)) return; // 多个内部 step 指向同一外部目标
      seenEdge.add(id);
      edges.push({
        id,
        source,
        target,
        label: condition,
        type: "smoothstep",
        markerEnd: { type: MarkerType.ArrowClosed },
      });
    };

    for (const stage of stages) {
      const instance = owner[stage.name];
      // 折叠的组件，出边不从展开后的内部 step 上取——那上面挂的是组件内部
      // 的条件名（gate_notify 的 next_on_success），而用户在 spec 里写的是
      // 端口名（next_on_approve）。折叠视图显示 "success" 是在讲组件的内部
      // 实现，跟用户写的对不上（实测截图里 approve 这条线标成了 success）。
      // 改从编辑态 spec 的组件 step 上取，那才是用户写的端口名。
      if (instance && !isOpen(instance)) continue;
      for (const [key, val] of Object.entries(stage)) {
        if (!key.startsWith("next_on_") || typeof val !== "string") continue;
        pushEdge(displayId(stage.name), displayId(val), key.replace("next_on_", ""));
      }
    }

    // 折叠组件的出边：用编辑态 spec 里的端口名
    for (const instance of seenInstance) {
      if (isOpen(instance)) continue;
      const editStage = (spec.stages || []).find((s) => s.name === instance);
      if (!editStage) continue;
      for (const [key, val] of Object.entries(editStage)) {
        if (!key.startsWith("next_on_") || typeof val !== "string") continue;
        pushEdge(instance, displayId(val), key.replace("next_on_", ""));
      }
    }

    return { nodes, edges, instanceCounts };
  }, [graphSpec, spec, selectedStepName, stepStatus, openInstances]);

  // fitView 只在首次挂载时跑一次，展开组件之后图变大了不会自动重新适配
  // ——实测展开后容器有一半在可视区外，看着像画歪了。展开状态变了就重新
  // 适配一次。
  // 挂载时的 fitView 是按折叠后的图算的，展开组件后图变大就装不下了
  // （实测容器有一块在可视区外）。展开/折叠后重新适配一次。
  //
  // 用不带参数的 fitView()——跟 Controls 上那个适配按钮同一套默认值。
  // 试过传 {padding: 0.2, duration: 200}，结果把整张图甩到可视区外，
  // 比不调还糟。延迟一帧是必须的：新加进来的子节点要等 React Flow 量完
  // 尺寸才有宽高，同步调用算出来的 bounding box 是错的。
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return; // 挂载时 ReactFlow 自己的 fitView 已经做过了
    }
    const timer = setTimeout(() => flowRef.current?.fitView(), 80);
    return () => clearTimeout(timer);
  }, [openInstances]);

  const componentCount = Object.keys(instanceCounts).length;
  const allOpen = componentCount > 0 && openInstances.size === componentCount;

  return (
    <div className="flex flex-col h-full w-full">
      <div className="px-4 py-3 border-b border-gray-200 flex items-center gap-3 shrink-0">
        <span className="font-medium text-gray-700">DAG</span>
        {componentCount > 0 && (
          <button
            onClick={() =>
              setOpenInstances(
                allOpen ? new Set() : new Set(Object.keys(instanceCounts)),
              )
            }
            className="text-xs text-violet-600 hover:underline"
          >
            {allOpen ? "全部折叠" : "展开全部组件"}
          </button>
        )}
        {expandError && (
          <span className="text-xs text-red-600 truncate" title={expandError}>
            组件展开失败：{expandError}
          </span>
        )}
      </div>
      <div className="flex-1 min-h-0">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onInit={(instance) => {
            flowRef.current = instance;
          }}
          fitView
          onNodeClick={(_, node) => {
            // 组件生成的 step 在编辑态 spec 里不存在，选中它 Inspector 会
            // 空着——点内部 step 一律选中它所属的组件引用，那才是能编辑的
            // 那一个。
            const owner = ownerMap(graphSpec.stages || []);
            selectStep(owner[node.id] ?? node.id);
          }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}
