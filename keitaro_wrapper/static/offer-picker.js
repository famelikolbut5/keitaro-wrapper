class OfferPicker extends HTMLElement {
  connectedCallback() {
    if (this.input) return;
    this.input = this.querySelector("[role=combobox]");
    this.valueField = this.querySelector("[name=offer_id]");
    this.popup = this.querySelector(".offer-popup");
    this.list = this.querySelector("[role=listbox]");
    this.status = this.querySelector("[role=status]");
    this.add = this.closest(".add-offer")?.querySelector("[type=submit]");
    this.input.addEventListener("input", () => this.search());
    this.input.addEventListener("focus", () => {
      if (!this.valueField.value && this.input.value.trim()) this.search();
    });
    this.input.addEventListener("blur", () => this.hide());
    this.input.addEventListener("keydown", event => this.navigate(event));
    this.list.addEventListener("mousedown", event => event.preventDefault());
    this.list.addEventListener("click", event => {
      const option = event.target.closest("[role=option]");
      if (option) this.select(option);
    });
  }

  disconnectedCallback() {
    this.close();
  }

  close() {
    clearTimeout(this.timer);
    this.request?.abort();
    this.hide();
  }

  hide() {
    this.popup.hidden = true;
    this.input.setAttribute("aria-expanded", "false");
    this.input.removeAttribute("aria-activedescendant");
    this.index = -1;
  }

  search() {
    this.close();
    const query = this.input.value.trim();
    this.valueField.value = "";
    this.input.setCustomValidity(query ? "Выберите оффер из списка." : "");
    if (this.add) this.add.disabled = true;
    this.closest("form")?.querySelector("[data-offer-required]")?.remove();
    if (query) this.timer = setTimeout(() => this.load(query), 160);
  }

  async load(query) {
    const request = new AbortController();
    this.request = request;
    const params = new URLSearchParams({q: query});
    if (this.dataset.stream) params.set("stream_id", this.dataset.stream);
    this.list.replaceChildren();
    this.status.textContent = "Ищем офферы…";
    const bounds = this.input.getBoundingClientRect();
    const below = window.innerHeight - bounds.bottom;
    const above = bounds.top > below && below < 240;
    this.popup.classList.toggle("opens-up", above);
    this.popup.style.maxHeight = Math.max(72, Math.min(296, (above ? bounds.top : below) - 12)) + "px";
    if (document.activeElement === this.input) {
      this.popup.hidden = false;
      this.input.setAttribute("aria-expanded", "true");
    }
    try {
      const response = await fetch("/api/offers?" + params, {signal: request.signal});
      if (!response.ok) throw new Error();
      const offers = await response.json();
      if (request.signal.aborted) return;
      if (offers.some(offer => String(offer.id) === query)) {
        this.valueField.value = query;
        this.input.setCustomValidity("");
        if (this.add) this.add.disabled = false;
      }
      for (const offer of offers) {
        const option = document.createElement("div");
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.id = this.list.id + "-" + offer.id;
        option.dataset.id = offer.id;
        const name = document.createElement("span");
        const prefix = offer.id + " ";
        name.textContent = offer.name.startsWith(prefix) ? offer.name.slice(prefix.length) : offer.name;
        const id = document.createElement("small");
        id.textContent = "#" + offer.id;
        option.append(name, id);
        this.list.append(option);
      }
      this.status.textContent = offers.length ? "" : "Подходящих офферов нет";
    } catch {
      if (!request.signal.aborted) this.status.textContent = "Не удалось загрузить офферы. Повторите поиск.";
    }
  }

  select(option) {
    this.valueField.value = option.dataset.id;
    this.input.value = option.firstElementChild.textContent;
    this.input.setCustomValidity("");
    if (this.add) this.add.disabled = false;
    this.close();
  }

  navigate(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      this.close();
      return;
    }
    const options = this.list.children;
    if (this.popup.hidden || !options.length) return;
    if (event.key === "Enter" && this.index >= 0) {
      event.preventDefault();
      this.select(options[this.index]);
      return;
    }
    if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    options[this.index]?.setAttribute("aria-selected", "false");
    if (event.key === "ArrowDown") this.index = (this.index + 1) % options.length;
    else this.index = this.index <= 0 ? options.length - 1 : this.index - 1;
    const next = options[this.index];
    next.setAttribute("aria-selected", "true");
    this.input.setAttribute("aria-activedescendant", next.id);
    next.scrollIntoView({block: "nearest"});
  }
}

customElements.define("offer-picker", OfferPicker);
