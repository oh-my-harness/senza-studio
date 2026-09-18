// studio_frontend/src/components/AgentUiPanel.tsx
//
// spec 顶层 ui 块的编辑器：导出 Agent（以及它的预览 Game view）顶上的标题、
// 说明，和每个入口输入的文案。
//
// 这些不属于任何一个 step，所以没地方挂在节点 Inspector 里——放在"没选中节点"
// 时的 Inspector 上：那块地方本来只写着"选择一个节点查看属性"，而这恰好是
// 唯一一处"整个 agent 的属性"。
//
// 字段列表不在前端算：问后端的 /api/projects/{id}/agent，它已经把入口输入扫
// 出来、把默认 label 算好、把作者写的覆盖值合并完了。前端自己扫 {{var}} 等于
// 把同一套规则实现第二遍（还得自己处理能力组件展开）。
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AgentInput } from "../player/types";
import { useStudioStore } from "../store";

interface Draft {
  title: string;
  description: string;
  inputs: Record<string, { label: string; placeholder: string; multiline: boolean }>;
}

function toDraft(title: string, description: string, inputs: AgentInput[]): Draft {
  return {
    title,
    description,
    inputs: Object.fromEntries(
      inputs.map((f) => [
        f.name,
        { label: f.label, placeholder: f.placeholder, multiline: f.multiline },
      ])
    ),
  };
}

export default function AgentUiPanel({ projectId }: { projectId: string }) {
  const spec = useStudioStore((s) => s.spec);
  const setSpec = useStudioStore((s) => s.setSpec);
  const projectName = useStudioStore((s) => s.project?.name ?? "");

  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState<Draft | null>(null);

  useEffect(() => {
    let alive = true;
    api
      .getAgent(projectId)
      .then((info) => {
        if (!alive) return;
        // 标题框里显示的是**实际会用的值**（作者没写就是项目名），而不是空框。
        // 空框会让人以为标题也是空的。
        const next = toDraft(info.title, info.description, info.inputs);
        setDraft(next);
        setSaved(next);
      })
      .catch(console.error);
    return () => {
      alive = false;
    };
    // 只跟 stages 走，不跟整个 spec 走：保存这里的文案会改 spec.ui，若把
    // 整个 spec 放进依赖，保存立刻触发重新取一次契约，而那个 PUT 还没落盘
    // ——取回来的是旧值，界面上看起来就像"保存没生效"。stages 变了（加了个
    // 入口 {{var}}、换了第一个 step）字段列表确实要跟着变，那条保留。
  }, [projectId, JSON.stringify(spec.stages)]);

  if (!draft) {
    return <div className="p-4 text-sm text-gray-400">加载中…</div>;
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);

  const save = () => {
    const ui: Record<string, unknown> = {};
    // 和项目名相同就不写进 spec——那本来就是兜底值，写进去只会在改项目名时
    // 留下一个对不上的旧标题。
    if (draft.title && draft.title !== projectName) ui.title = draft.title;
    if (draft.description) ui.description = draft.description;
    const inputs: Record<string, Record<string, unknown>> = {};
    for (const [name, options] of Object.entries(draft.inputs)) {
      const entry: Record<string, unknown> = {};
      if (options.label) entry.label = options.label;
      if (options.placeholder) entry.placeholder = options.placeholder;
      // multiline 默认 true，只有关掉了才需要写
      if (!options.multiline) entry.multiline = false;
      if (Object.keys(entry).length > 0) inputs[name] = entry;
    }
    if (Object.keys(inputs).length > 0) ui.inputs = inputs;

    const next = { ...spec };
    if (Object.keys(ui).length > 0) next.ui = ui;
    else delete next.ui;
    setSpec(next);
    api.updateSpec(projectId, next).catch(console.error);
    setSaved(draft);
  };

  const field = (label: string, node: React.ReactNode) => (
    <div>
      <label className="mb-1 block text-xs text-gray-500">{label}</label>
      {node}
    </div>
  );

  const inputClass =
    "w-full rounded border border-gray-200 px-2 py-1 text-sm outline-none focus:border-blue-400";

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <p className="text-xs text-gray-400">
          最终用户在导出的 Agent 里看到的文案。Play 之后的 Game view 就是它的预览。
        </p>

        {field(
          "标题",
          <input
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            className={inputClass}
          />
        )}
        {field(
          "一句话说明",
          <input
            value={draft.description}
            onChange={(e) => setDraft({ ...draft, description: e.target.value })}
            placeholder="这个 agent 是干什么的"
            className={inputClass}
          />
        )}

        <div className="border-t border-gray-100 pt-3">
          <div className="mb-2 text-xs font-medium text-gray-600">入口输入</div>
          {Object.keys(draft.inputs).length === 0 ? (
            <p className="text-xs text-gray-400">
              入口 step 的 prompt_template 里还没有 {"{{变量}}"} 占位符——没有要问
              用户的东西。
            </p>
          ) : (
            <div className="space-y-4">
              {Object.entries(draft.inputs).map(([name, options]) => (
                <div key={name} className="space-y-2 rounded-lg bg-gray-50 p-2">
                  <div className="font-mono text-xs text-gray-500">{name}</div>
                  {field(
                    "label",
                    <input
                      value={options.label}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          inputs: {
                            ...draft.inputs,
                            [name]: { ...options, label: e.target.value },
                          },
                        })
                      }
                      className={inputClass}
                    />
                  )}
                  {field(
                    "placeholder",
                    <input
                      value={options.placeholder}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          inputs: {
                            ...draft.inputs,
                            [name]: { ...options, placeholder: e.target.value },
                          },
                        })
                      }
                      placeholder="输入框里的灰字提示"
                      className={inputClass}
                    />
                  )}
                  <label className="flex items-center gap-2 text-xs text-gray-600">
                    <input
                      type="checkbox"
                      checked={options.multiline}
                      onChange={(e) =>
                        setDraft({
                          ...draft,
                          inputs: {
                            ...draft.inputs,
                            [name]: { ...options, multiline: e.target.checked },
                          },
                        })
                      }
                    />
                    多行输入框
                  </label>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="shrink-0 border-t border-gray-200 p-4">
        <button
          onClick={save}
          disabled={!dirty}
          className="w-full rounded-lg bg-blue-500 px-3 py-1.5 text-sm text-white hover:bg-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          保存
        </button>
      </div>
    </div>
  );
}
