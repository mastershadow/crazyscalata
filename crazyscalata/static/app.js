// Ricerca nella lista iscritti
(function () {
  const input = document.getElementById("cerca");
  const only = document.getElementById("solo-incompleti");
  const table = document.getElementById("iscritti");
  if (!input || !table) return;
  const fold = (s) => s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const rows = [...table.tBodies[0].rows].filter((r) => r.dataset.search !== undefined);
  function apply() {
    const terms = fold(input.value).split(/\s+/).filter(Boolean);
    for (const r of rows) {
      const text = fold(r.dataset.search);
      const match = terms.every((t) => text.includes(t));
      const inc = !only.checked || r.hasAttribute("data-incompleto");
      r.hidden = !(match && inc);
    }
  }
  input.addEventListener("input", apply);
  only.addEventListener("change", apply);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const first = rows.find((r) => !r.hidden);
      const link = first && first.querySelector("a");
      if (link) location.href = link.href;
    }
  });
})();

// Inserimento a blocchi: Tab inserisce il separatore, Cmd/Ctrl+Invio controlla
(function () {
  const ta = document.getElementById("testo");
  const btn = document.getElementById("controlla");
  if (!ta || !btn) return;
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Tab" && !e.shiftKey && !e.altKey && !e.metaKey && !e.ctrlKey) {
      e.preventDefault();
      ta.setRangeText("\t", ta.selectionStart, ta.selectionEnd, "end");
    } else if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      btn.click();
    }
  });
  // dopo il controllo il fuoco è su "Salva": dalla casella si torna con un clic
  if (document.activeElement === document.body) ta.focus();
})();

// Nuovo iscritto: se nome, cognome e data corrispondono a un'edizione precedente,
// tipologia, sesso e crazy vengono presi da lì (al posto dei valori preselezionati)
(function () {
  const form = document.getElementById("nuovo-iscritto");
  if (!form) return;
  const msg = document.getElementById("storico-msg");
  const field = (n) => form.elements[n];
  const nomi = { tipo: "tipologia", sesso: "sesso", crazy: "crazy" };
  let last = "";
  async function lookup() {
    const q = new URLSearchParams({
      nome: field("nome").value, cognome: field("cognome").value, datanascita: field("datanascita").value,
    });
    if (!field("datanascita").value || q.toString() === last) return;
    last = q.toString();
    let h = null;
    try {
      h = await (await fetch(form.dataset.storico + "?" + q)).json();
    } catch (e) {
      return;
    }
    if (!h) { msg.hidden = true; return; }
    const presi = [];
    for (const k of Object.keys(nomi)) {
      if (!h[k]) continue;
      const radio = form.querySelector(`input[name="${k}"][value="${h[k]}"]`);
      if (radio) { radio.checked = true; presi.push(nomi[k]); }
    }
    if (!presi.length) { msg.hidden = true; return; }
    msg.textContent = `Già iscritto nel ${h.anno}: ${presi.join(", ")} presi da lì. Controlla.`;
    msg.hidden = false;
  }
  for (const n of ["nome", "cognome", "datanascita"]) field(n).addEventListener("change", lookup);
})();

// Nuovo iscritto: ricerca per parole tra gli iscritti degli anni scorsi ("luca pic").
// Scegliendo una persona si compilano nome, cognome, data, tipologia, sesso e crazy;
// se è già iscritta quest'anno si apre la sua scheda.
(function () {
  const form = document.getElementById("nuovo-iscritto");
  const input = document.getElementById("cerca-persona");
  const list = document.getElementById("persone");
  if (!form || !input || !list) return;
  const msg = document.getElementById("storico-msg");
  let items = [], active = 0, timer = null, seq = 0;
  const data = (iso) => (iso ? iso.split("-").reverse().join("/") : "");
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

  function render() {
    list.hidden = !items.length;
    list.innerHTML = items.map((p, i) => {
      const info = p.id
        ? `<span class="tag">già iscritto${p.pettorale ? " · pett. " + p.pettorale : ""}</span>`
        : `<span class="muted">${esc([p.tipo, p.sesso, p.crazy === "SI" ? "crazy" : ""].filter(Boolean).join(" · ").toLowerCase())}</span>
           <span class="tag">${p.anno}</span>`;
      return `<li data-i="${i}" class="${i === active ? "on" : ""}"><b>${esc((p.cognome + " " + p.nome).trim())}</b>
              <span class="muted">${data(p.datanascita)}</span>${info}</li>`;
    }).join("");
  }

  async function search() {
    const q = input.value.trim();
    const my = ++seq;
    if (!q) { items = []; render(); return; }
    try {
      const r = await (await fetch(form.dataset.persone + "?q=" + encodeURIComponent(q))).json();
      if (my !== seq) return;  // risposta di una ricerca vecchia
      items = r; active = 0; render();
    } catch (e) { /* offline o server fermo: niente suggerimenti */ }
  }

  function pick(p) {
    if (p.id) {  // già iscritto quest'anno: niente doppioni, si apre la scheda
      location.href = form.dataset.iscritto.replace(/0$/, p.id);
      return;
    }
    form.elements.nome.value = p.nome || "";
    form.elements.cognome.value = p.cognome || "";
    form.elements.datanascita.value = p.datanascita || "";
    for (const k of ["tipo", "sesso", "crazy"]) {
      const radio = form.querySelector(`input[name="${k}"][value="${p[k] || ""}"]`);
      if (radio) radio.checked = true;
    }
    msg.textContent = `Dati dall'edizione ${p.anno}: controlla, poi pettorale e pagamento.`;
    msg.hidden = false;
    input.value = ""; items = []; render();
    form.elements.pettorale.focus();
  }

  input.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 120); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!items.length) return;
      e.preventDefault();
      active = (active + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
      render();
      list.children[active]?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();  // non inviare il modulo
      if (items[active]) pick(items[active]);
    } else if (e.key === "Escape") {
      items = []; render();
    }
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("li");
    if (li) { e.preventDefault(); pick(items[+li.dataset.i]); }
  });
})();
