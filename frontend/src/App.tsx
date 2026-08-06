import { useEffect } from 'react';
import { useProjectStore } from './store/projectStore';
import { useLiveRunBridge } from './hooks/useLiveRunBridge';
import { TopBar } from './components/layout/TopBar';
import { ProjectList } from './components/layout/ProjectList';
import { FileTree } from './components/layout/FileTree';
import { StatusBar } from './components/layout/StatusBar';
import { RightPanel } from './components/layout/RightPanel';
import { ConverseTab } from './components/converse/ConverseTab';
import { RunTab } from './components/run/RunTab';
import { CodeTab } from './components/code/CodeTab';
import { DagTab } from './components/dag/DagTab';
import { TraceTab } from './components/trace/TraceTab';
import { Panel, PanelGroup, PanelResizeHandle } from 'react-resizable-panels';

export default function App() {
  const activeTab = useProjectStore((s) => s.activeTab);
  const project = useProjectStore((s) => s.project);
  const loadSpec = useProjectStore((s) => s.loadSpec);
  useLiveRunBridge();

  useEffect(() => {
    if (project) loadSpec();
  }, [project, loadSpec]);

  return (
    <div className="flex flex-col h-screen bg-background text-foreground">
      <TopBar />
      <PanelGroup direction="horizontal" className="flex-1 min-h-0">
        <Panel defaultSize={15} minSize={10} maxSize={25} className="min-h-0">
          <div className="flex h-full flex-col">
            <ProjectList />
            <div className="min-h-0 flex-1 overflow-y-auto">
              <FileTree />
            </div>
          </div>
        </Panel>
        <PanelResizeHandle className="w-px bg-border" />
        <Panel defaultSize={65} minSize={30} className="min-h-0">
          {activeTab === 'converse' && <ConverseTab />}
          {activeTab === 'run' && <RunTab />}
          {activeTab === 'code' && <CodeTab />}
          {activeTab === 'dag' && <DagTab />}
          {activeTab === 'trace' && <TraceTab />}
        </Panel>
        <PanelResizeHandle className="w-px bg-border" />
        <Panel defaultSize={20} minSize={12} maxSize={35} className="min-h-0">
          <RightPanel />
        </Panel>
      </PanelGroup>
      <StatusBar />
    </div>
  );
}
