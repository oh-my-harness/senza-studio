// studio_frontend/src/components/ControlBar.tsx
import { useStudioStore } from "../store";

export default function ControlBar() {
  const ws = useStudioStore((s) => s.ws);
  const status = useStudioStore((s) => s.status);
  const resetPlay = useStudioStore((s) => s.resetPlay);
  const setStatus = useStudioStore((s) => s.setStatus);

  const playing = status === "playing";

  const play = () => {
    if (!ws || playing) return;
    resetPlay();
    setStatus("playing");
    ws.send(JSON.stringify({ type: "play" }));
  };

  const stop = () => {
    if (!ws || !playing) return;
    ws.send(JSON.stringify({ type: "stop" }));
  };

  return (
    <div className="flex items-center gap-2 px-4 py-2 border-b border-gray-200 bg-gray-50">
      <button
        onClick={play}
        disabled={playing}
        className="rounded-lg bg-green-500 px-4 py-1.5 text-sm text-white hover:bg-green-600 disabled:opacity-50"
      >
        ▶ Play
      </button>
      <button
        onClick={stop}
        disabled={!playing}
        className="rounded-lg bg-red-500 px-4 py-1.5 text-sm text-white hover:bg-red-600 disabled:opacity-50"
      >
        ■ Stop
      </button>
      {playing && <span className="text-xs text-gray-500 ml-2">运行中…</span>}
    </div>
  );
}
