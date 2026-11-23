import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import errorCodes from "../../../api-client/src/error-codes.json";
import { ChatThread } from "../ChatThread";
import { CitationChips } from "../CitationChips";
import { errorMessage, errorsPt } from "../i18n/errors.pt";
import { MessageBubble } from "../MessageBubble";
import { SafeMarkdown } from "../SafeMarkdown";
import type { Citation } from "../types";

afterEach(cleanup);

const citation = (index: number, extra: Partial<Citation> = {}): Citation => ({
  index,
  chunk_id: `c${index}`,
  doc_id: `d${index}`,
  source_uri: `file:///d${index}.pdf`,
  title: `Documento ${index}`,
  page_start: 3,
  ...extra,
});

describe("SafeMarkdown (INV-08)", () => {
  it("inv08_safe_markdown_blocks_images", () => {
    const { container } = render(
      <SafeMarkdown>{"![x](https://evil.example/a.png) ok"}</SafeMarkdown>,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("[imagem bloqueada]")).toBeTruthy();
  });

  it("inv08_blocks_javascript_links", () => {
    const { container } = render(
      <SafeMarkdown allowedHosts={["ok.example"]}>
        {"[a](javascript:alert(1)) [b](data:text/html,x) [c](vbscript:x) [d](JaVaScRiPt:y)"}
      </SafeMarkdown>,
    );
    expect(container.querySelector("a")).toBeNull();
    expect(container.innerHTML).not.toMatch(/javascript:|data:text|vbscript:/i);
    expect(screen.getByText("a")).toBeTruthy();
  });

  it("inv08_raw_html_not_rendered", () => {
    const { container } = render(
      <SafeMarkdown>
        {'<script>window.x=1</script><b onclick="x()">negrito</b> texto'}
      </SafeMarkdown>,
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.innerHTML).not.toContain("onclick");
  });

  it("inv08_autolink_to_non_allowlisted_is_text", () => {
    const { container } = render(
      <SafeMarkdown allowedHosts={["docs.example"]}>
        {"https://evil.example/x e [ok](https://docs.example/p) e [http](http://docs.example/p)"}
      </SafeMarkdown>,
    );
    const links = [...container.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://docs.example/p"]);
    expect(links[0]!.getAttribute("rel")).toContain("noopener");
    expect(container.textContent).toContain("https://evil.example/x");
  });

  it("allows internal citation anchors and renders tables", () => {
    const { container } = render(
      <SafeMarkdown>{"ver [1](#cit-1)\n\n| a |\n|---|\n| b |"}</SafeMarkdown>,
    );
    expect(container.querySelector('a[href="#cit-1"]')).not.toBeNull();
    expect(container.querySelector("table")).not.toBeNull();
  });
});

describe("citações e mensagens", () => {
  it("citation_chips_click_callback", () => {
    const onSelect = vi.fn();
    render(
      <CitationChips
        citations={[citation(1), citation(2, { title: null, page_start: null })]}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByText("[1] Documento 1, pág. 3"));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ index: 1 }));
    expect(screen.getByText("[2] Documento sem título")).toBeTruthy();
  });

  it("kind_badges", () => {
    const base = { id: "1", role: "assistant" as const, text: "texto" };
    const { rerender } = render(<MessageBubble message={{ ...base, kind: "general_knowledge" }} />);
    expect(screen.getByTestId("kind-badge").textContent).toBe("Conhecimento geral");
    rerender(<MessageBubble message={{ ...base, kind: "not_found" }} />);
    expect(screen.getByTestId("kind-badge").textContent).toBe("Não encontrado");
    rerender(<MessageBubble message={{ ...base, kind: "grounded" }} />);
    expect(screen.queryByTestId("kind-badge")).toBeNull();
    rerender(
      <MessageBubble
        message={{ id: "2", role: "user", text: "**não é markdown**", kind: "not_found" }}
      />,
    );
    expect(screen.queryByTestId("kind-badge")).toBeNull();
    expect(screen.getByText("**não é markdown**")).toBeTruthy();
  });

  it("thread shows the AI disclosure and opens the citation panel", () => {
    const onOpen = vi.fn();
    render(
      <ChatThread
        messages={[
          {
            id: "1",
            role: "assistant",
            text: "Resposta [1]",
            kind: "grounded",
            citations: [citation(1)],
          },
        ]}
        onOpenDocument={onOpen}
      />,
    );
    expect(screen.getByRole("note").textContent).toContain("inteligência artificial");
    fireEvent.click(screen.getByText("[1] Documento 1, pág. 3"));
    fireEvent.click(screen.getByText("Abrir documento"));
    expect(onOpen).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByText("Fechar"));
    expect(screen.queryByText("Abrir documento")).toBeNull();
  });
});

describe("mensagens de erro", () => {
  it("error_messages_cover_all_codes", () => {
    const missing = (errorCodes as string[]).filter((code) => !errorsPt[code]);
    expect(missing).toEqual([]);
    expect(errorMessage("codigo_desconhecido")).toBe(errorsPt["internal_error"]);
    expect(errorMessage(undefined)).toBe(errorsPt["internal_error"]);
  });
});
