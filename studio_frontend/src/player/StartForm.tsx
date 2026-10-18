// studio_frontend/src/player/StartForm.tsx —— 入口输入表单。
//
// 两种排版：表单布局用 stacked（每个字段一行，多行框），看板布局用 inline
// （挤成一条，和"运行"按钮并排）。字段本身和校验规则是同一份。
import { useState } from "react";
import type { AgentInfo } from "./types";

/** 开始按钮的就绪判定：字段默认必填；契约里声明了 optional 的字段允许留空。
 *  留空的语义由后端 loader 决定（默认档/自动推断），前端不编造值。 */
export function isStartReady(
  inputs: { name: string; optional?: boolean }[],
  values: Record<string, string>,
): boolean {
  return inputs.every(
    (field) => field.optional || (values[field.name] ?? "").trim() !== "",
  );
}

export default function StartForm({
  info,
  disabled,
  onStart,
  variant = "stacked",
  submitLabel = "开始",
}: {
  info: AgentInfo;
  disabled: boolean;
  onStart: (values: Record<string, string>) => void;
  variant?: "stacked" | "inline";
  submitLabel?: string;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const ready = isStartReady(info.inputs, values);
  const inline = variant === "inline";

  const inputClass =
    "w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-faint)] focus:border-[var(--accent)]";

  return (
    <form
      className={inline ? "flex flex-wrap items-end gap-3" : "space-y-4"}
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !disabled) onStart(values);
      }}
    >
      {info.inputs.map((field) => (
        <div key={field.name} className={inline ? "min-w-[12rem] flex-1" : undefined}>
          <label
            className="mb-1.5 block text-sm font-medium text-[var(--text)]"
            htmlFor={`input-${field.name}`}
          >
            {field.label}
            {field.optional && (
              <span className="ml-1 text-xs font-normal text-[var(--text-faint)]">
                （可选）
              </span>
            )}
          </label>
          {field.multiline && !inline ? (
            <textarea
              id={`input-${field.name}`}
              rows={5}
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
      ))}
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
