const form = document.getElementById("valuation-form");
const submitButton = document.getElementById("submit-button");
const message = document.getElementById("message");
const results = document.getElementById("results");
const skeleton = document.getElementById("skeleton");
const rankingBody = document.getElementById("ranking-body");
const rankingMessage = document.getElementById("ranking-message");
const rankingSkeleton = document.getElementById("ranking-skeleton");
const comparisonForm = document.getElementById("comparison-form");
const comparisonMessage = document.getElementById("comparison-message");
const comparisonBody = document.getElementById("comparison-body");
const rankingSection = document.getElementById("ranking");

const currency = new Intl.NumberFormat("pt-BR", {
  style: "currency",
  currency: "BRL",
});
const decimal = new Intl.NumberFormat("pt-BR", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});
const periodLabels = {
  ltm: "Últimos 12 meses (LTM)",
  "3anos": "Últimos 3 anos",
  "5anos": "Últimos 5 anos",
  todos: "Todos os anos disponíveis",
};
let priceChart;
let dividendChart;
let comparisonRequestId = 0;
let rankingItems = null;

function setComparisonTickerButtonsDisabled(disabled) {
  document.querySelectorAll(".comparison-ticker").forEach((button) => {
    button.disabled = disabled;
  });
}

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function statusClass(status) {
  return status.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replaceAll(" ", "-");
}

function formattedMargin(value) {
  return `${value >= 0 ? "+" : ""}${decimal.format(value)}%`;
}

function resultWarnings(data, period) {
  const warnings = [...data.avisos];
  if (period === "ltm" || period === "todos") {
    data.itens.forEach((item) => {
      item.avisos.forEach((warning) => warnings.push(`${item.ticker}: ${warning}`));
    });
  }
  return warnings;
}

function showWarnings(items) {
  const container = document.getElementById("warnings");
  container.replaceChildren();
  container.hidden = !items.length;
  if (!items.length) return;
  const title = document.createElement("strong");
  title.textContent = "Atenção aos dados:";
  const list = document.createElement("ul");
  items.forEach((warning) => {
    const item = document.createElement("li");
    item.textContent = warning;
    list.appendChild(item);
  });
  container.append(title, list);
}

function renderHistory(data) {
  const container = document.getElementById("dividend-history");
  container.replaceChildren();
  const isLtm = data.periodo === "ltm";
  const items = isLtm ? data.pagamentos_ltm : data.dividendos_historicos;
  setText("dividend-history-title", isLtm ? "Pagamentos utilizados" : "Dividendos anuais utilizados");
  if (!items.length) {
    container.textContent = "Nenhum pagamento registrado no período.";
  }
  items.forEach((item) => {
    const element = document.createElement("div");
    element.className = "dividend-item";
    const year = document.createElement("span");
    year.textContent = isLtm ? item.data.split("-").reverse().join("/") : item.ano;
    const value = document.createElement("strong");
    value.textContent = currency.format(item.valor);
    element.append(year, value);
    if (!isLtm) {
      const state = document.createElement("span");
      state.className = "dividend-state";
      state.textContent = item.situacao === "parcial" ? "Parcial" : item.situacao === "sem_registro" ? "Sem registro" : "Ano encerrado";
      element.appendChild(state);
    }
    container.appendChild(element);
  });
}

function renderCalculation(data) {
  const isLtm = data.periodo === "ltm";
  const items = isLtm ? data.pagamentos_ltm : data.dividendos_historicos;
  const values = items.map((item) => decimal.format(item.valor));
  const lines = [
    "Valores exibidos arredondados a duas casas decimais; os cálculos usam a precisão original.",
    `Período analisado: ${periodLabels[data.periodo]}`,
    "Dividendos utilizados:",
    ...items.map((item) => `${isLtm ? item.data.split("-").reverse().join("/") : `${item.ano}${item.situacao === "parcial" ? " (parcial)" : item.situacao === "sem_registro" ? " (sem registro)" : ""}`} = R$ ${decimal.format(item.valor)}`),
    isLtm
      ? `Dividendos LTM = ${values.length ? values.join(" + ") : "0"}`
      : `Dividendos Médios = (${values.join(" + ")}) / ${values.length}`,
    `Dividendos ${isLtm ? "LTM" : "Médios"} = R$ ${decimal.format(data.dividendos_medios)}`,
    `Preço Justo = ${decimal.format(data.dividendos_medios)} / (${decimal.format(data.taxa_bazin * 100)} / 100)`,
    `Preço Justo = R$ ${decimal.format(data.preco_justo)}`,
    `Margem = ((${decimal.format(data.preco_justo)} - ${decimal.format(data.preco_atual)}) / ${decimal.format(data.preco_atual)}) × 100`,
    `Margem = ${formattedMargin(data.margem_seguranca)}`,
    `Dividend Yield (${data.ano_dividend_yield}) = (${decimal.format(data.dividendos_dividend_yield)} / ${decimal.format(data.preco_atual)}) × 100 = ${decimal.format(data.dividend_yield)}%`,
  ];
  const container = document.getElementById("calculation");
  container.replaceChildren();
  lines.forEach((line) => {
    const row = document.createElement("p");
    row.textContent = line;
    container.appendChild(row);
  });
}

function chartColors() {
  const styles = getComputedStyle(document.body);
  return {
    ink: styles.getPropertyValue("--ink").trim(),
    grid: styles.getPropertyValue("--line").trim(),
    blue: styles.getPropertyValue("--blue").trim(),
    green: styles.getPropertyValue("--green").trim(),
  };
}

function renderCharts(data) {
  if (typeof Chart === "undefined") return;
  const colors = chartColors();
  if (priceChart) priceChart.destroy();
  if (dividendChart) dividendChart.destroy();
  Chart.defaults.color = colors.ink;
  priceChart = new Chart(document.getElementById("price-chart"), {
    type: "bar",
    data: {
      labels: ["Preço atual", "Preço justo Bazin"],
      datasets: [{
        data: [data.preco_atual, data.preco_justo],
        backgroundColor: [colors.blue, colors.green],
        borderRadius: 7,
        maxBarThickness: 72,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => currency.format(context.raw) } } },
      scales: { y: { beginAtZero: true, grid: { color: colors.grid }, ticks: { callback: (value) => currency.format(value) } }, x: { grid: { display: false } } },
    },
  });
  dividendChart = new Chart(document.getElementById("dividend-chart"), {
    type: "bar",
    data: {
      labels: data.dividendos_historicos.map((item) => item.ano),
      datasets: [{
        label: "Dividendos por ação",
        data: data.dividendos_historicos.map((item) => item.valor),
        backgroundColor: colors.green,
        borderRadius: 6,
        maxBarThickness: 52,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (context) => currency.format(context.raw) } } },
      scales: { y: { beginAtZero: true, grid: { color: colors.grid }, ticks: { callback: (value) => currency.format(value) } }, x: { grid: { display: false } } },
    },
  });
}

async function requestJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "Não foi possível concluir a consulta.");
  return data;
}

document.querySelectorAll(".rate-suggestion").forEach((button) => {
  button.addEventListener("click", () => {
    document.getElementById("taxa").value = button.dataset.rate;
  });
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const ticker = document.getElementById("ticker").value.trim().toUpperCase();
  const rate = Number(document.getElementById("taxa").value) / 100;
  const period = document.getElementById("periodo").value;
  if (!ticker) return;

  comparisonRequestId += 1;
  if (document.getElementById("comparison-submit").disabled) {
    comparisonMessage.textContent = "";
  }
  document.getElementById("comparison-submit").disabled = false;
  submitButton.disabled = true;
  document.getElementById("taxa").disabled = true;
  document.getElementById("periodo").disabled = true;
  document.querySelectorAll(".rate-suggestion").forEach((button) => { button.disabled = true; });
  setComparisonTickerButtonsDisabled(true);
  submitButton.textContent = "Consultando...";
  message.textContent = "";
  results.hidden = true;
  skeleton.hidden = false;

  try {
    const data = await requestJson(
      `/api/v1/valuation/${encodeURIComponent(ticker)}?taxa=${encodeURIComponent(rate)}&periodo=${encodeURIComponent(period)}`
    );
    setText("company-name", data.empresa);
    setText("ticker-name", data.ticker);
    setText("current-price", currency.format(data.preco_atual));
    setText("fair-price", currency.format(data.preco_justo));
    setText("safety-margin", formattedMargin(data.margem_seguranca));
    setText("dividend-yield", `${decimal.format(data.dividend_yield)}%`);
    setText("data-source", data.fonte);
    setText("data-price", currency.format(data.preco_atual));
    setText("average-dividends", currency.format(data.dividendos_medios));
    setText("average-dividends-label", data.periodo === "ltm" ? "Dividendos utilizados (LTM)" : "Dividendos médios");
    setText("dividend-chart-caption", data.periodo === "ltm"
      ? "Pagamentos do LTM agrupados por ano; os anos podem ser parciais."
      : data.periodo === "todos"
        ? "Proventos por ano disponível; o ano atual é parcial."
        : "Proventos por ano encerrado, em reais por ação.");
    setText("used-period", periodLabels[data.periodo]);
    setText("ltm-dividends", data.dividendos_ltm === null ? "Indisponível na fonte" : currency.format(data.dividendos_ltm));
    setText("dy-base", `${data.ano_dividend_yield}: ${currency.format(data.dividendos_dividend_yield)}`);
    setText("used-rate", `${decimal.format(data.taxa_bazin * 100)}%`);
    setText("consulted-at", new Intl.DateTimeFormat("pt-BR", { dateStyle: "short", timeStyle: "short" }).format(new Date(data.data_consulta)));
    setText("events-found", data.eventos_encontrados === null ? "Indisponível" : String(data.eventos_encontrados));
    const annualYears = data.resumo_dividendos.anos_analisados;
    setText("years-used", annualYears === null ? "Não se aplica ao LTM" : String(annualYears));
    setText("history-note", data.periodo === "ltm"
      ? "O LTM reúne pagamentos com data informada; veja os avisos sobre a cobertura da fonte."
      : "Ano encerrado não garante cobertura completa da fonte.");
    setText("summary-average", annualYears === null ? "Não se aplica ao LTM" : currency.format(data.dividendos_medios));
    setText("summary-high", data.resumo_dividendos.maior_anual === null ? "Indisponível" : currency.format(data.resumo_dividendos.maior_anual));
    setText("summary-low", data.resumo_dividendos.menor_anual === null ? "Indisponível" : currency.format(data.resumo_dividendos.menor_anual));
    setText("summary-growth", data.resumo_dividendos.crescimento_medio === null ? "Indisponível" : formattedMargin(data.resumo_dividendos.crescimento_medio));
    setText("summary-years", annualYears === null ? "Não se aplica ao LTM" : String(annualYears));
    setText("summary-note", annualYears === null
      ? "O LTM não representa anos civis completos; estatísticas anuais não se aplicam."
      : "Média simples das variações percentuais entre anos consecutivos. Indisponível quando há lacunas ou base zero; anos parciais são incluídos quando selecionados.");
    setText("profile-aggressive", currency.format(data.precos_perfil.agressivo));
    setText("profile-moderate", currency.format(data.precos_perfil.moderado));
    setText("profile-conservative", currency.format(data.precos_perfil.conservador));
    setText("price-difference", `${formattedMargin(data.margem_seguranca)} de diferença entre o preço atual e o preço justo.`);
    renderHistory(data);
    renderCalculation(data);
    showWarnings(data.avisos || []);
    window.lastValuation = data;

    const comparisonTickers = [data.ticker, ...(data.ativos_comparaveis || [])].slice(0, 4);
    const comparisonInput = document.getElementById("comparison-tickers");
    const peerInfo = document.getElementById("peer-info");
    comparisonInput.value = comparisonTickers.join(", ");
    if (data.setor && data.ativos_comparaveis && data.ativos_comparaveis.length) {
      peerInfo.textContent = `Comparação automática do setor ${data.setor}: ${comparisonTickers.join(", ")}.`;
      comparisonForm.requestSubmit();
    } else {
      peerInfo.textContent = `Não há pares setoriais cadastrados para ${data.ticker}; você pode informar os tickers manualmente.`;
      renderComparison([]);
      comparisonMessage.textContent = "";
    }

    const badge = document.getElementById("status-badge");
    badge.textContent = data.status;
    badge.className = `status-badge ${statusClass(data.status)}`;

    results.hidden = false;
    requestAnimationFrame(() => renderCharts(data));
  } catch (error) {
    message.textContent = error instanceof Error ? error.message : "Serviços financeiros indisponíveis no momento.";
  } finally {
    skeleton.hidden = true;
    submitButton.disabled = false;
    document.getElementById("taxa").disabled = false;
    document.getElementById("periodo").disabled = false;
    document.querySelectorAll(".rate-suggestion").forEach((button) => { button.disabled = false; });
    setComparisonTickerButtonsDisabled(false);
    submitButton.textContent = "Calcular valuation";
  }
});

function renderRanking(items) {
  rankingBody.replaceChildren();
  if (!items.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "empty-state";
    cell.textContent = "Nenhum ativo pôde ser consultado. Tente novamente mais tarde.";
    row.appendChild(cell);
    rankingBody.appendChild(row);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("tr");
    const values = [
      item.ticker,
      currency.format(item.preco_atual),
      currency.format(item.preco_justo),
      formattedMargin(item.margem_seguranca),
      `${decimal.format(item.dividend_yield)}%`,
    ];
    values.forEach((value, index) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      if (index === 0) cell.className = "ticker-cell";
      row.appendChild(cell);
    });
    const classification = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = `status-badge table-badge ${statusClass(item.status)}`;
    badge.textContent = item.status;
    classification.appendChild(badge);
    row.appendChild(classification);
    rankingBody.appendChild(row);
  });
}

function sortRanking(items, order) {
  const classifications = {
    "Muito Barata": 0,
    "Barata": 1,
    "Justa": 2,
    "Cara": 3,
    "Muito Cara": 4,
  };
  return [...items].sort((a, b) => {
    if (order === "dy") return b.dividend_yield - a.dividend_yield;
    if (order === "classificacao") {
      return classifications[a.status] - classifications[b.status] || b.margem_seguranca - a.margem_seguranca;
    }
    return b.margem_seguranca - a.margem_seguranca;
  });
}

async function loadRanking() {
  rankingSkeleton.hidden = false;
  rankingMessage.textContent = "";
  document.getElementById("ranking-refresh").disabled = true;
  const rate = Number(document.getElementById("taxa").value) / 100;
  try {
    const period = document.getElementById("periodo").value;
    const data = await requestJson(`/api/v1/ranking?ordem=potencial&taxa=${encodeURIComponent(rate)}&periodo=${encodeURIComponent(period)}`);
    rankingItems = data.itens;
    renderRanking(sortRanking(rankingItems, document.getElementById("ranking-order").value));
    rankingMessage.textContent = resultWarnings(data, period).join(" ");
  } catch (error) {
    rankingMessage.textContent = error instanceof Error ? error.message : "Não foi possível carregar o ranking.";
  } finally {
    rankingSkeleton.hidden = true;
    document.getElementById("ranking-refresh").disabled = false;
  }
}

document.getElementById("ranking-refresh").addEventListener("click", loadRanking);
document.getElementById("ranking-order").addEventListener("change", (event) => {
  if (rankingItems !== null) renderRanking(sortRanking(rankingItems, event.target.value));
});
if (window.location.pathname === "/ranking" && !rankingSection.hidden) {
  window.addEventListener("load", () => {
    window.setTimeout(() => document.getElementById("ranking").scrollIntoView(), 0);
  }, { once: true });
}

function comparisonCell(label, value) {
  const cell = document.createElement("td");
  cell.textContent = value;
  if (label === "Classificação") {
    const badge = document.createElement("span");
    badge.className = `status-badge table-badge ${statusClass(value)}`;
    badge.textContent = value;
    cell.replaceChildren(badge);
  }
  return cell;
}

function renderComparison(items) {
  ["compare-header-0", "compare-header-1", "compare-header-2", "compare-header-3"].forEach((id, index) => {
    const header = document.getElementById(id);
    const item = items[index];
    if (!item) {
      header.textContent = "—";
      return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "comparison-ticker";
    button.textContent = item.ticker;
    button.setAttribute("aria-label", `Analisar ${item.ticker}`);
    button.disabled = submitButton.disabled;
    button.addEventListener("click", () => {
      document.getElementById("ticker").value = item.ticker;
      document.getElementById("calculadora").scrollIntoView();
      form.requestSubmit();
    });
    header.replaceChildren(button);
  });
  comparisonBody.replaceChildren();
  if (!items.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.className = "empty-state";
    cell.textContent = "Não foi possível obter dados dos ativos selecionados.";
    row.appendChild(cell);
    comparisonBody.appendChild(row);
    return;
  }
  const metrics = [
    ["Preço atual", (item) => currency.format(item.preco_atual)],
    ["Preço justo", (item) => currency.format(item.preco_justo)],
    ["Dividend Yield", (item) => `${decimal.format(item.dividend_yield)}%`],
    ["Margem de segurança", (item) => formattedMargin(item.margem_seguranca)],
    ["Classificação", (item) => item.status],
  ];
  metrics.forEach(([label, valueFor]) => {
    const row = document.createElement("tr");
    const heading = document.createElement("th");
    heading.scope = "row";
    heading.textContent = label;
    row.appendChild(heading);
    items.forEach((item) => row.appendChild(comparisonCell(label, valueFor(item))));
    for (let index = items.length; index < 4; index += 1) row.appendChild(comparisonCell(label, "—"));
    comparisonBody.appendChild(row);
  });
}

comparisonForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const tickers = document.getElementById("comparison-tickers").value
    .split(",").map((ticker) => ticker.trim().toUpperCase()).filter(Boolean);
  if (tickers.length < 1 || tickers.length > 4) {
    comparisonMessage.textContent = "Informe de 1 a 4 tickers separados por vírgula.";
    return;
  }
  const requestId = ++comparisonRequestId;
  comparisonMessage.textContent = "Consultando ativos...";
  document.getElementById("comparison-submit").disabled = true;
  const params = new URLSearchParams();
  tickers.forEach((ticker) => params.append("tickers", ticker));
  params.set("taxa", String(Number(document.getElementById("taxa").value) / 100));
  const period = document.getElementById("periodo").value;
  params.set("periodo", period);
  try {
    const data = await requestJson(`/api/v1/comparison?${params.toString()}`);
    if (requestId !== comparisonRequestId) return;
    renderComparison(data.itens);
    const warnings = resultWarnings(data, period);
    comparisonMessage.textContent = warnings.length
      ? warnings.join(" ")
      : `Comparação concluída: ${data.itens.length} ${data.itens.length === 1 ? "ativo" : "ativos"}.`;
  } catch (error) {
    if (requestId !== comparisonRequestId) return;
    comparisonMessage.textContent = error instanceof Error ? error.message : "Não foi possível comparar os ativos.";
  } finally {
    if (requestId === comparisonRequestId) {
      document.getElementById("comparison-submit").disabled = false;
    }
  }
});

const themeToggle = document.getElementById("theme-toggle");
const savedTheme = localStorage.getItem("bazin-theme");
const darkThemeEnabled = savedTheme === "dark";
document.body.dataset.theme = darkThemeEnabled ? "dark" : "light";
themeToggle.setAttribute("aria-label", darkThemeEnabled ? "Ativar tema claro" : "Ativar tema escuro");
themeToggle.addEventListener("click", () => {
  const dark = document.body.dataset.theme !== "dark";
  document.body.dataset.theme = dark ? "dark" : "light";
  localStorage.setItem("bazin-theme", dark ? "dark" : "light");
  themeToggle.setAttribute("aria-label", dark ? "Ativar tema claro" : "Ativar tema escuro");
  if (!results.hidden) {
    const currentData = window.lastValuation;
    if (currentData) renderCharts(currentData);
  }
});

if (!rankingSection.hidden) loadRanking();
