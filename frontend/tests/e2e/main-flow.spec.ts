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

test("troca a usina somente na tela de exposição", async ({ page }) => {
  await page.goto("/exposicao");
  const screen = page.locator("[data-exposure-screen]");
  await expect(screen).toHaveAttribute("data-asset-id", "RNEM13");
  const windIllustrations = screen.locator('[data-energy-illustration="wind"]');
  await expect(windIllustrations).toHaveCount(6);

  await selectAsset(page, "Monte Verde Solar II");
  await expect(screen).toHaveAttribute("data-asset-id", "RNMVS2");
  const solarIllustrations = screen.locator('[data-energy-illustration="solar"]');
  await expect(solarIllustrations).toHaveCount(6);
  await expect(screen.locator('[data-energy-illustration="wind"]')).toHaveCount(0);

  await page.getByRole("link", { name: "Manutenção", exact: true }).click();
  await expect(page.locator("button[data-asset-picker]")).toContainText("Ativo Eólico RN-01");
});

test("valida catálogo, contexto e narrativas da exposição por usina", async ({ page }) => {
  await page.goto("/exposicao");
  const screen = page.locator("[data-exposure-screen]");
  await expect(screen).toHaveAttribute("data-asset-id", "RNEM13");

  await page.locator("button[data-asset-picker]").click();
  const dialog = page.getByRole("dialog");
  const options = dialog.locator("ul button");
  await expect(options).toHaveCount(5);
  const optionText = await options.allTextContents();
  expect(optionText.join(" ")).not.toContain("CJU_");
  await dialog.getByRole("button", { name: "Fechar seleção de usina" }).click();

  const topology = screen.locator("[data-topology-list]");
  await expect(topology).toContainText("Ventos de Santa Martina 13");
  await expect(topology).toContainText("Rio do Vento");
  await expect(topology).toContainText("RNCMM-500-A");
  await expect(topology).toContainText("Reconciliação no conjunto");
  await expect(topology).toContainText("Pressão sistêmica no ponto");
  await expect(screen.locator("[data-point-entity]")).toHaveCount(16);
  await expect(screen.getByText(/não é atribuída à usina selecionada/)).toBeVisible();

  await expect(screen.locator("[data-analysis-title]")).toHaveCount(6);
  await expect(screen.locator("[data-analysis-title]")).toHaveText(Array(6).fill("Análise dos dados"));
  const visibleText = await screen.textContent();
  for (const forbidden of ["generation_mode", "cached_bedrock", "deterministic_fallback", "ONS_PUBLICO", "PROXY_CALCULADO", "SIMULADO"]) {
    expect(visibleText).not.toContain(forbidden);
  }
});

test("mostra 60 dias em linha e três janelas críticas de 72 horas", async ({ page }) => {
  await page.goto("/exposicao");
  const forecast = page.locator("[data-exposure-forecast='60d']");
  await expect(forecast.locator("[data-chart-kind='line']")).toHaveCount(1);
  await expect(forecast.locator("[data-forecast-point-count='60']")).toHaveCount(1);
  await expect(forecast.locator("[data-forecast-marker]")).toHaveCount(60);

  await forecast.locator("[data-forecast-marker]").nth(30).hover({ force: true });
  const tooltip = forecast.locator("[data-forecast-tooltip]");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toContainText("MWh");
  await expect(tooltip).toContainText("Risco de curtailment no dia");
  await expect(tooltip).toContainText("%");

  const windows = page.locator("[data-critical-window]");
  await expect(windows).toHaveCount(3);
  for (const window of await windows.all()) await expect(window).toHaveAttribute("data-window-hours", "72");
  await expect(page.getByText(/janela semanal/i)).toHaveCount(0);
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
  const topology = page.locator("[data-topology-list]");
  await expect(topology).toBeVisible();
  await expect(page.locator(".react-flow")).toBeHidden();
  const topologyText = await topology.locator(":scope > ul > li").evaluateAll((items) =>
    items.slice(0, 3).map((item) => item.textContent),
  );
  expect(topologyText[0]).toContain("Ventos de Santa Martina 13");
  expect(topologyText[1]).toContain("Rio do Vento");
  expect(topologyText[2]).toContain("RNCMM-500-A");

  const chartScroll = page.locator("[data-chart-scroll]");
  await expect(chartScroll).toBeVisible();
  const chartWidths = await chartScroll.evaluate((element) => ({
    client: element.clientWidth,
    content: element.scrollWidth,
  }));
  expect(chartWidths.content).toBeGreaterThan(chartWidths.client);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(375);
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
  await expect(page.locator("#secao-qualidade [data-highlight-list]")).toHaveCount(2);
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
