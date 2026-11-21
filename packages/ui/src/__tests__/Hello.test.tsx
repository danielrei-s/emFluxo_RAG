import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Hello } from "../Hello";

afterEach(cleanup);

describe("Hello", () => {
  it("renderiza a saudação por omissão", () => {
    render(<Hello />);
    expect(screen.getByText("Olá, mundo!")).toBeTruthy();
  });

  it("renderiza o nome indicado", () => {
    render(<Hello name="OLEK" />);
    expect(screen.getByText("Olá, OLEK!")).toBeTruthy();
  });
});
