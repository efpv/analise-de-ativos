const refreshButton = document.getElementById("cash-yield-refresh");
const statusText = document.getElementById("cash-yield-status");
const messageText = document.getElementById("cash-yield-message");
const body = document.getElementById("cash-yield-body");
const currency = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const decimal = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const POLL_INTERVAL_MS = 3000;
let pollTimer = null;

function cell(text, className) {
  const element = document.createElement("td");
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function renderRows(items, emptyText) {
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
      cell(item.ticker, "ticker-cell"),
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
  refreshButton.disabled = running;
  refreshButton.textContent = data.status === "vazio" ? "Gerar lista" : "Atualizar lista";
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
  if (data.status === "vazio") {
    renderRows([], "Clique em \"Gerar lista\" para analisar as ações do catálogo. A consulta às fontes pode levar vários minutos e o resultado fica salvo para as próximas visitas.");
  } else if (data.atualizado_em || !running) {
    renderRows(data.itens, "Nenhuma ação atendeu aos critérios nesta análise.");
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
    refreshButton.disabled = false;
  }
}

function load() {
  return request("/api/v1/cash-yield");
}

refreshButton.addEventListener("click", () => {
  refreshButton.disabled = true;
  request("/api/v1/cash-yield/refresh", { method: "POST" });
});

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
