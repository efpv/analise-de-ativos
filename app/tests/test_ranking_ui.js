const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setupRanking() {
  const elements = new Map();
  function element() {
    return {
      children: [], listeners: {}, dataset: {}, hidden: false, value: "",
      addEventListener(type, handler) { this.listeners[type] = handler; },
      setAttribute() {},
      replaceChildren(...children) { this.children = children; },
      appendChild(child) { this.children.push(child); },
    };
  }
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  get("taxa").value = "6";
  get("periodo").value = "5anos";
  get("ranking-order").value = "potencial";
  const requests = [];
  const pending = [];
  const context = {
    document: {
      getElementById: get,
      createElement: element,
      querySelectorAll: () => [],
      body: { dataset: {} },
    },
    window: { location: { pathname: "/" } },
    localStorage: { getItem: () => null },
    fetch: (url) => {
      requests.push(url);
      return new Promise((resolve) => pending.push(resolve));
    },
    Intl,
  };
  vm.runInNewContext(readFileSync(join(__dirname, "..", "static", "app.js"), "utf8"), context);
  const changeOrder = (order) => {
    const select = get("ranking-order");
    select.value = order;
    select.listeners.change({ target: select });
  };
  const tickers = () => get("ranking-body").children.map((row) => row.children[0].textContent);
  const resolveRequest = async (items) => {
    pending.shift()({ ok: true, json: async () => ({ itens: items, avisos: [] }) });
    await new Promise((resolve) => setImmediate(resolve));
  };
  return { get, requests, changeOrder, tickers, resolveRequest, renderCalculation: context.renderCalculation };
}

test("ordena dados carregados sem consultar novamente e atualiza com os parâmetros atuais", async () => {
  const ui = setupRanking();
  const item = (ticker, margin, dy, status) => ({
    ticker, margem_seguranca: margin, dividend_yield: dy, status,
    preco_atual: 10, preco_justo: 12, avisos: [],
  });

  const items = [
    item("AAA3", 30, 4, "Barata"),
    item("BBB3", 10, 12, "Justa"),
    item("CCC3", 50, 7, "Muito Barata"),
  ];

  ui.changeOrder("dy");
  await ui.resolveRequest(items);
  assert.deepEqual(ui.tickers(), ["BBB3", "CCC3", "AAA3"]);
  ui.changeOrder("classificacao");
  assert.deepEqual(ui.tickers(), ["CCC3", "AAA3", "BBB3"]);
  ui.changeOrder("potencial");
  assert.deepEqual(ui.tickers(), ["CCC3", "AAA3", "BBB3"]);
  assert.equal(ui.requests.length, 1);

  ui.get("taxa").value = "8";
  ui.get("periodo").value = "3anos";
  const refresh = ui.get("ranking-refresh").listeners.click();
  assert.equal(ui.requests.length, 2);
  assert.match(ui.requests[1], /taxa=0\.08/);
  assert.match(ui.requests[1], /periodo=3anos/);
  await ui.resolveRequest(items);
  await refresh;
});

test("apresenta valores com duas casas e a taxa em percentual na memória", async () => {
  const ui = setupRanking();
  await ui.resolveRequest([{
    ticker: "AAA3", margem_seguranca: 12.3456, dividend_yield: 7.8912,
    status: "Barata", preco_atual: 10.1234, preco_justo: 11.5678, avisos: [],
  }]);
  const cells = ui.get("ranking-body").children[0].children;
  assert.equal(cells[3].textContent, "+12,35%");
  assert.equal(cells[4].textContent, "7,89%");

  const data = {
    periodo: "5anos",
    dividendos_historicos: [{ ano: 2025, valor: 0.123456, situacao: "encerrado" }],
    dividendos_medios: 0.123456, taxa_bazin: 0.065,
    preco_justo: 1.899323, preco_atual: 1.234567,
    margem_seguranca: 53.8456, ano_dividend_yield: 2025,
    dividendos_dividend_yield: 0.123456, dividend_yield: 10.0003,
  };
  ui.renderCalculation(data);
  const lines = ui.get("calculation").children.map((row) => row.textContent);
  assert.match(lines[0], /precisão original/);
  assert.ok(lines.includes("2025 = R$ 0,12"));
  assert.ok(lines.includes("Preço Justo = 0,12 / (6,50 / 100)"));
  assert.ok(lines.includes("Margem = +53,85%"));
  assert.ok(lines.includes("Dividend Yield (2025) = (0,12 / 1,23) × 100 = 10,00%"));
  ui.renderCalculation({ ...data, taxa_bazin: 0.001 });
  assert.ok(ui.get("calculation").children.some((row) => row.textContent === "Preço Justo = 0,12 / (0,10 / 100)"));
});
