const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const script = readFileSync(join(__dirname, "..", "static", "cash-yield.js"), "utf8");

const item = {
  posicao: 1,
  ticker: "AAAA3",
  empresa: "Empresa AAAA3",
  preco_atual: 10,
  preco_teto: 13.33333333,
  y1: 9,
  y1_minimo: 7,
  veredito: "aprovada",
  criterios: [],
  alertas: [],
};

function setup(data) {
  const document = {
    body: { dataset: {} },
    getElementById: (id) => elements.get(id),
    createElement: () => element(),
    querySelectorAll: () => [],
  };
  const elements = new Map();
  function element() {
    return {
      textContent: "", children: [], listeners: {}, attributes: {}, dataset: {},
      className: "", colSpan: 0, disabled: false, open: false,
      setAttribute(name, value) { this.attributes[name] = value; },
      removeAttribute(name) { delete this.attributes[name]; },
      addEventListener(name, handler) { this.listeners[name] = handler; },
      appendChild(child) { this.children.push(child); return child; },
      append(...nodes) { this.children.push(...nodes); },
      replaceChildren(...nodes) { this.children = nodes; },
      close() { this.open = false; },
      showModal() { this.open = true; },
    };
  }
  for (const id of [
    "cash-yield-refresh", "cash-yield-refresh-pilot", "cash-yield-status", "cash-yield-message",
    "cash-yield-body", "analysis-modal", "analysis-modal-content", "analysis-modal-title",
    "analysis-modal-close", "theme-toggle",
  ]) {
    elements.set(id, element());
  }
  vm.runInNewContext(script, {
    document,
    Intl,
    fetch: () => Promise.resolve({ ok: true, json: async () => data }),
    localStorage: { getItem: () => null, setItem: () => {} },
    setTimeout,
    clearTimeout,
  });
  return elements.get("cash-yield-body");
}

function payload(itens) {
  return {
    status: "pronto",
    processados: itens.length,
    total: itens.length,
    atualizado_em: "2026-11-27T12:00:00Z",
    total_analisados: itens.length,
    total_qualificados: itens.length,
    total_reprovados_fundamentos: 0,
    itens,
    avisos: [],
  };
}

const flush = () => new Promise((resolve) => setImmediate(resolve));

test("linha da tabela mostra preço atual e preço teto em colunas separadas", async () => {
  const body = setup(payload([item]));
  await flush();
  await flush();

  const cells = body.children[0].children;
  assert.equal(cells.length, 9);
  assert.match(cells[2].textContent, /10,00/);
  assert.match(cells[3].textContent, /13,33/);
  assert.match(cells[4].textContent, /9,00%/);
});

test("endpoint de notícias é chamado com ticker e empresa no modal", async () => {
  assert.match(script, /\/noticias/);
  assert.match(script, /Notícias sobre o ativo/);
});

test("estado vazio ocupa as nove colunas da tabela", async () => {
  const body = setup(payload([]));
  await flush();
  await flush();

  assert.equal(body.children[0].children.length, 1);
  assert.equal(body.children[0].children[0].colSpan, 9);
});
