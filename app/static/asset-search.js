(() => {
  const input = document.getElementById("ticker");
  const list = document.getElementById("ticker-suggestions");
  const status = document.getElementById("ticker-search-status");
  const normalize = (value) => value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toUpperCase();
  let assets = null;
  let matches = [];
  let activeIndex = -1;

  function closeSuggestions() {
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    matches = [];
    activeIndex = -1;
  }

  function selectAsset(asset) {
    input.value = asset.ticker;
    status.textContent = "";
    closeSuggestions();
    input.focus();
  }

  function renderSuggestions() {
    closeSuggestions();
    const query = normalize(input.value.trim());
    if (!query || assets === null) return;

    const matching = assets.filter((asset) =>
      asset.searchTicker.includes(query) || asset.searchSymbol.includes(query) || asset.searchCompany.includes(query));
    matches = [
      ...matching.filter((asset) => asset.searchTicker.startsWith(query)),
      ...matching.filter((asset) => !asset.searchTicker.startsWith(query)),
    ].slice(0, 10);
    status.textContent = matches.length ? "" : "Nenhum ativo encontrado no catálogo. Você pode digitar o ticker.";
    matches.forEach((asset, index) => {
      const option = document.createElement("li");
      option.id = `ticker-option-${index}`;
      option.setAttribute("role", "option");
      option.setAttribute("aria-selected", "false");
      const ticker = document.createElement("strong");
      ticker.textContent = asset.ticker;
      const company = document.createElement("span");
      company.textContent = asset.company;
      option.appendChild(ticker);
      option.appendChild(company);
      option.addEventListener("pointerdown", (event) => event.preventDefault());
      option.addEventListener("click", () => selectAsset(asset));
      list.appendChild(option);
    });
    if (matches.length) {
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    }
  }

  function setActive(index) {
    activeIndex = index;
    Array.from(list.children).forEach((option, position) => {
      option.setAttribute("aria-selected", position === activeIndex ? "true" : "false");
    });
    const option = list.children[activeIndex];
    input.setAttribute("aria-activedescendant", option.id);
    option.scrollIntoView({ block: "nearest" });
  }

  input.addEventListener("input", () => {
    if (assets !== null) status.textContent = "";
    renderSuggestions();
  });
  input.addEventListener("focus", renderSuggestions);
  input.addEventListener("blur", closeSuggestions);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeSuggestions();
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (list.hidden) renderSuggestions();
      if (!matches.length) return;
      event.preventDefault();
      const direction = event.key === "ArrowDown" ? 1 : -1;
      const next = activeIndex === -1
        ? (direction === 1 ? 0 : matches.length - 1)
        : (activeIndex + direction + matches.length) % matches.length;
      setActive(next);
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      selectAsset(matches[activeIndex]);
    }
  });

  status.textContent = "Carregando catálogo de ativos...";
  fetch("/api/v1/assets")
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((data) => {
      if (!Array.isArray(data) || !data.length || data.some((asset) =>
        !asset || typeof asset.ticker !== "string" || !asset.ticker
        || typeof asset.symbol !== "string" || !asset.symbol
        || typeof asset.company !== "string" || !asset.company)) {
        throw new Error("Catálogo de ativos inválido.");
      }
      assets = data.map((asset) => ({
        ticker: asset.ticker,
        company: asset.company,
        searchTicker: normalize(asset.ticker),
        searchSymbol: normalize(asset.symbol),
        searchCompany: normalize(asset.company),
      }));
      status.textContent = "";
      if (document.activeElement === input) renderSuggestions();
    })
    .catch((error) => {
      console.error("Não foi possível carregar o catálogo de ativos.", error);
      status.textContent = "Catálogo indisponível. Você pode digitar o ticker manualmente.";
    });
})();
