const refreshButton = document.getElementById("cash-yield-refresh");
const statusText = document.getElementById("cash-yield-status");
const messageText = document.getElementById("cash-yield-message");
const body = document.getElementById("cash-yield-body");
const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const POLL_INTERVAL_MS = 3000;
let pollTimer = null;
let currentItems = [];
let emptyText = "";
let sortKey = "posicao";
let sortDirection = "asc";
const panel = document.getElementById("analysis-panel");
const VERDICTS = { aprovada: "Aprovada", atencao: "Atenção", aprovado: "Aprovado", reprovado: "Reprovado", reprovada: "Reprovada" };

function cell(text, className) {
  const element = document.createElement("td");
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function sortedItems() {
  const direction = sortDirection === "asc" ? 1 : -1;
  return [...currentItems].sort((a, b) => {
    const left = a[sortKey];
    const right = b[sortKey];
    if (sortKey === "veredito") return (a.veredito === "aprovada" ? 0 : 1) * direction || a.posicao - b.posicao;
    const result = typeof left === "string" ? left.localeCompare(right, "pt-BR") : left - right;
    return result * direction || a.posicao - b.posicao;
  });
}

function tickerCell(ticker) {
  const element = cell("", "ticker-cell");
  const link = document.createElement("a");
  link.href = `https://investidor10.com.br/acoes/${encodeURIComponent(ticker.toLowerCase())}/`;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.className = "ticker-link";
  link.textContent = ticker;
  link.title = `Abrir ${ticker} no Investidor10`;
  element.appendChild(link);
  return element;
}

function badge(status) {
  const element = document.createElement("span");
  element.className = `badge badge-${status}`;
  element.textContent = VERDICTS[status] || status;
  return element;
}

function verdictCell(item) {
  const element = cell("");
  element.appendChild(badge(item.veredito));
  if (item.alertas.length) element.title = item.alertas.join("\n");
  return element;
}

function debtCell(item) {
  const criterion = item.criterios.find((entry) => entry.nome === "Dívida líquida / EBITDA");
  return cell(criterion && criterion.valor ? criterion.valor : "—");
}

function analysisCell(item) {
  const element = cell("");
  const button = document.createElement("button");
  button.type = "button";
  button.className = "sort-button";
  button.textContent = "Análise";
  button.addEventListener("click", () => showAnalysis(item.ticker, button));
  element.appendChild(button);
  return element;
}

function section(title, children) {
  const wrapper = document.createElement("div");
  wrapper.className = "analysis-section";
  const heading = document.createElement("h4");
  heading.textContent = title;
  wrapper.append(heading, ...children);
  return wrapper;
}

function paragraph(text) {
  const element = document.createElement("p");
  element.textContent = text;
  return element;
}

function list(entries) {
  const element = document.createElement("ul");
  entries.forEach((entry) => {
    const item = document.createElement("li");
    if (typeof entry === "string") {
      item.textContent = entry;
    } else {
      item.append(badge(entry.status), ` ${entry.nome}${entry.valor ? ` (${entry.valor})` : ""}: ${entry.texto}`);
    }
    element.appendChild(item);
  });
  return element;
}

function money(value) {
  return value === null || value === undefined ? "indisponível" : currency.format(value);
}

function renderAnalysis(data) {
  const price = data.preco_teto;
  const title = document.createElement("h3");
  title.append(`${data.ticker} — ${data.empresa} `, badge(data.veredito));
  const margin = (value) => (value === null ? "" : ` (margem ${decimal.format(value)}%)`);
  panel.replaceChildren(
    title,
    section("Resumo executivo / Veredito Bazin", [paragraph(data.resumo), list(data.criterios_principais)]),
    section("Preço-teto e dividendos", [
      list([
        `DPA dos últimos 12 meses: ${money(price.dpa_ltm)} → preço-teto ${money(price.preco_teto_ltm)}${margin(price.margem_ltm)}`,
        `DPA médio de 5 anos: ${money(price.dpa_media_5anos)} → preço-teto ${money(price.preco_teto_media_5anos)}${margin(price.margem_media_5anos)}`,
        `Cenário conservador: ${money(price.cenario_conservador)} · cotação atual ${money(data.preco_atual)} · rendimento mínimo ${decimal.format(price.taxa * 100)}%`,
      ]),
      list(price.observacoes),
    ]),
    section("Saúde financeira e indicadores", [list(data.saude_financeira)]),
    section("Riscos e pontos de atenção", [list(data.riscos)]),
  );
  panel.hidden = false;
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function showAnalysis(ticker, button) {
  button.disabled = true;
  messageText.textContent = "";
  try {
    const response = await fetch(`/api/v1/cash-yield/${encodeURIComponent(ticker)}/analise`);
    if (!response.ok) throw new Error();
    renderAnalysis(await response.json());
  } catch {
    messageText.textContent = `Não foi possível carregar a análise de ${ticker} agora.`;
  } finally {
    button.disabled = false;
  }
}

function renderRows(items, text) {
  currentItems = items;
  emptyText = text;
  drawRows();
}

function drawRows() {
  if (!body) return;
  const items = sortedItems();
  document.querySelectorAll("th[aria-sort]").forEach((header) => {
    const key = header.querySelector("[data-sort]").dataset.sort;
    header.setAttribute("aria-sort", key === sortKey ? (sortDirection === "asc" ? "ascending" : "descending") : "none");
  });
  body.replaceChildren();
  if (!items.length) {
    const row = document.createElement("tr");
    const empty = cell(emptyText, "empty-state");
    empty.colSpan = 10;
    row.appendChild(empty);
    body.appendChild(row);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("tr");
    row.append(
      cell(item.posicao),
      tickerCell(item.ticker),
      cell(item.empresa),
      cell(currency.format(item.preco_atual)),
      cell(`${decimal.format(item.y1)}%`),
      cell(`${decimal.format(item.y1_minimo)}%`),
      cell(item.anos.map((year) => `${year.ano}: ${decimal.format(year.y1)}%`).join(" · ")),
      verdictCell(item),
      debtCell(item),
      analysisCell(item),
    );
    body.appendChild(row);
  });
}

function render(data) {
  const running = data.status === "calculando";
  if (refreshButton) {
    refreshButton.disabled = running;
    refreshButton.textContent = data.status === "vazio" ? "Gerar lista" : "Atualizar lista";
  }
  messageText.textContent = "";
  const parts = [];
  if (running) parts.push(`Analisando ativos: ${data.processados} de ${data.total}...`);
  if (data.atualizado_em) {
    parts.push(
      `Atualizado em ${new Date(data.atualizado_em).toLocaleString("pt-BR")}. `
      + `${data.total_qualificados} de ${data.total_analisados} ativos analisados atenderam aos critérios.`
      + (data.total_reprovados_fundamentos ? ` ${data.total_reprovados_fundamentos} excluídos por endividamento ou balanço.` : ""),
    );
  }
  parts.push(...data.avisos);
  statusText.textContent = parts.join(" ");
  if (body) {
    if (data.status === "vazio") {
      renderRows([], "A lista ainda não foi gerada. Acesse /gerarlista para iniciar a análise.");
    } else if (data.atualizado_em || !running) {
      renderRows(data.itens, "Nenhuma ação atendeu aos critérios nesta análise.");
    }
  }
  clearTimeout(pollTimer);
  if (running) pollTimer = setTimeout(load, POLL_INTERVAL_MS);
}

async function request(url, options) {
  try {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error();
    render(await response.json());
  } catch {
    messageText.textContent = "Não foi possível consultar a seleção agora. Tente novamente.";
    if (refreshButton) refreshButton.disabled = false;
  }
}

function load() {
  return request("/api/v1/cash-yield");
}

document.querySelectorAll("[data-sort]").forEach((button) => {
  button.addEventListener("click", () => {
    const key = button.dataset.sort;
    sortDirection = key === sortKey && sortDirection === "asc" ? "desc" : "asc";
    sortKey = key;
    drawRows();
  });
});

if (refreshButton) {
  refreshButton.addEventListener("click", () => {
    refreshButton.disabled = true;
    request("/api/v1/cash-yield/refresh", { method: "POST" });
  });
}

const themeToggle = document.getElementById("theme-toggle");
const savedTheme = localStorage.getItem("bazin-theme");
const darkThemeEnabled = savedTheme !== "light";
document.body.dataset.theme = darkThemeEnabled ? "dark" : "light";
themeToggle.setAttribute("aria-label", darkThemeEnabled ? "Ativar tema claro" : "Ativar tema escuro");
themeToggle.addEventListener("click", () => {
  const dark = document.body.dataset.theme !== "dark";
  document.body.dataset.theme = dark ? "dark" : "light";
  localStorage.setItem("bazin-theme", dark ? "dark" : "light");
  themeToggle.setAttribute("aria-label", dark ? "Ativar tema claro" : "Ativar tema escuro");
});

load();
