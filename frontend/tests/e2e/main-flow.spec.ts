import { expect, test, type Page } from "@playwright/test";

const routes = ["/exposicao", "/manutencao", "/bateria", "/relatorio", "/configuracoes"];

async function selectAsset(page: Page, name: string) {
  await page.locator("button[data-asset-picker]").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: new RegExp(name) }).click();
  await expect(dialog).toBeHidden();
}

test("percorre exposição, manutenção, bateria e relatório sem perder o modo BESS", async ({ page }) => {
  await page.goto("/exposicao");
  await expect(page.locator("[data-exposure-screen]")).toBeVisible();
  await page.getByRole("link", { name: "Manutenção", exact: true }).click();
  await page.getByRole("button", { name: "Comparar janelas" }).click();
  await page.getByRole("button", { name: "Selecionar esta janela" }).click();
  await page.getByRole("link", { name: "Bateria", exact: true }).click();
  await expect(page.getByText(/A triagem usa o perfil residual-wind-alt-1/)).toBeVisible();
  await page.getByRole("button", { name: /Já possuo uma bateria/ }).click();
  await page.getByRole("button", { name: "Avaliar configuração" }).click();
  await page.getByRole("button", { name: "Registrar triagem no relatório" }).click();
  await expect(page.getByRole("button", { name: "Triagem registrada" })).toBeVisible();
  await page.getByRole("link", { name: "Relatório" }).click();
  await expect(page.getByText("Bateria existente", { exact: true })).toBeVisible();
  await expect(page.getByText("59.200 R$/ano")).toBeVisible();
  await expect(page.getByText("91.000 R$/ano")).toHaveCount(0);
});

test("troca o ativo real somente na tela de exposição", async ({ page }) => {
  await page.goto("/exposicao");
  const screen = page.locator("[data-exposure-screen]");
  await expect(screen).toHaveAttribute("data-asset-id", "CJU_RNRDV");
  const windIllustrations = screen.locator('[data-energy-illustration="wind"]');
  await expect(windIllustrations).toHaveCount(6);
  await expect(windIllustrations.first().locator("[data-connected-plant]")).toHaveCount(1);

  await selectAsset(page, "Conj. Monte Verde Solar");
  await expect(screen).toHaveAttribute("data-asset-id", "CJU_RNMVS");
  const solarIllustrations = screen.locator('[data-energy-illustration="solar"]');
  await expect(solarIllustrations).toHaveCount(6);
  await expect(solarIllustrations.first().locator("[data-connected-plant]")).toHaveCount(3);
  await expect(screen.locator('[data-energy-illustration="wind"]')).toHaveCount(0);

  await page.getByRole("link", { name: "Manutenção", exact: true }).click();
  await expect(page.locator("button[data-asset-picker]")).toContainText("Ativo Eólico RN-01");
});

test("não reutiliza ranking após parâmetros sem pacote ou ida e volta entre ativos", async ({ page }) => {
  await page.goto("/manutencao");
  await page.getByLabel("Duração (horas)").fill("48");
  await page.getByRole("button", { name: "Comparar janelas" }).click();
  await expect(page.getByText("Combinação ainda não materializada")).toBeVisible();
  await expect(page.getByText("Ranking de janelas")).toHaveCount(0);
  await selectAsset(page, "Ativo Solar MG-02");
  await selectAsset(page, "Ativo Eólico RN-01");
  await expect(page.getByText("Ranking aguardando consulta")).toBeVisible();
  await expect(page.getByText("Combinação ainda não materializada")).toHaveCount(0);
});

test("relatório não materializa manutenção ou BESS sem análise", async ({ page }) => {
  await page.goto("/relatorio");
  await expect(page.getByText("Análise de manutenção não realizada")).toBeVisible();
  await expect(page.getByText("Triagem BESS não registrada")).toBeVisible();
  await expect(page.getByText("Ranking consultado")).toHaveCount(0);
  await expect(page.getByText("Parâmetros da intervenção")).toHaveCount(0);
});

test("preço vazio degrada todos os resultados monetários até o relatório", async ({ page }) => {
  await page.goto("/manutencao");
  await page.getByLabel("Preço de cenário (R$/MWh)").fill("");
  await page.getByRole("button", { name: "Comparar janelas" }).click();
  await expect(page.getByText("Custo de oportunidade indisponível")).toBeVisible();
  await page.getByRole("button", { name: "Selecionar esta janela" }).click();
  await expect(page.getByText(/Diferença monetária: Indisponível/)).toBeVisible();
  await page.getByRole("link", { name: "Relatório" }).click();
  await expect(page.getByText("Indisponível", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/3\.360 R\$/)).toHaveCount(0);
});

test("formulários BESS distinguem bateria nova e existente e recusam pacote alterado", async ({ page }) => {
  await page.goto("/bateria");
  await expect(page.getByLabel("CAPEX total (R$)")).toHaveValue("1200000");
  await expect(page.getByLabel("Duração de descarga (horas)")).toHaveValue("4");
  await page.getByRole("button", { name: /Já possuo uma bateria/ }).click();
  await expect(page.getByLabel("Capacidade (MWh)")).toHaveValue("80");
  await expect(page.getByLabel("SOC inicial (%)")).toHaveValue("48");
  await page.getByLabel("Degradação anual (%/ano) (opcional)").locator("..").getByText("Procedência: simulado").click();
  await expect(page.getByText("Degradação da bateria existente não validada")).toBeVisible();
  await page.getByLabel("Capacidade (MWh)").fill("81");
  await page.getByRole("button", { name: "Avaliar configuração" }).click();
  await expect(page.getByText("Configuração ainda não materializada")).toBeVisible();
  await expect(page.getByText("Conclusão da triagem")).toHaveCount(0);
});

test("invalida o cenário BESS local ao trocar de ativo", async ({ page }) => {
  await page.goto("/bateria");
  await page.getByRole("button", { name: "Avaliar configuração" }).click();
  await expect(page.getByText("702 MWh/ano")).toBeVisible();
  await selectAsset(page, "Ativo Solar MG-02");
  await expect(page.getByText("702 MWh/ano")).toHaveCount(0);
  await expect(page.getByText("Conclusão da triagem")).toHaveCount(0);
  await expect(page.getByText("Triagem aguardando avaliação")).toBeVisible();
});

test("abre todas as rotas diretamente", async ({ page }) => {
  for (const route of routes) {
    const response = await page.goto(route);
    expect(response?.ok()).toBeTruthy();
    await expect(page.locator("h1")).toBeVisible();
  }
});

test("não cria rolagem horizontal no celular e usa lista legível para a topologia", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  for (const route of routes) {
    await page.goto(route);
    const dimensions = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
    expect(dimensions.scroll, `${route} excedeu ${dimensions.client}px`).toBe(dimensions.client);
  }
  await page.goto("/exposicao");
  await expect(page.locator("[data-topology-list]")).toBeVisible();
  await expect(page.locator(".react-flow")).toBeHidden();
});

test("skip link transfere foco e controles visíveis têm alvo mínimo de 44 px", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/exposicao");
  const skipLink = page.getByRole("link", { name: "Pular para o conteúdo" });
  await skipLink.focus();
  await expect(skipLink).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main-content")).toBeFocused();
  await expect(page.locator(".react-flow__attribution")).toHaveCount(0);
  for (const selector of [".react-flow__controls-button", "a[aria-label='Relatório']", "a[aria-label='Fontes']", "button[data-asset-picker]"]) {
    const items = page.locator(selector);
    await expect(items.first(), selector).toBeVisible();
    const boxes = await items.evaluateAll((elements) => elements.filter((element) => { const style = getComputedStyle(element); return style.display !== "none" && style.visibility !== "hidden"; }).map((element) => { const box = element.getBoundingClientRect(); return { width: box.width, height: box.height }; }));
    for (const box of boxes) { expect(box.width).toBeGreaterThanOrEqual(44); expect(box.height).toBeGreaterThanOrEqual(44); }
  }
  await page.goto("/bateria");
  for (const legend of ["Configuração técnica", "Premissas econômicas", "Operação e conexão", "Restrições, medição e preço"]) await expect(page.getByText(legend, { exact: true })).toBeVisible();
  const provenanceBoxes = await page.locator("summary").filter({ hasText: "Procedência:" }).evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height));
  expect(provenanceBoxes.length).toBeGreaterThan(0);
  for (const height of provenanceBoxes) expect(height).toBeGreaterThanOrEqual(44);
});

test("estrutura a exposição em seis seções com análise e dados", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/exposicao");
  const sections = page.locator("[data-analysis-section]");
  const expectedIds = ["secao-ativo", "secao-resumo", "secao-previsao", "secao-razao-origem", "secao-recorrencia", "secao-qualidade"];
  await expect(sections).toHaveCount(expectedIds.length);
  expect(await sections.evaluateAll((elements) => elements.map((element) => element.id))).toEqual(expectedIds);

  for (const section of await sections.all()) {
    await expect(section.locator(":scope > [data-analysis-grid] > [data-ai-analysis]")).toHaveCount(1);
    await expect(section.locator(":scope > [data-analysis-grid] > [data-section-data-column] > [data-section-card]")).toHaveCount(1);
  }

  await expect(page.locator("#secao-previsao [data-exposure-forecast='60d']")).toHaveCount(1);
  await expect(page.locator("#secao-resumo [data-highlight-list]")).toHaveCount(1);
  await expect(page.locator("#secao-qualidade [data-highlight-list]")).toHaveCount(1);
});

test("navegação lateral expande, transfere destaque e navega entre seções", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/exposicao");
  const nav = page.locator("nav[data-section-nav]");
  const links = nav.locator("button[data-section-link]");
  await expect(nav).toBeVisible();
  await expect(links).toHaveCount(6);
  await expect(nav).toHaveAttribute("data-expanded", "false");
  await expect(links.first()).toHaveAttribute("aria-current", "true");

  await links.first().hover();
  await expect(nav).toHaveAttribute("data-expanded", "true");
  await expect(links.first()).toHaveAttribute("data-emphasis", "true");
  await links.nth(3).hover();
  await expect(links.nth(3)).toHaveAttribute("data-emphasis", "true");
  await expect(links.first()).toHaveAttribute("data-emphasis", "false");

  await links.nth(3).click();
  await expect(nav).toHaveAttribute("data-expanded", "false");
  await expect(links.nth(3)).toHaveAttribute("aria-current", "true");
  await expect.poll(async () => page.locator("#secao-razao-origem").evaluate((element) => Math.round(element.getBoundingClientRect().top))).toBeGreaterThan(0);
  await expect.poll(async () => page.locator("#secao-razao-origem").evaluate((element) => Math.round(element.getBoundingClientRect().top))).toBeLessThan(180);

  await page.locator("#secao-qualidade").evaluate((element) => element.scrollIntoView({ behavior: "auto", block: "start" }));
  await expect(links.nth(5)).toHaveAttribute("aria-current", "true");

  await links.nth(5).focus();
  await expect(nav).toHaveAttribute("data-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(nav).toHaveAttribute("data-expanded", "false");
});

test("a roda do mouse focaliza somente a seção seguinte ou anterior", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/exposicao");
  await expect(page.locator("[data-exposure-screen]")).toBeVisible();
  const links = page.locator("nav[data-section-nav] button[data-section-link]");
  await expect(links.first()).toHaveAttribute("aria-current", "true");

  await page.mouse.wheel(0, 400);
  await expect(links.nth(1)).toHaveAttribute("aria-current", "true");
  await expect.poll(async () => page.evaluate(() => {
    const header = document.querySelector<HTMLElement>("[data-app-header]");
    const section = document.querySelector<HTMLElement>("#secao-resumo");
    return header && section ? Math.abs(section.getBoundingClientRect().top - header.getBoundingClientRect().bottom) : Number.POSITIVE_INFINITY;
  })).toBeLessThan(2);

  await page.waitForTimeout(1050);
  await page.mouse.wheel(0, -400);
  await expect(links.first()).toHaveAttribute("aria-current", "true");
});

test("mantém a top bar fixa durante o scroll da exposição", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/exposicao");
  const topBar = page.locator("header.no-print");
  await expect(topBar).toBeVisible();
  expect(await topBar.evaluate((element) => getComputedStyle(element).position)).toBe("sticky");
  await page.locator("#secao-qualidade").evaluate((element) => element.scrollIntoView({ behavior: "auto", block: "start" }));
  await expect.poll(async () => topBar.evaluate((element) => Math.round(element.getBoundingClientRect().top))).toBe(0);
});
