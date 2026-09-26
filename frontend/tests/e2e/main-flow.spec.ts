import { expect, test } from "@playwright/test";

const routes = ["/exposicao", "/manutencao", "/bateria", "/relatorio", "/configuracoes"];

test("percorre exposição, manutenção, bateria e relatório sem perder o modo BESS", async ({ page }) => {
  await page.goto("/exposicao");
  await expect(page.getByRole("heading", { name: "Exposição e perspectiva operacional" })).toBeVisible();
  await expect(page.getByText("Esta perspectiva ainda não é uma previsão operacional.")).toBeVisible();
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

test("troca de ativo seleciona exposição e qualidade próprias", async ({ page }) => {
  await page.goto("/exposicao");
  await expect(page.getByText("844,8 GWh")).toBeVisible();
  await page.locator('select[name="asset"]').selectOption("asset-solar");
  await expect(page.getByText("126,4 GWh")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Modalidade solar registrada" })).toBeVisible();
  await page.getByText("Caminho deste número", { exact: true }).first().click();
  await expect(page.getByText("API CurtailLess, fixture solar sintética", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("solar-demo-snapshot-2026-09-26")).toBeVisible();
});

test("não reutiliza ranking após parâmetros sem pacote ou ida e volta entre ativos", async ({ page }) => {
  await page.goto("/manutencao");
  await page.getByLabel("Duração (horas)").fill("48");
  await page.getByRole("button", { name: "Comparar janelas" }).click();
  await expect(page.getByText("Combinação ainda não materializada")).toBeVisible();
  await expect(page.getByText("Ranking de janelas")).toHaveCount(0);
  await page.locator('select[name="asset"]').selectOption("asset-solar");
  await page.locator('select[name="asset"]').selectOption("asset-wind");
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
  await page.locator('select[name="asset"]').selectOption("asset-solar");
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
  for (const selector of [".react-flow__controls-button", "a[aria-label='Relatório']", "a[aria-label='Fontes e qualidade']"]) {
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
