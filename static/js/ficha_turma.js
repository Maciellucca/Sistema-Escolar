// Coluna lateral da ficha do aluno (templates/_ficha_turma.html): recolher,
// filtrar pelo nome e manter a aba aberta ao passar para outro aluno.
(function () {
  const layout = document.getElementById("ficha-layout");
  const lista = document.getElementById("ficha-turma");
  if (!layout || !lista) return;

  const CHAVE = "ficha-turma-recolhida";
  const botao = document.getElementById("ficha-turma-recolher");
  const recolher = (sim) => {
    layout.classList.toggle("turma-recolhida", sim);
    botao.setAttribute("aria-expanded", String(!sim));
    botao.title = sim ? "Mostrar alunos da turma" : "Recolher lista da turma";
    try { sim ? localStorage.setItem(CHAVE, "1") : localStorage.removeItem(CHAVE); } catch (e) {}
  };
  let recolhida = false;
  try { recolhida = localStorage.getItem(CHAVE) === "1"; } catch (e) {}
  recolher(recolhida);
  botao.addEventListener("click", () => recolher(!layout.classList.contains("turma-recolhida")));

  // deixa o aluno atual visível na lista
  const atual = lista.querySelector("a.atual");
  const corpo = lista.querySelector(".ficha-turma-lista");
  if (atual && corpo && corpo.scrollHeight > corpo.clientHeight) {
    corpo.scrollTop = atual.offsetTop - corpo.offsetTop - corpo.clientHeight / 2 + atual.offsetHeight / 2;
  }

  // trocar de turma: abre a ficha do 1º aluno da turma escolhida (mantendo a aba)
  const trocaTurma = lista.querySelector("[data-trocar-turma]");
  if (trocaTurma) {
    trocaTurma.addEventListener("change", () => {
      if (!trocaTurma.value) return;
      const b = document.querySelector(".abas-nav [data-tab-btn].ativa");
      const url = new URL(trocaTurma.form.action, location.href);
      url.searchParams.set("turma", trocaTurma.value);
      if (b && b.dataset.tabBtn !== "boletim") url.hash = "aba=" + b.dataset.tabBtn;
      location.href = url.toString();
    });
  }

  // filtro por nome (sem acento, sem maiúscula)
  const filtro = document.getElementById("ficha-turma-filtro");
  const vazio = lista.querySelector(".ficha-turma-vazio");
  const normal = (t) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  if (filtro) {
    filtro.addEventListener("input", () => {
      const termo = normal(filtro.value.trim());
      let algum = false;
      lista.querySelectorAll(".ficha-turma-lista li").forEach((li) => {
        const ok = !termo || normal(li.textContent).includes(termo);
        li.hidden = !ok;
        algum = algum || ok;
      });
      if (vazio) vazio.hidden = algum;
    });
  }

  // mantém a aba aberta (Boletim, Dados cadastrais...) ao trocar de aluno
  const abaAtiva = () => {
    const b = document.querySelector(".abas-nav [data-tab-btn].ativa");
    return b ? b.dataset.tabBtn : null;
  };
  document.querySelectorAll("a[data-colega]").forEach((a) => {
    a.addEventListener("click", () => {
      const aba = abaAtiva();
      const url = new URL(a.href, location.href);
      url.hash = aba && aba !== "boletim" ? "aba=" + aba : "";
      a.href = url.toString();
    });
  });
  // depois do app.js ligar as abas (ele também espera o DOMContentLoaded)
  document.addEventListener("DOMContentLoaded", () => {
    const m = location.hash.match(/^#aba=([\w-]+)$/);
    if (!m) return;
    const b = document.querySelector('.abas-nav [data-tab-btn="' + m[1] + '"]');
    if (b) b.click();
  });
})();
