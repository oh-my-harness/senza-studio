import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { useAgentStore } from '../store/agentStore';
import { useAgentRunWs } from '../hooks/useAgentRunWs';
import { MessageBubble } from '../components/converse/MessageBubble';
import { Play, Square, Send, Terminal, ArrowLeft } from 'lucide-react';

export function AgentWindow() {
  const { projectId } = useParams<{ projectId: string }>();
  const setProjectId = useAgentStore((s) => s.setProjectId);
  const runStatus = useAgentStore((s) => s.runStatus);
  const runView = useAgentStore((s) => s.runView);
  const runMessages = useAgentStore((s) => s.runMessages);
  const stepStates = useAgentStore((s) => s.stepStates);
  const activeStepId = useAgentStore((s) => s.activeStepId);
  const startRun = useAgentStore((s) => s.startRun);
  const stopRun = useAgentStore((s) => s.stopRun);
  const sendRunMessage = useAgentStore((s) => s.sendRunMessage);
  const submitTask = useAgentStore((s) => s.submitTask);
  const { sendInput } = useAgentRunWs();
  const [input, setInput] = useState('');

  useEffect(() => {
    if (projectId) setProjectId(projectId);
  }, [projectId, setProjectId]);

  const handleSubmit = () => {
    if (!input.trim()) return;
    if (runView === 'chat') {
      sendRunMessage(input);
    } else {
      submitTask(input);
    }
    sendInput(input);
    setInput('');
  };

  const steps = Object.entries(stepStates);

  return (
    <div className="flex flex-col h-screen bg-background text-foreground">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-2 border-b bg-background shrink-0">
        <button
          onClick={() => window.close()}
          className="text-sm flex items-center gap-1 hover:bg-accent px-2 py-1 rounded"
        >
          <ArrowLeft size={16} /> Close
        </button>
        <span className="font-semibold">Agent Runtime</span>
        <span className="text-xs text-muted-foreground">Project: {projectId}</span>
        <div className="flex-1" />
        {runStatus === 'running' || runStatus === 'waiting_input' ? (
          <button
            onClick={() => stopRun()}
            className="px-3 py-1 text-sm bg-destructive text-destructive-foreground rounded flex items-center gap-1"
          >
            <Square size={16} /> Stop
          </button>
        ) : (
          <button
            onClick={() => startRun('studio')}
            className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded flex items-center gap-1"
          >
            <Play size={16} /> Start
          </button>
        )}
        <span className={`text-xs px-2 py-1 rounded ${
          runStatus === 'running' ? 'bg-blue-100 text-blue-700' :
          runStatus === 'waiting_input' ? 'bg-yellow-100 text-yellow-700' :
          runStatus === 'completed' ? 'bg-green-100 text-green-700' :
          runStatus === 'failed' ? 'bg-red-100 text-red-700' :
          'bg-muted text-muted-foreground'
        }`}>
          {runStatus}
        </span>
      </div>

      {/* Body */}
      {runStatus === 'idle' ? (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <Terminal size={48} className="mx-auto text-muted-foreground mb-4" />
            <p className="text-muted-foreground mb-4">Agent not running</p>
            <button
              onClick={() => startRun('studio')}
              className="px-4 py-2 bg-primary text-primary-foreground rounded flex items-center gap-2 mx-auto"
            >
              <Play size={16} /> Start Agent
            </button>
          </div>
        </div>
      ) : runView === 'chat' ? (
        /* Chat view — single agent */
        <>
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-2 min-h-0">
            {runMessages.map((msg, i) => (
              <MessageBubble key={i} role={msg.role} content={msg.content} thinking={msg.thinking} />
            ))}
          </div>
          <div className="shrink-0 border-t p-3 flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              placeholder="Type a message…"
              className="flex-1 px-3 py-2 bg-[var(--input)] border rounded-lg text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              disabled={runStatus !== 'waiting_input' && runStatus !== 'running'}
            />
            <button
              onClick={handleSubmit}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm flex items-center gap-1"
            >
              <Send size={16} /> Send
            </button>
          </div>
        </>
      ) : (
        /* Execution view — workflow */
        <div className="flex flex-col flex-1 overflow-hidden">
          <div className="p-3 border-b">
            <div className="flex items-center gap-2 flex-wrap">
              {steps.map(([stepId, state], i) => (
                <div key={stepId} className="flex items-center gap-2">
                  {i > 0 && <span className="text-muted-foreground">→</span>}
                  <div className={`px-3 py-1 rounded border ${
                    state.status === 'done' ? 'bg-green-100 border-green-500' :
                    state.status === 'running' ? 'bg-yellow-100 border-yellow-500 animate-pulse' :
                    state.status === 'failed' ? 'bg-red-100 border-red-500' :
                    'bg-background'
                  }`}>
                    <div className="text-sm font-medium">{stepId}</div>
                    <div className="text-xs text-muted-foreground">{state.status}</div>
                  </div>
                </div>
              ))}
              {steps.length === 0 && <span className="text-sm text-muted-foreground">Submit a task to start</span>}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <div className="text-xs text-muted-foreground mb-2">
              {activeStepId ? `Step: ${activeStepId}` : 'Output'}
            </div>
            {runMessages
              .filter((m) => m.role === 'assistant')
              .slice(-1)
              .map((msg, i) => (
                <pre key={i} className="text-sm whitespace-pre-wrap">{msg.content}</pre>
              ))}
          </div>
          <div className="shrink-0 border-t p-3 flex gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSubmit()}
              placeholder="Submit task..."
              className="flex-1 px-3 py-2 bg-[var(--input)] border rounded-lg text-sm"
              disabled={runStatus === 'running'}
            />
            <button
              onClick={handleSubmit}
              disabled={runStatus === 'running'}
              className="px-4 py-2 bg-primary text-primary-foreground rounded-lg text-sm flex items-center gap-1 disabled:opacity-50"
            >
              <Send size={16} /> Submit
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
