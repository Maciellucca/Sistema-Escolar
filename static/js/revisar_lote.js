/*
 * "Trocar aluno" na tela de conferência de notas: busca ao vivo em vez de
 * um <select> com todos os alunos repetido em cada linha — isso sozinho
 * já deixava a página gigante (900 alunos x 900 opções = ~800 mil <option>)
 * em importações grandes.
 */
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".link-trocar-aluno").forEach((link) => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const info = link.closest(".aluno-casado-info");
      const busca = info.nextElementSibling; // .trocar-aluno-busca
      info.hidden = true;
      busca.hidden = false;
      const campo = busca.querySelector(".campo-busca-trocar");
      campo.value = "";
      campo.focus();
    });
  });

  document.querySelectorAll(".campo-busca-trocar").forEach((campo) => {
    const container = campo.closest(".trocar-aluno-busca");
    const resultados = container.querySelector(".resultados-busca-trocar");
    const turma = campo.dataset.turma;
    const corpo = container.closest(".revisao-aluno-corpo");
    const campoId = corpo.querySelector(".campo-aluno-id");
    const info = container.previousElementSibling; // .aluno-casado-info
    const nomeSpan = info ? info.querySelector(".nome-aluno-casado") : null;

    let temporizador;
    campo.addEventListener("input", () => {
      clearTimeout(temporizador);
      const termo = campo.value.trim();
      if (!termo) {
        resultados.innerHTML = "";
        return;
      }
      temporizador = setTimeout(async () => {
        try {
          const resp = await fetch(`/api/turma/${encodeURIComponent(turma)}/alunos?q=${encodeURIComponent(termo)}`);
          const alunos = await resp.json();
          resultados.innerHTML = alunos
            .map((a) => `<button type="button" class="resultado-busca-trocar" data-id="${a.id}" data-nome="${a.nome}">${a.nome}</button>`)
            .join("");
        } catch (e) {
          resultados.innerHTML = "";
        }
      }, 250);
    });

    resultados.addEventListener("click", (e) => {
      const botao = e.target.closest(".resultado-busca-trocar");
      if (!botao) return;
      campoId.value = botao.dataset.id;
      if (nomeSpan) nomeSpan.textContent = botao.dataset.nome;
      resultados.innerHTML = "";
      container.hidden = true;
      if (info) info.hidden = false;
    });
  });
});
