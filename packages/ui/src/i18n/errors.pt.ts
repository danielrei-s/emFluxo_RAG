/** Mensagens de erro em PT-PT por código da API (a lista vem de api-client/src/error-codes.json). */
export const errorsPt: Record<string, string> = {
  access_denied: "Não tem permissão para esta ação.",
  bad_request: "O pedido não é válido.",
  consent_error: "É necessário o seu consentimento para continuar.",
  corrupted_file: "O ficheiro está corrompido.",
  encrypted_file: "O ficheiro está protegido por palavra-passe e não pode ser lido.",
  file_too_large: "O ficheiro é demasiado grande.",
  internal_error: "Ocorreu um erro inesperado. Tente novamente dentro de instantes.",
  not_found: "Não foi encontrado.",
  parse_memory_limit: "O ficheiro é demasiado complexo para ser processado.",
  parse_timeout: "O processamento do ficheiro demorou demasiado tempo.",
  prompt_too_large: "A pergunta é demasiado longa.",
  quota_exceeded: "A quota mensal da sua organização foi atingida.",
  rate_limited: "Demasiados pedidos. Aguarde um momento e tente novamente.",
  sandbox_violation: "O ficheiro foi bloqueado por motivos de segurança.",
  unauthenticated: "A sessão expirou. Inicie sessão novamente.",
  unsupported_feature: "Esta funcionalidade não é suportada.",
  unsupported_type: "Este tipo de ficheiro não é suportado.",
  upstream_error: "O serviço de respostas está indisponível. Tente novamente mais tarde.",
  validation_failed: "Os dados enviados não são válidos.",
};

export function errorMessage(code: string | undefined): string {
  return (code && errorsPt[code]) || errorsPt["internal_error"]!;
}
