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
    empty.colSpan = 7;
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
      + `${data.total_qualificados} de ${data.total_analisados} ativos analisados atenderam aos critérios.`,
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
