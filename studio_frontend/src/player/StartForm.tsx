// studio_frontend/src/player/StartForm.tsx —— 入口输入表单。
//
// 两种排版：表单布局用 stacked（每个字段一行，多行框），看板布局用 inline
// （挤成一条，和"运行"按钮并排）。字段本身和校验规则是同一份。
import { useState } from "react";
import type { AgentInfo } from "./types";

/** 入口是否可以提交：首轮输入没有可选项，所有字段都必须有非空值。
 *  默认值只是预填，用户可以清空，所以仍然按"非空"判断。 */
export function isStartReady(
  inputs: AgentInfo["inputs"],
  values: Record<string, string>,
): boolean {
  return inputs.every((field) => (values[field.name] ?? "").trim() !== "");
}

export default function StartForm({
  info,
  disabled,
  onStart,
  variant = "stacked",
  submitLabel = "开始",
  values: controlledValues,
  onValuesChange,
  dense = false,
}: {
  info: AgentInfo;
  disabled: boolean;
  onStart: (values: Record<string, string>) => void;
  variant?: "stacked" | "inline";
  submitLabel?: string;
  values?: Record<string, string>;
  onValuesChange?: (values: Record<string, string>) => void;
  /** 对话布局用：多行框收成 2 行，并把字段区限制在固定高度内滚动，
   *  保证聊天记录永远有空间、发送按钮始终可见。表单/看板布局不传。 */
  dense?: boolean;
}) {
  const [localValues, setLocalValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(info.inputs.filter(f => f.default !== undefined).map(f => [f.name, f.default!])),
  );
  const values = controlledValues ?? localValues;
  const setValues = (update: (v: Record<string, string>) => Record<string, string>) => {
    const next = update(values);
    if (onValuesChange) onValuesChange(next);
    else setLocalValues(next);
  };
  const ready = isStartReady(info.inputs, values);
  const inline = variant === "inline";

  const inputClass =
    "w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-faint)] focus:border-[var(--accent)]";

  const fields = info.inputs.map((field) => (
    <div key={field.name} className={inline ? "min-w-[12rem] flex-1" : undefined}>
      <label
        className="mb-1.5 block text-sm font-medium text-[var(--text)]"
        htmlFor={`input-${field.name}`}
      >
        {field.label}
      </label>
      {field.multiline && !inline ? (
        <textarea
          id={`input-${field.name}`}
          rows={dense ? 2 : 5}
          placeholder={field.placeholder}
          value={values[field.name] ?? ""}
          onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
          className={`resize-y ${inputClass}`}
        />
      ) : (
        <input
          id={`input-${field.name}`}
          placeholder={field.placeholder}
          value={values[field.name] ?? ""}
          onChange={(e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))}
          className={inputClass}
        />
      )}
    </div>
  ));

  return (
    <form
      className={inline ? "flex flex-wrap items-end gap-3" : "space-y-4"}
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !disabled) onStart(values);
      }}
    >
      {dense ? (
        <div className="max-h-[32vh] space-y-4 overflow-y-auto pr-1">{fields}</div>
      ) : (
        fields
      )}
      <button
        type="submit"
        disabled={!ready || disabled}
        className="rounded-lg bg-[var(--accent)] px-5 py-2 text-sm font-medium text-[var(--accent-fg)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {submitLabel}
      </button>
    </form>
  );
}
