import { type ReactElement, useState } from "react";

import { AiDisclosure } from "./AiDisclosure";
import { CitationPanel } from "./CitationPanel";
import { MessageBubble } from "./MessageBubble";
import type { ChatMessageData, Citation } from "./types";

export interface ChatThreadProps {
  messages: readonly ChatMessageData[];
  allowedHosts?: readonly string[] | undefined;
  onOpenDocument?: ((citation: Citation) => void) | undefined;
}

export function ChatThread({
  messages,
  allowedHosts,
  onOpenDocument,
}: ChatThreadProps): ReactElement {
  const [selected, setSelected] = useState<Citation | null>(null);
  return (
    <section aria-live="polite">
      <AiDisclosure />
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          allowedHosts={allowedHosts}
          onSelectCitation={setSelected}
        />
      ))}
      <CitationPanel
        citation={selected}
        onOpenDocument={onOpenDocument}
        onClose={() => setSelected(null)}
      />
    </section>
  );
}
