/*
 * Buscas ao vivo da tela inicial: pelo nome do aluno e pelo nome do
 * responsável. Ao escolher um resultado, navega direto pra página do aluno.
 */
document.addEventListener("DOMContentLoaded", () => {
  function ligar(idCampo, idResultados, url, montar, vazioTexto) {
    const campo = document.getElementById(idCampo);
    const resultados = document.getElementById(idResultados);
    if (!campo || !resultados) return;
    let temporizador;

    campo.addEventListener("input", () => {
      clearTimeout(temporizador);
      const termo = campo.value.trim();
      if (termo.length < 2) {
        resultados.innerHTML = "";
        resultados.hidden = true;
        return;
      }
      temporizador = setTimeout(async () => {
        try {
          const resp = await fetch(`${url}?q=${encodeURIComponent(termo)}`);
          const lista = await resp.json();
          resultados.innerHTML = "";
          if (lista.length === 0) {
            const vazio = document.createElement("div");
            vazio.className = "resultado-busca-trocar muted";
            vazio.textContent = vazioTexto;
            resultados.appendChild(vazio);
          }
          lista.forEach((r) => {
            const item = montar(r);
            item.addEventListener("click", () => { window.location.href = `/aluno/${r.id}`; });
            resultados.appendChild(item);
          });
          resultados.hidden = false;
        } catch (err) {
          resultados.hidden = true;
        }
      }, 250);
    });

    document.addEventListener("click", (ev) => {
      if (!campo.contains(ev.target) && !resultados.contains(ev.target)) resultados.hidden = true;
    });
  }

  ligar("busca-aluno-dashboard", "resultados-busca-aluno-dashboard", "/api/alunos", (a) => {
    const item = document.createElement("div");
    item.className = "resultado-busca-trocar";
    item.textContent = `${a.nome} (${a.turma})`;
    return item;
  }, "Nenhum aluno encontrado.");

  ligar("busca-responsavel-dashboard", "resultados-busca-responsavel-dashboard", "/api/responsaveis", (r) => {
    const item = document.createElement("div");
    item.className = "resultado-busca-trocar resultado-busca-responsavel";
    const nome = document.createElement("strong");
    nome.textContent = r.responsavel;
    const aluno = document.createElement("span");
    aluno.textContent = `${r.tipo} de ${r.aluno} (${r.turma})` + (r.ativo ? "" : ` · ${(r.situacao || "inativo").toLowerCase()}`);
    item.append(nome, aluno);
    return item;
  }, "Nenhum responsável encontrado.");
});
