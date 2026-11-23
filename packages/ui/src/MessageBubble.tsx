import type { ReactElement } from "react";

import { CitationChips } from "./CitationChips";
import { pt } from "./i18n/pt";
import { SafeMarkdown } from "./SafeMarkdown";
import type { ChatMessageData, Citation } from "./types";

export interface MessageBubbleProps {
  message: ChatMessageData;
  allowedHosts?: readonly string[] | undefined;
  onSelectCitation?: ((citation: Citation) => void) | undefined;
}

export function MessageBubble({
  message,
  allowedHosts,
  onSelectCitation,
}: MessageBubbleProps): ReactElement {
  const badge = message.role === "assistant" && message.kind ? pt.kind[message.kind] : "";
  return (
    <article data-role={message.role}>
      {badge ? <strong data-testid="kind-badge">{badge}</strong> : null}
      {message.role === "assistant" ? (
        <SafeMarkdown allowedHosts={allowedHosts ?? []}>{message.text}</SafeMarkdown>
      ) : (
        <p>{message.text}</p>
      )}
      <CitationChips citations={message.citations ?? []} onSelect={onSelectCitation} />
    </article>
  );
}
