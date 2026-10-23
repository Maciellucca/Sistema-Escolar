document.addEventListener("DOMContentLoaded", () => {
  // Mensagens fecham só pelo "×" — clicar no texto (ex: pra selecionar e
  // copiar alguma coisa) não some mais com a mensagem.
  document.querySelectorAll(".flash").forEach((el) => {
    const fechar = document.createElement("button");
    fechar.type = "button";
    fechar.className = "flash-fechar";
    fechar.setAttribute("aria-label", "Fechar mensagem");
    fechar.textContent = "×";
    fechar.addEventListener("click", () => el.remove());
    el.appendChild(fechar);
  });

  // Formulários salvos em segundo plano ([data-salvar-ajax]): confirma no
  // próprio formulário, sem recarregar a página nem perder a aba aberta.
  document.querySelectorAll("form[data-salvar-ajax]").forEach((form) => {
    const botao = form.querySelector("button[type=submit]");
    const status = form.querySelector("[data-status]");
    const textoBotao = botao ? botao.textContent : "";
    form.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      if (botao) { botao.disabled = true; botao.textContent = "Salvando…"; }
      try {
        const resp = await fetch(form.action, {
          method: "POST", body: new FormData(form), headers: { "X-Requested-With": "fetch" },
        });
        const dados = await resp.json().catch(() => null);
        if (!resp.ok || !dados || !dados.ok) throw new Error();
        if (status) status.textContent = `${dados.mensagem} Última edição: ${dados.autor || "—"}`;
        if (botao) { botao.textContent = "Salvo ✓"; botao.classList.add("copiado"); }
      } catch (e) {
        if (status) status.textContent = "Não foi possível salvar — tente de novo.";
        if (botao) botao.textContent = textoBotao;
      } finally {
        if (botao) botao.disabled = false;
        setTimeout(() => { if (botao) { botao.textContent = textoBotao; botao.classList.remove("copiado"); } }, 2000);
      }
    });
  });

  // Botões "Copiar": qualquer [data-copiar="texto"] copia o texto e confirma
  // no próprio botão ("Copiado ✓").
  document.querySelectorAll("[data-copiar]").forEach((botao) => {
    const original = botao.textContent;
    botao.addEventListener("click", async () => {
      const texto = botao.dataset.copiar;
      let ok = false;
      try {
        await navigator.clipboard.writeText(texto);
        ok = true;
      } catch (err) {
        // navegador sem acesso à área de transferência (ex: http sem HTTPS)
        const campo = document.createElement("textarea");
        campo.value = texto;
        campo.setAttribute("readonly", "");
        campo.style.position = "fixed";
        campo.style.opacity = "0";
        document.body.appendChild(campo);
        campo.select();
        try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
        campo.remove();
      }
      botao.textContent = ok ? "Copiado ✓" : "Não foi possível copiar";
      botao.classList.toggle("copiado", ok);
      setTimeout(() => {
        botao.textContent = original;
        botao.classList.remove("copiado");
      }, 2000);
    });
  });

  const botaoConta = document.getElementById("botao-conta");
  const menuConta = document.getElementById("menu-conta");
  if (botaoConta && menuConta) {
    const fechar = () => {
      menuConta.hidden = true;
      botaoConta.setAttribute("aria-expanded", "false");
    };
    const abrir = () => {
      menuConta.hidden = false;
      botaoConta.setAttribute("aria-expanded", "true");
    };
    botaoConta.addEventListener("click", (e) => {
      e.stopPropagation();
      menuConta.hidden ? abrir() : fechar();
    });
    document.addEventListener("click", (e) => {
      if (!menuConta.hidden && !menuConta.contains(e.target)) fechar();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") fechar();
    });
  }

  // Menu lateral no celular: gaveta aberta pelo botão ☰ do topo; fecha no
  // fundo escuro, no Esc ou ao escolher uma opção.
  const botaoMenu = document.getElementById("botao-menu");
  const sidebar = document.getElementById("sidebar");
  const fundoMenu = document.getElementById("sidebar-fundo");
  if (botaoMenu && sidebar && fundoMenu) {
    const fecharMenu = (devolverFoco) => {
      if (!sidebar.classList.contains("aberta")) return;
      sidebar.classList.remove("aberta");
      fundoMenu.hidden = true;
      document.body.classList.remove("menu-aberto");
      botaoMenu.setAttribute("aria-expanded", "false");
      botaoMenu.setAttribute("aria-label", "Abrir menu");
      recolherGruposMenu();
      if (devolverFoco) botaoMenu.focus();
    };
    const abrirMenu = () => {
      sidebar.classList.add("aberta");
      fundoMenu.hidden = false;
      document.body.classList.add("menu-aberto");
      botaoMenu.setAttribute("aria-expanded", "true");
      botaoMenu.setAttribute("aria-label", "Fechar menu");
      const ativo = sidebar.querySelector(".sidebar-icon.ativo");
      const alvo = ativo && ativo.offsetParent ? ativo
        : sidebar.querySelector(".contem-ativo .sidebar-grupo-titulo") || sidebar.querySelector("a");
      if (alvo) alvo.focus({ preventScroll: true });
    };
    botaoMenu.addEventListener("click", () => {
      sidebar.classList.contains("aberta") ? fecharMenu(false) : abrirMenu();
    });
    fundoMenu.addEventListener("click", () => fecharMenu(false));
    sidebar.addEventListener("click", (e) => {
      if (e.target.closest("a")) fecharMenu(false);
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") fecharMenu(true);
    });
  }

  // Categorias do menu lateral: começam sempre fechadas, abrem e fecham
  // no título e voltam a fechar sozinhas quando a pessoa sai da barra
  // (mouse sai, foco vai pra página ou a gaveta do celular fecha). O
  // título da categoria da tela atual fica destacado.
  const gruposMenu = document.querySelectorAll(".sidebar-grupo");
  const marcarGrupo = (grupo, fechado) => {
    grupo.classList.toggle("recolhido", fechado);
    grupo.querySelector(".sidebar-grupo-titulo").setAttribute("aria-expanded", fechado ? "false" : "true");
  };
  function recolherGruposMenu() {
    gruposMenu.forEach((grupo) => marcarGrupo(grupo, true));
  }
  try { localStorage.removeItem("menuGruposRecolhidos"); } catch (e) { /* versão antiga guardava isso */ }
  recolherGruposMenu();
  gruposMenu.forEach((grupo) => {
    grupo.querySelector(".sidebar-grupo-titulo").addEventListener("click", () => {
      marcarGrupo(grupo, !grupo.classList.contains("recolhido"));
    });
  });
  const barraLateral = document.getElementById("sidebar");
  if (barraLateral && gruposMenu.length) {
    const naGaveta = () => barraLateral.classList.contains("aberta");
    barraLateral.addEventListener("mouseleave", () => {
      if (naGaveta()) return; // celular: fecha junto com a gaveta
      // o clique num título deixa o foco nele e a barra ficaria aberta
      if (barraLateral.contains(document.activeElement)) document.activeElement.blur();
      recolherGruposMenu();
    });
    barraLateral.addEventListener("focusout", (e) => {
      if (!naGaveta() && !barraLateral.contains(e.relatedTarget) && !barraLateral.matches(":hover")) {
        recolherGruposMenu();
      }
    });
  }

  // Busca no menu: filtra as opções enquanto digita (sem acento e sem
  // diferença de maiúsculas); Enter abre a primeira encontrada.
  const buscaMenu = document.getElementById("busca-menu");
  const navMenu = document.getElementById("sidebar-nav");
  if (buscaMenu && navMenu) {
    const normalizar = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
    const semResultado = navMenu.querySelector(".sidebar-sem-resultado");
    const filtrar = () => {
      const termo = normalizar(buscaMenu.value);
      navMenu.classList.toggle("buscando", termo !== "");
      let total = 0;
      navMenu.querySelectorAll("[data-menu-item]").forEach((link) => {
        const grupo = link.closest(".sidebar-grupo");
        const nomeGrupo = grupo ? normalizar(grupo.querySelector(".sidebar-grupo-nome").textContent) : "";
        const bate = !termo || normalizar(link.textContent).includes(termo) || nomeGrupo.includes(termo);
        link.hidden = !bate;
        if (bate) total += 1;
      });
      navMenu.querySelectorAll(".sidebar-grupo").forEach((grupo) => {
        grupo.hidden = !!termo && !grupo.querySelector("[data-menu-item]:not([hidden])");
      });
      if (semResultado) semResultado.hidden = total > 0;
    };
    buscaMenu.addEventListener("input", filtrar);
    // saiu do menu (clicou na página, Tab pra fora): limpa a busca pra
    // barra recolhida não ficar filtrada
    const barra = buscaMenu.closest(".sidebar");
    barra.addEventListener("focusout", (e) => {
      if (buscaMenu.value && !barra.contains(e.relatedTarget)) {
        buscaMenu.value = "";
        filtrar();
      }
    });
    buscaMenu.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const primeiro = navMenu.querySelector("[data-menu-item]:not([hidden])");
        if (primeiro && buscaMenu.value.trim()) {
          e.preventDefault();
          window.location.href = primeiro.href;
        }
      } else if (e.key === "Escape" && buscaMenu.value) {
        e.stopPropagation();
        buscaMenu.value = "";
        filtrar();
      }
    });
  }

  // Abas genéricas: qualquer [data-tab-btn]/[data-tab-panel] dentro do
  // [data-tabs] mais próximo. Funciona com grupos aninhados (ex: abas da
  // ficha do aluno, com um seletor de bimestre aninhado dentro de uma delas).
  document.querySelectorAll("[data-tab-btn]").forEach((botao) => {
    botao.addEventListener("click", () => {
      const grupo = botao.closest("[data-tabs]");
      if (!grupo) return;
      const alvo = botao.dataset.tabBtn;
      const doGrupo = (seletor) =>
        [...grupo.querySelectorAll(seletor)].filter((el) => el.closest("[data-tabs]") === grupo);

      doGrupo("[data-tab-btn]").forEach((b) => {
        const ativo = b === botao;
        b.classList.toggle("ativa", ativo);
        b.setAttribute("aria-selected", ativo ? "true" : "false");
      });
      doGrupo("[data-tab-panel]").forEach((painel) => {
        painel.hidden = painel.dataset.tabPanel !== alvo;
      });
    });
  });
});
