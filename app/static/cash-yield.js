const refreshButton = document.getElementById("cash-yield-refresh");
const pilotButton = document.getElementById("cash-yield-refresh-pilot");
const statusText = document.getElementById("cash-yield-status");
const messageText = document.getElementById("cash-yield-message");
const body = document.getElementById("cash-yield-body");
const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const POLL_INTERVAL_MS = 3000;
let pollTimer = null;
let currentItems = [];
let emptyText = "";
let sortKey = "y1_minimo";
let sortDirection = "desc";
let newsToken = 0;
const modal = document.getElementById("analysis-modal");
const modalContent = document.getElementById("analysis-modal-content");
const modalTitle = document.getElementById("analysis-modal-title");
const modalClose = document.getElementById("analysis-modal-close");
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
  button.className = "secondary-button table-action";
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

function newsMessage(text) {
  const element = document.createElement("li");
  element.textContent = text;
  return element;
}

function newsItemNode(item) {
  const element = document.createElement("li");
  const link = document.createElement("a");
  link.href = item.link;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = item.titulo;
  const details = document.createElement("span");
  const published = item.publicado_em ? new Date(item.publicado_em).toLocaleDateString("pt-BR") : "";
  details.textContent = ` — ${item.fonte}${published ? ` · ${published}` : ""}${item.resumo ? ` — ${item.resumo}` : ""}`;
  element.append(link, details);
  return element;
}

async function loadNews(ticker, empresa, list, token) {
  try {
    const params = new URLSearchParams();
    if (empresa) params.set("empresa", empresa);
    const query = params.toString();
    const url = `/api/v1/cash-yield/${encodeURIComponent(ticker)}/noticias${query ? `?${query}` : ""}`;
    const response = await fetch(url);
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (token !== newsToken) return;
    const nodes = data.itens.map(newsItemNode);
    if (!nodes.length) nodes.push(newsMessage("Nenhuma notícia recente encontrada nas fontes consultadas."));
    nodes.push(...data.avisos.map((aviso) => newsMessage(aviso)));
    list.replaceChildren(...nodes);
  } catch {
    if (token !== newsToken) return;
    list.replaceChildren(newsMessage("Não foi possível carregar as notícias agora."));
  }
}

function newsSection(data, token) {
  const list = document.createElement("ul");
  list.appendChild(newsMessage("Carregando notícias..."));
  const wrapper = section("Notícias sobre o ativo", [list]);
  loadNews(data.ticker, data.empresa, list, token);
  return wrapper;
}

function renderAnalysis(data, token) {
  const price = data.preco_teto;
  const margin = (value) => (value === null ? "" : ` (margem ${decimal.format(value)}%)`);
  modalTitle.replaceChildren(`${data.ticker} — ${data.empresa} (${data.perfil}) `, badge(data.veredito));
  modalContent.replaceChildren(
    section("Resumo executivo / Veredito Bazin", [paragraph(data.resumo), list(data.criterios_principais)]),
    section("Preço-teto e dividendos", [
      list([
        `DPA dos 3 últimos anos fechados: ${price.dpa_anos.map((year) => `${year.ano}: ${money(year.dpa)}`).join(" · ")} → média ${money(price.dpa_media_3anos)}`,
        `Preço-teto principal (média de 3 anos ÷ ${decimal.format(price.taxa * 100)}%): ${money(price.preco_teto_3anos)}${margin(price.margem_3anos)}`,
        `Últimos 12 meses (LTM): DPA ${money(price.dpa_ltm)} → preço-teto ${money(price.preco_teto_ltm)}${margin(price.margem_ltm)}`,
        `Preço-teto conservador: ${money(price.preco_teto_conservador)}${margin(price.margem_conservador)} · cotação atual ${money(data.preco_atual)}`,
      ]),
      list(price.observacoes),
    ]),
    section("Saúde financeira e indicadores", [list(data.saude_financeira)]),
    section("Riscos e pontos de atenção", [list(data.riscos)]),
    newsSection(data, token),
  );
  if (typeof modal.showModal === "function") {
    if (!modal.open) modal.showModal();
  } else {
    modal.setAttribute("open", "");
  }
}

function closeAnalysis() {
  if (!modal) return;
  if (modal.open) modal.close();
  modal.removeAttribute("open");
}

async function showAnalysis(ticker, button) {
  const token = ++newsToken;
  button.disabled = true;
  messageText.textContent = "";
  try {
    const response = await fetch(`/api/v1/cash-yield/${encodeURIComponent(ticker)}/analise`);
    if (!response.ok) throw new Error();
    renderAnalysis(await response.json(), token);
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
    empty.colSpan = 9;
    row.appendChild(empty);
    body.appendChild(row);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("tr");
    row.append(
      tickerCell(item.ticker),
      cell(item.empresa),
      cell(currency.format(item.preco_atual)),
      cell(money(item.preco_teto)),
      cell(`${decimal.format(item.y1)}%`),
      cell(`${decimal.format(item.y1_minimo)}%`),
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
  if (pilotButton) {
    pilotButton.disabled = running;
    pilotButton.textContent = data.status === "vazio" ? "Gerar piloto" : "Atualizar piloto";
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
    if (pilotButton) pilotButton.disabled = false;
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

function startRefresh(scope) {
  if (refreshButton) refreshButton.disabled = true;
  if (pilotButton) pilotButton.disabled = true;
  request(`/api/v1/cash-yield/refresh?escopo=${scope}`, { method: "POST" });
}

if (refreshButton) {
  refreshButton.addEventListener("click", () => startRefresh("catalogo"));
}

if (pilotButton) {
  pilotButton.addEventListener("click", () => startRefresh("piloto"));
}

if (modalClose) modalClose.addEventListener("click", closeAnalysis);
if (modal) {
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeAnalysis();
  });
  modal.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeAnalysis();
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
