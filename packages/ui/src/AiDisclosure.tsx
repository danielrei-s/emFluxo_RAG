import type { ReactElement } from "react";

import { pt } from "./i18n/pt";

/** Aviso de transparência: o utilizador sabe que está a falar com IA. */
export function AiDisclosure(): ReactElement {
  return <p role="note">{pt.disclosure}</p>;
}
