/** Textos PT-PT dos componentes de chat (C12). */
export const pt = {
  chat: {
    placeholder: "Escreva a sua pergunta",
    send: "Enviar",
    sources: "Fontes",
    openDocument: "Abrir documento",
    closePanel: "Fechar",
    page: "pág.",
    untitled: "Documento sem título",
    imageBlocked: "[imagem bloqueada]",
  },
  kind: {
    grounded: "",
    general_knowledge: "Conhecimento geral",
    not_found: "Não encontrado",
    refused: "Pedido recusado",
  },
  feedback: {
    good: "Resposta útil",
    bad: "Resposta pouco útil",
    thanks: "Obrigado pelo seu feedback",
  },
  disclosure:
    "Esta resposta foi gerada por inteligência artificial a partir dos documentos da sua organização. Verifique as fontes antes de decidir.",
} as const;

export type AnswerKind = keyof typeof pt.kind;
