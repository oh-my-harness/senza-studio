import { useState, useEffect } from 'react';
import { useProjectStore } from '../../store/projectStore';

export function CodeTab() {
  const files = useProjectStore((s) => s.files);
  const saveFile = useProjectStore((s) => s.saveFile);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [content, setContent] = useState('');
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    if (selectedFile && files[selectedFile] !== undefined) {
      setContent(files[selectedFile]);
      setDirty(false);
    }
  }, [selectedFile, files]);

  const handleSave = async () => {
    if (!selectedFile) return;
    await saveFile(selectedFile, content);
    setDirty(false);
  };

  return (
    <div className="flex h-full">
      <div className="w-48 border-r overflow-y-auto">
        {Object.keys(files).map((path) => (
          <button
            key={path}
            onClick={() => setSelectedFile(path)}
            className={`block w-full text-left px-3 py-1 text-sm hover:bg-accent ${selectedFile === path ? 'bg-accent' : ''}`}
          >
            {path}
          </button>
        ))}
      </div>
      <div className="flex-1 flex flex-col">
        {selectedFile ? (
          <>
            <div className="flex items-center justify-between border-b px-3 py-1">
              <span className="text-sm">{selectedFile} {dirty && '•'}</span>
              <button onClick={handleSave} disabled={!dirty} className="px-3 py-1 text-sm bg-primary text-primary-foreground rounded disabled:opacity-50">
                Save
              </button>
            </div>
            <textarea
              value={content}
              onChange={(e) => { setContent(e.target.value); setDirty(true); }}
              className="flex-1 p-2 font-mono text-sm bg-background resize-none focus:outline-none"
            />
          </>
        ) : (
          <div className="flex items-center justify-center text-muted-foreground">Select a file</div>
        )}
      </div>
    </div>
  );
}
