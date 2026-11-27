const categoryInputs = Array.from(document.querySelectorAll('input[name="categoria"]'));
const refreshButton = document.getElementById("news-refresh");
const statusText = document.getElementById("news-status");
const messageText = document.getElementById("news-message");
const list = document.getElementById("news-list");

function selectedCategories() {
  return categoryInputs.filter((input) => input.checked).map((input) => input.value);
}

function card(item) {
  const article = document.createElement("article");
  article.className = "panel news-card";
  const meta = document.createElement("p");
  meta.className = "news-meta";
  const published = item.publicado_em ? new Date(item.publicado_em).toLocaleString("pt-BR") : "";
  meta.textContent = [item.categoria, item.fonte, published].filter(Boolean).join(" · ");
  const title = document.createElement("h3");
  const link = document.createElement("a");
  link.href = item.link;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = item.titulo;
  title.appendChild(link);
  article.append(meta, title);
  if (item.resumo) {
    const summary = document.createElement("p");
    summary.className = "news-summary";
    summary.textContent = item.resumo;
    article.appendChild(summary);
  }
  return article;
}

function render(data) {
  messageText.textContent = "";
  statusText.textContent = data.itens.length
    ? `${data.itens.length} notícia(s) carregada(s).`
    : "Nenhuma notícia para exibir.";
  list.replaceChildren();
  if (!data.itens.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = data.avisos[0] || "Nenhuma notícia encontrada para as categorias selecionadas.";
    list.appendChild(empty);
  } else {
    data.itens.forEach((item) => list.appendChild(card(item)));
  }
  if (data.avisos.length) messageText.textContent = data.avisos.join(" ");
}

async function load() {
  const categories = selectedCategories();
  if (!categories.length) {
    statusText.textContent = "Selecione ao menos uma categoria.";
    messageText.textContent = "";
    list.replaceChildren();
    return;
  }
  refreshButton.disabled = true;
  statusText.textContent = "Carregando notícias...";
  messageText.textContent = "";
  try {
    const params = new URLSearchParams();
    categories.forEach((category) => params.append("categorias", category));
    const response = await fetch(`/api/v1/news?${params.toString()}`);
    if (!response.ok) throw new Error();
    render(await response.json());
  } catch {
    messageText.textContent = "Não foi possível carregar as notícias agora. Tente novamente.";
    statusText.textContent = "";
  } finally {
    refreshButton.disabled = false;
  }
}

categoryInputs.forEach((input) => input.addEventListener("change", load));
refreshButton.addEventListener("click", load);

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