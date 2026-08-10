import { useProjectStore } from '../../store/projectStore';

export function GenerateBanner() {
  const currentSpec = useProjectStore((s) => s.currentSpec);
  const pendingDiff = useProjectStore((s) => s.pendingDiff);
  const files = useProjectStore((s) => s.files);
  const generating = useProjectStore((s) => s.generating);
  const generateError = useProjectStore((s) => s.generateError);
  const generate = useProjectStore((s) => s.generate);
  const applySpecDiff = useProjectStore((s) => s.applySpecDiff);

  if (!currentSpec) return null;

  const hasFiles = Object.keys(files).length > 0;

  let label: string;
  let loadingLabel: string;
  let description: string | null = null;
  let onClick: () => void;

  if (pendingDiff) {
    label = 'Apply Changes';
    loadingLabel = 'Applying…';
    description = 'Spec changes ready to apply.';
    onClick = () => applySpecDiff(pendingDiff);
  } else if (!hasFiles) {
    label = 'Generate Code';
    loadingLabel = 'Generating…';
    description = `Spec ready: ${currentSpec.name}.`;
    onClick = () => generate();
  } else {
    label = 'Regenerate Code';
    loadingLabel = 'Generating…';
    description = 'This will overwrite existing files — no automatic backup yet.';
    onClick = () => generate();
  }

  return (
    <div className="shrink-0 border-t bg-muted/40 px-4 py-2">
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm text-muted-foreground">{description}</span>
        <button
          onClick={onClick}
          disabled={generating}
          className="shrink-0 px-4 py-1.5 bg-primary text-primary-foreground rounded-lg text-sm disabled:opacity-50"
        >
          {generating ? loadingLabel : label}
        </button>
      </div>
      {generateError && (
        <div className="mt-1 text-xs text-destructive">{generateError}</div>
      )}
    </div>
  );
}
