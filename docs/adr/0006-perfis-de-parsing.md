# ADR-0006 · Perfis de parsing: lite (desktop) e full (central)

- **Estado:** aceite
- **Data:** 2026-11-21 · **Tarefa:** F0-T12

## Contexto

O Docling com torch dentro de um instalador desktop dá vários GB. O sandbox "sem rede" também não
é exequível sem privilégios de administrador no Windows e no macOS. Parsers de PDF, DOCX e
semelhantes são uma superfície de ataque conhecida (PDF malformado que explora o parser).

## Decisão

- Dois perfis que produzem o **mesmo** `StructuredDocument` e passam os **mesmos** testes:
  - **lite** (desktop): bibliotecas Python puras e ONNX (extras `lite`, `ocr`, `onnx` do
    `rag-core`): python-docx, openpyxl, python-pptx, pdfplumber, pypdfium2, beautifulsoup4,
    olefile.
  - **full** (central): Docling (extra `docling`), com OCR e layout avançado.
- **Sandbox:** na central, contentor sem rede (isolamento real). No desktop, subprocesso com
  limites de CPU, memória e tempo, bloqueio de rede em Python e parsers que recebem **bytes,
  nunca caminhos**. O risco residual no desktop fica documentado.
- EML usa a biblioteca padrão do Python; o formato MSG fica pendente de decisão de licença
  (extract-msg é GPL-3.0; HR-04) e, até lá, "não suportado" no desktop.

## Alternativas consideradas

- **Docling em todo o lado** — instalador de vários GB; atualizações lentas.
- **PyMuPDF** — licença AGPL, incompatível com a política de licenças (ADR-0007).
- **Sem sandbox no desktop** — um PDF malicioso correria com todos os privilégios do utilizador.

## Consequências

- A qualidade de extração pode diferir entre perfis; a diferença é medida no golden set e
  registada.
- Instalador desktop pequeno, com modelos descarregados à parte, com hash verificado.
- Ao acrescentar um formato é preciso implementá-lo nos dois perfis ou declarar a exceção.
