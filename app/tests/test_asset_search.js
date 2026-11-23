const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = readFileSync(join(__dirname, "..", "static", "asset-search.js"), "utf8");
const fixtures = [
  { ticker: "BBAS3", symbol: "BBAS3.SA", company: "Banco do Brasil S.A." },
  { ticker: "BBAS3F", symbol: "BBAS3F.SA", company: "BCO BRASIL S.A." },
  { ticker: "PETR4", symbol: "PETR4.SA", company: "Petróleo Brasileiro S.A. - Petrobras" },
  ...Array.from({ length: 12 }, (_, i) => ({
    ticker: `TEST${i}`, symbol: `TEST${i}.SA`, company: "Empresa de teste",
  })),
];

function setup(response) {
  const elements = new Map();
  const document = {
    activeElement: null,
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, element());
      return elements.get(id);
    },
    createElement: () => element(),
  };
  function element() {
    return {
      value: "", textContent: "", children: [], listeners: {}, attributes: {}, hidden: false,
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      addEventListener(name, handler) { this.listeners[name] = handler; },
      appendChild(child) { this.children.push(child); },
      replaceChildren() { this.children = []; },
      focus() { document.activeElement = this; },
      scrollIntoView() {},
    };
  }
  const requests = [];
  const errors = [];
  vm.runInNewContext(script, {
    document,
    fetch: (url) => { requests.push(url); return response; },
    console: { error: (...args) => errors.push(args) },
  });
  return {
    input: document.getElementById("ticker"),
    list: document.getElementById("ticker-suggestions"),
    status: document.getElementById("ticker-search-status"),
    requests, errors,
    ready: () => new Promise((resolve) => setImmediate(resolve)),
  };
}

test("pesquisa local por nome, ticker e símbolo com seleção por teclado ou clique", async () => {
  const ui = setup(Promise.resolve({ ok: true, json: async () => fixtures }));
  await ui.ready();
  ui.input.focus();
  ui.input.value = "banco do brasil";
  ui.input.listeners.input();
  assert.equal(ui.list.children[0].children[0].textContent, "BBAS3");
  assert.equal(ui.list.children[0].children[1].textContent, "Banco do Brasil S.A.");
  assert.equal(ui.list.children[0].children.length, 2);

  let prevented = false;
  ui.input.listeners.keydown({ key: "ArrowDown", preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(ui.input.attributes["aria-activedescendant"], "ticker-option-0");
  ui.input.listeners.keydown({ key: "Enter", preventDefault() {} });
  assert.equal(ui.input.value, "BBAS3");
  assert.equal(ui.list.hidden, true);

  ui.input.value = "petroleo";
  ui.input.listeners.input();
  assert.equal(ui.list.children[0].children[0].textContent, "PETR4");
  ui.list.children[0].listeners.click();
  assert.equal(ui.input.value, "PETR4");
  ui.input.value = "petr4.sa";
  ui.input.listeners.input();
  assert.equal(ui.list.children[0].children[0].textContent, "PETR4");
  ui.input.value = "teste";
  ui.input.listeners.input();
  assert.equal(ui.list.children.length, 10);
  assert.deepEqual(ui.requests, ["/api/v1/assets"]);
});

test("informa falha de catálogo sem bloquear a digitação manual", async () => {
  const ui = setup(Promise.resolve({ ok: false, status: 503 }));
  await ui.ready();
  assert.match(ui.status.textContent, /Catálogo indisponível/);
  assert.equal(ui.errors.length, 1);
  ui.input.value = "BBAS3";
  ui.input.listeners.input();
  assert.equal(ui.input.value, "BBAS3");
  assert.match(ui.status.textContent, /Catálogo indisponível/);
});
