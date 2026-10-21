// Reusable UI widgets.
const CHEVRON =
  '<svg class="chevron" viewBox="0 0 20 20" width="14" height="14" aria-hidden="true"><path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';

/** A searchable multi-select dropdown. Empty selection means "no filter" (all values). */
export class MultiSelect {
  constructor(root, { label, allLabel, options, onChange }) {
    this.root = root;
    this.options = options;
    this.allLabel = allLabel;
    this.label = label;
    this.onChange = onChange;
    this.selected = new Set();
    this.build();
    document.addEventListener("click", (e) => {
      if (!this.root.contains(e.target)) this.close();
    });
    this.root.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !this.pop.hidden) {
        this.close();
        this.button.focus();
      }
    });
  }

  build() {
    this.root.replaceChildren();
    const caption = document.createElement("span");
    caption.className = "field-label";
    caption.textContent = this.label;

    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.className = "ms-btn";
    this.button.setAttribute("aria-haspopup", "true");
    this.button.setAttribute("aria-expanded", "false");
    this.button.innerHTML = `<span class="ms-text"></span><span class="ms-count" hidden></span>${CHEVRON}`;
    this.text = this.button.querySelector(".ms-text");
    this.count = this.button.querySelector(".ms-count");
    this.button.addEventListener("click", () => (this.pop.hidden ? this.open() : this.close()));

    this.pop = document.createElement("div");
    this.pop.className = "ms-pop";
    this.pop.hidden = true;

    this.search = document.createElement("input");
    this.search.type = "search";
    this.search.placeholder = `Search ${this.label.toLowerCase()}…`;
    this.search.setAttribute("aria-label", `Search ${this.label}`);
    this.search.addEventListener("input", () => this.filterList());

    this.list = document.createElement("div");
    this.list.className = "ms-list";
    this.items = this.options.map((opt) => {
      const row = document.createElement("label");
      row.className = "ms-item";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.value = opt.value;
      box.addEventListener("change", () => {
        box.checked ? this.selected.add(opt.value) : this.selected.delete(opt.value);
        this.sync();
        this.onChange(Array.from(this.selected));
      });
      const name = document.createElement("span");
      name.textContent = opt.label;
      row.append(box, name);
      if (opt.hint) {
        const hint = document.createElement("em");
        hint.textContent = opt.hint;
        row.appendChild(hint);
      }
      this.list.appendChild(row);
      return { opt, row, box };
    });

    const foot = document.createElement("div");
    foot.className = "ms-foot";
    this.footText = document.createElement("span");
    const clear = document.createElement("button");
    clear.type = "button";
    clear.className = "link-btn";
    clear.textContent = "Clear";
    clear.addEventListener("click", () => {
      this.selected.clear();
      this.sync();
      this.onChange([]);
    });
    foot.append(this.footText, clear);

    this.pop.append(this.search, this.list, foot);
    this.root.append(caption, this.button, this.pop);
    this.sync();
  }

  filterList() {
    const q = this.search.value.trim().toLowerCase();
    this.items.forEach(({ opt, row }) => {
      row.hidden = q !== "" && !opt.label.toLowerCase().includes(q);
    });
  }

  open() {
    this.pop.hidden = false;
    this.button.setAttribute("aria-expanded", "true");
    this.search.focus();
  }

  close() {
    this.pop.hidden = true;
    this.button.setAttribute("aria-expanded", "false");
  }

  /** Programmatic update (does not call onChange). Unknown values are ignored. */
  setSelected(values) {
    const known = new Set(this.options.map((o) => o.value));
    this.selected = new Set(values.filter((v) => known.has(v)));
    this.sync();
  }

  sync() {
    this.items.forEach(({ opt, box }) => (box.checked = this.selected.has(opt.value)));
    const n = this.selected.size;
    if (n === 0) this.text.textContent = this.allLabel;
    else if (n === 1) this.text.textContent = this.options.find((o) => this.selected.has(o.value))?.label ?? "1 selected";
    else this.text.textContent = `${n} selected`;
    this.count.hidden = n < 2;
    this.count.textContent = n;
    this.footText.textContent = n ? `${n} of ${this.options.length} selected` : `All ${this.options.length} included`;
  }
}
