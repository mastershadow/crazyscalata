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
