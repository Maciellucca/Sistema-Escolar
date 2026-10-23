/*
 * Filtro de coluna no estilo do Excel: em qualquer <table data-filtro-excel>,
 * os <th data-filtro> viram clicáveis e abrem uma caixinha com
 *   - ordenar A→Z / Z→A,
 *   - campo de pesquisa pra achar valores na lista,
 *   - "(Selecionar tudo)" + uma caixa de marcação por valor distinto da coluna,
 *   - "Limpar filtro" / "OK".
 * O valor de cada célula é o atributo data-filtro-valor (se houver) ou o
 * texto da célula. <th data-filtro-numerico> ordena pelo número do valor
 * (ex: "90%") em vez da ordem alfabética.
 *
 * Como no Excel, o filtro não se reaplica sozinho quando uma célula muda
 * depois (ex: salvar frequência em segundo plano) — a linha só some da
 * vista no próximo "OK" do filtro.
 */
document.addEventListener("DOMContentLoaded", () => {
  const coletor = new Intl.Collator("pt-BR", { sensitivity: "base", numeric: true });
  let popupAberto = null;

  const fecharPopup = () => {
    if (popupAberto) {
      popupAberto.remove();
      popupAberto = null;
    }
  };
  document.addEventListener("mousedown", (ev) => {
    if (popupAberto && !popupAberto.contains(ev.target) && !ev.target.closest("th[data-filtro]")) fecharPopup();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") fecharPopup();
  });
  window.addEventListener("resize", fecharPopup);

  document.querySelectorAll("table[data-filtro-excel]").forEach((tabela) => {
    const corpo = tabela.tBodies[0];
    if (!corpo) return;
    const cabecalhos = [...tabela.tHead.rows[0].cells];
    // índice da coluna -> Set de valores MARCADOS (ausente = sem filtro)
    const filtros = new Map();
    const contador = document.querySelector(`[data-contador-filtro-de="${tabela.id}"]`);

    const valorCelula = (linha, col) => {
      const celula = linha.cells[col];
      if (!celula) return "";
      const v = celula.dataset.filtroValor !== undefined ? celula.dataset.filtroValor : celula.textContent;
      return v.replace(/\s+/g, " ").trim() || "(Vazias)";
    };
    const numero = (v) => {
      const m = v.replace(",", ".").match(/-?\d+(\.\d+)?/);
      return m ? parseFloat(m[0]) : Number.POSITIVE_INFINITY; // texto vai pro fim
    };
    const comparar = (numerico) => (a, b) => {
      if (numerico) {
        const d = numero(a) - numero(b);
        if (d !== 0 && !Number.isNaN(d)) return d;
      }
      return coletor.compare(a, b);
    };

    const aplicar = () => {
      const linhas = [...corpo.rows];
      let visiveis = 0;
      linhas.forEach((linha) => {
        let mostra = true;
        filtros.forEach((marcados, col) => {
          if (!marcados.has(valorCelula(linha, col))) mostra = false;
        });
        linha.hidden = !mostra;
        if (mostra) visiveis += 1;
      });
      cabecalhos.forEach((th, col) => th.classList.toggle("filtro-ativo", filtros.has(col)));
      if (contador) {
        contador.textContent = filtros.size ? `Mostrando ${visiveis} de ${linhas.length}.` : "";
      }
    };

    const ordenar = (col, numerico, decrescente) => {
      const cmp = comparar(numerico);
      const linhas = [...corpo.rows].sort((a, b) => {
        const r = cmp(valorCelula(a, col), valorCelula(b, col));
        return decrescente ? -r : r;
      });
      linhas.forEach((l) => corpo.appendChild(l));
    };

    cabecalhos.forEach((th, col) => {
      if (!th.hasAttribute("data-filtro")) return;
      const numerico = th.hasAttribute("data-filtro-numerico");
      th.classList.add("th-filtravel");
      th.tabIndex = 0;
      th.title = "Clique para filtrar ou ordenar";
      const seta = document.createElement("span");
      seta.className = "th-filtro-seta";
      seta.setAttribute("aria-hidden", "true");
      seta.textContent = "▾";
      th.appendChild(seta);

      const abrir = () => {
        const jaAberto = popupAberto && popupAberto.dataset.col === String(col) && popupAberto.dataset.tabela === tabela.id;
        fecharPopup();
        if (jaAberto) return;

        // valores possíveis = os das linhas que passam pelos OUTROS filtros (como no Excel)
        const valores = new Set();
        [...corpo.rows].forEach((linha) => {
          let passa = true;
          filtros.forEach((marcados, c) => {
            if (c !== col && !marcados.has(valorCelula(linha, c))) passa = false;
          });
          if (passa) valores.add(valorCelula(linha, col));
        });
        const lista = [...valores].sort(comparar(numerico));
        const marcadosAtuais = filtros.get(col);

        const popup = document.createElement("div");
        popup.className = "filtro-excel-popup";
        popup.dataset.col = String(col);
        popup.dataset.tabela = tabela.id;
        popup.innerHTML = `
          <button type="button" class="filtro-excel-acao" data-ordem="asc">${numerico ? "Ordenar do menor para o maior" : "Classificar de A a Z"}</button>
          <button type="button" class="filtro-excel-acao" data-ordem="desc">${numerico ? "Ordenar do maior para o menor" : "Classificar de Z a A"}</button>
          <hr>
          <input type="search" class="filtro-excel-busca" placeholder="Pesquisar">
          <div class="filtro-excel-lista"></div>
          <div class="filtro-excel-rodape">
            <button type="button" class="button-outline" data-limpar>Limpar filtro</button>
            <button type="button" class="button" data-ok>OK</button>
          </div>`;

        const caixaLista = popup.querySelector(".filtro-excel-lista");
        const criarOpcao = (rotulo, valor, marcado) => {
          const label = document.createElement("label");
          label.className = "filtro-excel-opcao";
          const cb = document.createElement("input");
          cb.type = "checkbox";
          cb.checked = marcado;
          if (valor !== null) cb.value = valor;
          label.append(cb, document.createTextNode(` ${rotulo}`));
          caixaLista.appendChild(label);
          return cb;
        };
        const todos = criarOpcao("(Selecionar tudo)", null, true);
        todos.parentElement.classList.add("filtro-excel-todos");
        const caixas = lista.map((v) => criarOpcao(v, v, !marcadosAtuais || marcadosAtuais.has(v)));

        const visiveisNaLista = () => caixas.filter((cb) => !cb.parentElement.hidden);
        const sincronizarTodos = () => {
          const vis = visiveisNaLista();
          const n = vis.filter((cb) => cb.checked).length;
          todos.checked = vis.length > 0 && n === vis.length;
          todos.indeterminate = n > 0 && n < vis.length;
        };
        sincronizarTodos();
        todos.addEventListener("change", () => {
          visiveisNaLista().forEach((cb) => { cb.checked = todos.checked; });
          sincronizarTodos();
        });
        caixas.forEach((cb) => cb.addEventListener("change", sincronizarTodos));

        const busca = popup.querySelector(".filtro-excel-busca");
        busca.addEventListener("input", () => {
          const termo = busca.value.trim().toLocaleLowerCase("pt-BR");
          // igual ao Excel: pesquisar já deixa marcados só os que batem
          caixas.forEach((cb) => {
            const bate = !termo || cb.value.toLocaleLowerCase("pt-BR").includes(termo);
            cb.parentElement.hidden = !bate;
            cb.checked = bate;
          });
          sincronizarTodos();
        });
        busca.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") {
            ev.preventDefault();
            popup.querySelector("[data-ok]").click();
          }
        });

        popup.querySelectorAll("[data-ordem]").forEach((b) => {
          b.addEventListener("click", () => {
            ordenar(col, numerico, b.dataset.ordem === "desc");
            fecharPopup();
          });
        });
        popup.querySelector("[data-limpar]").addEventListener("click", () => {
          filtros.delete(col);
          aplicar();
          fecharPopup();
        });
        popup.querySelector("[data-ok]").addEventListener("click", () => {
          // com pesquisa digitada, só conta o que está visível na lista
          const escolhidos = new Set(visiveisNaLista().filter((cb) => cb.checked).map((cb) => cb.value));
          if (escolhidos.size === caixas.length) filtros.delete(col);
          else filtros.set(col, escolhidos);
          aplicar();
          fecharPopup();
        });

        document.body.appendChild(popup);
        const r = th.getBoundingClientRect();
        const largura = popup.offsetWidth;
        const esquerda = Math.min(r.left + window.scrollX, window.scrollX + document.documentElement.clientWidth - largura - 8);
        popup.style.left = `${Math.max(8, esquerda)}px`;
        popup.style.top = `${r.bottom + window.scrollY + 4}px`;
        popupAberto = popup;
        busca.focus();
      };

      th.addEventListener("click", abrir);
      th.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          abrir();
        }
      });
    });
  });
});
