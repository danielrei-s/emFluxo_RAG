import type { ReactElement } from "react";

import { citationLabel } from "./CitationChips";
import { pt } from "./i18n/pt";
import type { Citation } from "./types";

export interface CitationPanelProps {
  citation: Citation | null;
  onOpenDocument?: ((citation: Citation) => void) | undefined;
  onClose?: (() => void) | undefined;
}

export function CitationPanel({
  citation,
  onOpenDocument,
  onClose,
}: CitationPanelProps): ReactElement | null {
  if (!citation) return null;
  return (
    <aside aria-label={pt.chat.sources}>
      <h3>{citationLabel(citation)}</h3>
      <button type="button" onClick={() => onOpenDocument?.(citation)}>
        {pt.chat.openDocument}
      </button>
      <button type="button" onClick={onClose}>
        {pt.chat.closePanel}
      </button>
    </aside>
  );
}
