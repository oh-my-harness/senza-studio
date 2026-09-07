// studio_frontend/src/components/SettingsModal.tsx
import { useEffect, useState } from "react";
import { api } from "../api";
import { SECRET_PLACEHOLDER } from "../types";
import type { SettingsField } from "../types";

export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const [schema, setSchema] = useState<SettingsField[]>([]);
  const [sections, setSections] = useState<Record<string, string>>({});
  const [values, setValues] = useState<Record<string, string>>({});
  const [activeSection, setActiveSection] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api
      .getSettings()
      .then(({ schema, sections, values }) => {
        setSchema(schema);
        setSections(sections || {});
        setValues(values);
        // 默认选中第一个分区，避免右侧空着
        if (schema.length > 0) setActiveSection(schema[0].group);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      const { values: updated } = await api.updateSettings(values);
      setValues(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  // 分区顺序跟随 schema 里字段出现的顺序——后端加新分区不用改前端。
  const sectionNames: string[] = [];
  for (const field of schema) {
    if (!sectionNames.includes(field.group)) sectionNames.push(field.group);
  }
  const activeFields = schema.filter((f) => f.group === activeSection);

  return (
    <div
      className="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-[44rem] h-[30rem] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-5 py-3 border-b border-gray-200 flex items-center justify-between shrink-0">
          <h2 className="font-medium text-gray-700">设置</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600 text-xl leading-none"
          >
            ×
          </button>
        </div>

        <div className="flex-1 min-h-0 flex">
          {/* 左侧分区导航 */}
          <div className="w-40 shrink-0 border-r border-gray-200 bg-gray-50 overflow-y-auto py-2">
            {sectionNames.map((name) => (
              <button
                key={name}
                onClick={() => setActiveSection(name)}
                className={`w-full text-left px-4 py-2 text-sm ${
                  name === activeSection
                    ? "bg-white text-blue-600 font-medium border-r-2 border-blue-500"
                    : "text-gray-600 hover:bg-gray-100"
                }`}
              >
                {name}
              </button>
            ))}
            {!loading && sectionNames.length === 0 && (
              <div className="px-4 py-2 text-xs text-gray-400">无</div>
            )}
          </div>

          {/* 右侧内容 */}
          <div className="flex-1 min-w-0 overflow-y-auto p-5 space-y-3">
            {loading && <div className="text-sm text-gray-400">加载中…</div>}
            {error && (
              <div className="text-sm text-red-600 bg-red-50 rounded p-2">{error}</div>
            )}
            {!loading && activeSection && (
              <>
                {sections[activeSection] && (
                  <p className="text-xs text-gray-500 pb-1">{sections[activeSection]}</p>
                )}
                {activeFields.map((field) => (
                  <div key={field.key}>
                    <label className="block text-xs text-gray-600 mb-1">
                      {field.label}
                      {field.secret && values[field.key] === SECRET_PLACEHOLDER && (
                        <span className="ml-2 text-green-600">已设置</span>
                      )}
                    </label>
                    <input
                      type={field.secret ? "password" : "text"}
                      value={
                        // 密钥的哨兵值不该显示出来——留空并用 placeholder
                        // 提示已设置；用户不输入就保持原值不变。
                        values[field.key] === SECRET_PLACEHOLDER
                          ? ""
                          : values[field.key] || ""
                      }
                      onChange={(e) =>
                        setValues((v) => ({ ...v, [field.key]: e.target.value }))
                      }
                      placeholder={
                        field.secret && values[field.key] === SECRET_PLACEHOLDER
                          ? "留空则保持现有密码不变"
                          : field.placeholder || ""
                      }
                      className="w-full rounded border border-gray-300 px-2 py-1.5 text-sm focus:outline-none focus:border-blue-400"
                    />
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        <div className="px-5 py-3 border-t border-gray-200 flex items-center justify-end gap-2 shrink-0">
          {saved && <span className="text-xs text-green-600 mr-auto">已保存，立即生效</span>}
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100"
          >
            关闭
          </button>
          <button
            onClick={save}
            disabled={saving || loading}
            className="rounded-lg bg-blue-500 px-4 py-1.5 text-sm text-white hover:bg-blue-600 disabled:opacity-50"
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
