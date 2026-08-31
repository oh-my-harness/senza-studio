// studio_frontend/src/components/Markdown.tsx
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// 没装 @tailwindcss/typography，用 Tailwind 任意值选择器直接给渲染出来的
// 标签定样式，避免多加一个只为这一处用的插件依赖。
const PROSE_CLASSES = [
  "[&_p]:mb-2 [&_p:last-child]:mb-0",
  "[&_strong]:font-semibold",
  "[&_em]:italic",
  "[&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-2",
  "[&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-2",
  "[&_li]:mb-0.5",
  "[&_code]:bg-gray-100 [&_code]:rounded [&_code]:px-1 [&_code]:py-0.5 [&_code]:text-xs [&_code]:font-mono",
  "[&_pre]:bg-gray-100 [&_pre]:rounded [&_pre]:p-2 [&_pre]:mb-2 [&_pre]:overflow-x-auto [&_pre_code]:bg-transparent [&_pre_code]:p-0",
  "[&_a]:text-blue-600 [&_a]:underline",
  "[&_h1]:text-base [&_h1]:font-semibold [&_h1]:mb-1",
  "[&_h2]:text-sm [&_h2]:font-semibold [&_h2]:mb-1",
  "[&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mb-1",
  "[&_blockquote]:border-l-2 [&_blockquote]:border-gray-300 [&_blockquote]:pl-2 [&_blockquote]:text-gray-500 [&_blockquote]:italic",
  "[&_table]:border-collapse [&_th]:border [&_th]:border-gray-200 [&_th]:px-2 [&_th]:py-1 [&_td]:border [&_td]:border-gray-200 [&_td]:px-2 [&_td]:py-1",
].join(" ");

export default function Markdown({ text }: { text: string }) {
  return (
    <div className={PROSE_CLASSES}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
    </div>
  );
}
