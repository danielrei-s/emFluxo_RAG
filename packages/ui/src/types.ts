import type { AnswerKind } from "./i18n/pt";

/** Espelho dos tipos Citation e Answer da C6 (o cliente gerado chega com a F10-T02). */
export interface Citation {
  index: number;
  chunk_id: string;
  doc_id: string;
  source_uri: string;
  title?: string | null;
  page_start?: number | null;
}

export interface ChatMessageData {
  id: string;
  role: "user" | "assistant";
  text: string;
  kind?: AnswerKind;
  citations?: readonly Citation[];
}
