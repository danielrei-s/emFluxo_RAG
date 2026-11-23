import type { ReactElement, ReactNode } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { pt } from "./i18n/pt";

export interface SafeMarkdownProps {
  children: string;
  /** Anfitriões https cujos links são clicáveis (comparação exata, em minúsculas). */
  allowedHosts?: readonly string[];
}

const BLOCKED_SCHEMES = /^\s*(javascript|data|vbscript):/i;
const CITATION_ANCHOR = /^#cit-\d+$/;

/** Só âncoras de citação e https para anfitriões da allowlist; o resto vira texto simples. */
export function isSafeHref(href: string | undefined, allowedHosts: readonly string[]): boolean {
  if (!href || BLOCKED_SCHEMES.test(href)) return false;
  if (CITATION_ANCHOR.test(href)) return true;
  try {
    const url = new URL(href);
    return url.protocol === "https:" && allowedHosts.includes(url.hostname.toLowerCase());
  } catch {
    return false;
  }
}

/** Markdown sem HTML bruto, sem imagens e com links restritos (INV-08). */
export function SafeMarkdown({ children, allowedHosts = [] }: SafeMarkdownProps): ReactElement {
  return (
    <Markdown
      remarkPlugins={[remarkGfm]}
      skipHtml
      urlTransform={(url) => (BLOCKED_SCHEMES.test(url) ? "" : url)}
      components={{
        img: () => <span>{pt.chat.imageBlocked}</span>,
        a: ({ href, children: label }: { href?: string | undefined; children?: ReactNode }) =>
          isSafeHref(href, allowedHosts) ? (
            <a href={href} rel="noopener noreferrer nofollow" target="_blank">
              {label}
            </a>
          ) : (
            <span>{label}</span>
          ),
      }}
    >
      {children}
    </Markdown>
  );
}
