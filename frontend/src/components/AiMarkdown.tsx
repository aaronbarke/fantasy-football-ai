import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

// AI answers are built from league data other people write (team names, owner
// names, news), so a prompt injection could make the model emit an image whose
// URL smuggles the conversation out the moment it renders. Answers never need
// images. Links open in a new tab without handing over a reference to this page.
const SAFE_COMPONENTS: Components = {
  a: ({ href, children }) => (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer nofollow"
      className="font-medium underline"
    >
      {children}
    </a>
  ),
};

/** Markdown rendering for model output. Raw HTML is never rendered and unsafe
 * URL schemes are stripped (react-markdown defaults); images are dropped. */
export default function AiMarkdown({
  children,
  components,
}: {
  children: string;
  components?: Components;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      disallowedElements={["img"]}
      components={{ ...components, ...SAFE_COMPONENTS }}
    >
      {children}
    </ReactMarkdown>
  );
}
