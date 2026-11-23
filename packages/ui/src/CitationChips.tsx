import type { ReactElement } from "react";

import { pt } from "./i18n/pt";
import type { Citation } from "./types";

export interface CitationChipsProps {
  citations: readonly Citation[];
  onSelect?: ((citation: Citation) => void) | undefined;
}

export function citationLabel(citation: Citation): string {
  const title = citation.title?.trim() || pt.chat.untitled;
  return citation.page_start ? `${title}, ${pt.chat.page} ${citation.page_start}` : title;
}

export function CitationChips({ citations, onSelect }: CitationChipsProps): ReactElement | null {
  if (citations.length === 0) return null;
  return (
    <ul
      aria-label={pt.chat.sources}
      style={{ display: "flex", flexWrap: "wrap", gap: 6, padding: 0 }}
    >
      {citations.map((citation) => (
        <li key={citation.chunk_id} style={{ listStyle: "none" }}>
          <button type="button" id={`cit-${citation.index}`} onClick={() => onSelect?.(citation)}>
            [{citation.index}] {citationLabel(citation)}
          </button>
        </li>
      ))}
    </ul>
  );
}
