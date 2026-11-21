export interface HelloProps {
  name?: string;
}

/** Componente mínimo para validar a cadeia de ferramentas JS/TS. */
export function Hello({ name = "mundo" }: HelloProps) {
  return <p>Olá, {name}!</p>;
}
