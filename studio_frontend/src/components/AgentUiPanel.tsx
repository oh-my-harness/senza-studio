// studio_frontend/src/components/AgentUiPanel.tsx
//
// spec 顶层 ui 块的编辑器：导出 Agent（以及它的预览 Game view）的形态、文案
// 和视觉。
//
// 这些不属于任何一个 step，所以没地方挂在节点 Inspector 里——放在"没选中节点"
// 时的 Inspector 上：那块地方本来只写着"选择一个节点查看属性"，而这恰好是
// 唯一一处"整个 agent 的属性"。
//
// 字段列表和生效中的形态都不在前端算：问后端的 /api/projects/{id}/agent，它已经
// 把入口输入扫出来、把默认值算好、把作者写的覆盖值合并完了，形态也是它按流程
// 猜的。前端自己再算一遍就等于把同一套规则实现第二遍。
import { useEffect, useState } from "react";
import { api } from "../api";
import { FALLBACK_THEME } from "../player/theme";
import type { AgentInput, AgentInfo } from "../player/types";
import { useStudioStore } from "../store";

type InputDraft = { label: string; placeholder: string; multiline: boolean };

interface Draft {
  title: string;
  description: string;
  /** "" = 自动（不写进 spec，由后端按流程形态猜） */
  layout: string;
  accent: string;
  mode: string;
  density: string;
  logo: string;
  inputs: Record<string, InputDraft>;
}

const LAYOUT_OPTIONS = [
  { value: "", label: "自动" },
  { value: "form", label: "表单 — 填表、时间线、结果" },
  { value: "dashboard", label: "看板 — 一屏面板，无时间线" },
];

function toDraft(info: AgentInfo, explicitLayout: string): Draft {
  return {
    title: info.title,
    description: info.description,
    layout: explicitLayout,
    accent: info.theme?.accent ?? FALLBACK_THEME.accent,
    mode: info.theme?.mode ?? FALLBACK_THEME.mode,
    density: info.theme?.density ?? FALLBACK_THEME.density,
    logo: info.theme?.logo ?? "",
    inputs: Object.fromEntries(
      info.inputs.map((f: AgentInput) => [
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
  const [effectiveLayout, setEffectiveLayout] = useState("form");

  useEffect(() => {
    let alive = true;
    const explicit = String((spec.ui as Record<string, unknown>)?.layout ?? "");
    api
      .getAgent(projectId)
      .then((info) => {
        if (!alive) return;
        // 显示的是**实际会用的值**（作者没写就是推导出来的），而不是空框——
        // 空框会让人以为标题和标签也是空的。
        const next = toDraft(info, explicit);
        setDraft(next);
        setSaved(next);
        setEffectiveLayout(info.layout);
      })
      .catch(console.error);
    return () => {
      alive = false;
    };
    // 只跟 stages 走，不跟整个 spec 走：保存这里的文案会改 spec.ui，若把
    // 整个 spec 放进依赖，保存立刻触发重新取一次契约，而那个 PUT 还没落盘
    // ——取回来的是旧值，界面上看起来就像"保存没生效"。stages 变了（加了个
    // 入口 {{var}}、换了第一个 step）字段列表和推导出来的形态确实要跟着变。
  }, [projectId, JSON.stringify(spec.stages)]);

  if (!draft) {
    return <div className="p-4 text-sm text-gray-400">加载中…</div>;
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(saved);
  const patch = (fields: Partial<Draft>) => setDraft({ ...draft, ...fields });
  const patchInput = (name: string, fields: Partial<InputDraft>) =>
    setDraft({
      ...draft,
      inputs: { ...draft.inputs, [name]: { ...draft.inputs[name], ...fields } },
    });

  const save = () => {
    const ui: Record<string, unknown> = {};
    // 和项目名相同就不写进 spec——那本来就是兜底值，写进去只会在改项目名时
    // 留下一个对不上的旧标题。
    if (draft.title && draft.title !== projectName) ui.title = draft.title;
    if (draft.description) ui.description = draft.description;
    // "自动"就是不写这个键，让后端按流程形态猜——写死一个跟推导结果相同的值
    // 看着没差别，但流程改了之后它就不会跟着变了。
    if (draft.layout) ui.layout = draft.layout;

    const theme: Record<string, unknown> = {};
    if (draft.accent !== FALLBACK_THEME.accent) theme.accent = draft.accent;
    if (draft.mode !== FALLBACK_THEME.mode) theme.mode = draft.mode;
    if (draft.density !== FALLBACK_THEME.density) theme.density = draft.density;
    if (draft.logo) theme.logo = draft.logo;
    if (Object.keys(theme).length > 0) ui.theme = theme;

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

  const inputClass =
    "w-full rounded border border-gray-200 px-2 py-1 text-sm outline-none focus:border-blue-400";
  const field = (label: string, node: React.ReactNode, hint?: string) => (
    <div>
      <label className="mb-1 block text-xs text-gray-500">{label}</label>
      {node}
      {hint && <p className="mt-1 text-xs text-gray-400">{hint}</p>}
    </div>
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <p className="text-xs text-gray-400">
          最终用户在导出的 Agent 里看到的东西。Play 之后的 Game view 就是它的预览。
        </p>

        {field(
          "形态",
          <select
            value={draft.layout}
            onChange={(e) => patch({ layout: e.target.value })}
            className={`${inputClass} bg-white`}
          >
            {LAYOUT_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>,
          draft.layout
            ? undefined
            : `按当前流程推导：${effectiveLayout === "dashboard" ? "看板" : "表单"}`
        )}

        {field(
          "标题",
          <input
            value={draft.title}
            onChange={(e) => patch({ title: e.target.value })}
            className={inputClass}
          />
        )}
        {field(
          "一句话说明",
          <input
            value={draft.description}
            onChange={(e) => patch({ description: e.target.value })}
            placeholder="这个 agent 是干什么的"
            className={inputClass}
          />
        )}

        <div className="space-y-3 border-t border-gray-100 pt-3">
          <div className="text-xs font-medium text-gray-600">视觉</div>
          {field(
            "主色",
            <div className="flex items-center gap-2">
              <input
                type="color"
                value={/^#[0-9a-fA-F]{6}$/.test(draft.accent) ? draft.accent : "#2563eb"}
                onChange={(e) => patch({ accent: e.target.value })}
                className="h-7 w-10 shrink-0 cursor-pointer rounded border border-gray-200"
              />
              <input
                value={draft.accent}
                onChange={(e) => patch({ accent: e.target.value })}
                className={inputClass}
              />
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            {field(
              "明暗",
              <select
                value={draft.mode}
                onChange={(e) => patch({ mode: e.target.value })}
                className={`${inputClass} bg-white`}
              >
                <option value="light">浅色</option>
                <option value="dark">深色</option>
              </select>
            )}
            {field(
              "密度",
              <select
                value={draft.density}
                onChange={(e) => patch({ density: e.target.value })}
                className={`${inputClass} bg-white`}
              >
                <option value="comfortable">宽松</option>
                <option value="compact">紧凑</option>
              </select>
            )}
          </div>
          {field(
            "Logo",
            <input
              value={draft.logo}
              onChange={(e) => patch({ logo: e.target.value })}
              placeholder="图片 URL 或 data: URI"
              className={inputClass}
            />,
            "上传图片文件还没做，先填一个地址"
          )}
        </div>

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
                      onChange={(e) => patchInput(name, { label: e.target.value })}
                      className={inputClass}
                    />
                  )}
                  {field(
                    "placeholder",
                    <input
                      value={options.placeholder}
                      onChange={(e) => patchInput(name, { placeholder: e.target.value })}
                      placeholder="输入框里的灰字提示"
                      className={inputClass}
                    />
                  )}
                  <label className="flex items-center gap-2 text-xs text-gray-600">
                    <input
                      type="checkbox"
                      checked={options.multiline}
                      onChange={(e) => patchInput(name, { multiline: e.target.checked })}
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
