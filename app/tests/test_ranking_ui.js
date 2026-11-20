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
  return { get, requests, changeOrder, tickers, resolveRequest };
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
