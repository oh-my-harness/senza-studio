import { useProjectStore } from '../../store/projectStore';
import { ReactFlow, Background, Controls, type Node, type Edge } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { useMemo } from 'react';

export function DagTab() {
  const currentSpec = useProjectStore((s) => s.currentSpec);
  const stepStates = useProjectStore((s) => s.stepStates);

  const { nodes, edges } = useMemo(() => {
    if (!currentSpec?.workflow) return { nodes: [] as Node[], edges: [] as Edge[] };

    const wf = currentSpec.workflow;
    const nodes: Node[] = wf.steps.map((step, i) => {
      const state = stepStates[step.id];
      const status = state?.status || 'pending';
      return {
        id: step.id,
        position: { x: (i % 3) * 250, y: Math.floor(i / 3) * 150 },
        data: { label: `${step.name}\n${status}` },
        style: {
          background: status === 'done' ? '#dcfce7' : status === 'running' ? '#fef9c3' : status === 'failed' ? '#fee2e2' : '#fff',
        },
      };
    });

    const edges: Edge[] = wf.edges.map((e, i) => ({
      id: `edge-${i}`,
      source: e.from,
      target: e.to,
      label: e.condition ? `${e.condition.op} ${e.condition.pointer} ${JSON.stringify(e.condition.value)}` : undefined,
    }));

    return { nodes, edges };
  }, [currentSpec, stepStates]);

  if (!currentSpec?.workflow) {
    return <div className="flex items-center justify-center h-full text-muted-foreground">No workflow (single agent project)</div>;
  }

  return (
    <div className="h-full">
      <ReactFlow nodes={nodes} edges={edges}>
        <Background />
        <Controls />
      </ReactFlow>
    </div>
  );
}
