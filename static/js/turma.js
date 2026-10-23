/*
 * Busca ao vivo de alunos e painel de estatísticas da turma.
 * Consome a API interna em /api/turma/<turma>/... (routes/api.py).
 */
document.addEventListener("DOMContentLoaded", () => {
  const campoBusca = document.getElementById("busca-aluno");
  const lista = document.getElementById("lista-alunos");
  const status = document.getElementById("busca-status");
  const painel = document.getElementById("estatisticas-corpo");

  if (!campoBusca || !lista) return;
  const turma = campoBusca.dataset.turma;

  function cartaoAluno(a) {
    const foto = a.foto_url
      ? `<img src="${a.foto_url}" alt="Foto de ${a.nome}">`
      : `<div class="foto-placeholder" role="img" aria-label="Sem foto cadastrada">${a.nome.charAt(0)}</div>`;
    const badgeAee = a.aee ? `<span class="badge badge-aee">AEE</span>` : "";
    const badgeSituacao = a.situacao !== "ATIVO" ? `<span class="badge badge-muted">${a.situacao}</span>` : "";
    return `
      <a class="card aluno-card ${a.situacao !== "ATIVO" ? "inativo" : ""}" href="/aluno/${a.id}">
        <div class="foto-wrap">${foto}</div>
        <div class="aluno-nome">${a.nome}</div>
        ${badgeAee}${badgeSituacao}
      </a>`;
  }

  let ultimaRequisicao = 0;
  async function buscar(termo) {
    const idRequisicao = ++ultimaRequisicao;
    try {
      const resp = await fetch(`/api/turma/${encodeURIComponent(turma)}/alunos?q=${encodeURIComponent(termo)}`);
      if (!resp.ok) throw new Error("Falha na busca");
      const alunos = await resp.json();
      if (idRequisicao !== ultimaRequisicao) return; // resposta antiga, ignora
      lista.innerHTML = alunos.map(cartaoAluno).join("");
      status.textContent = termo
        ? `${alunos.length} aluno(s) encontrado(s) para "${termo}".`
        : "";
    } catch (e) {
      status.textContent = "Não foi possível buscar agora. Tente novamente.";
    }
  }

  let temporizador;
  campoBusca.addEventListener("input", () => {
    clearTimeout(temporizador);
    const termo = campoBusca.value.trim();
    temporizador = setTimeout(() => buscar(termo), 250);
  });

  // Painel de estatísticas (análise de dados a partir das notas importadas)
  async function carregarEstatisticas() {
    try {
      const resp = await fetch(`/api/turma/${encodeURIComponent(turma)}/estatisticas`);
      if (!resp.ok) throw new Error("Falha ao carregar estatísticas");
      const dados = await resp.json();

      if (dados.frequencia_por_bimestre.length === 0 && dados.distribuicao_conceito.length === 0) {
        painel.innerHTML = "<p class='muted'>Ainda não há notas importadas para esta turma.</p>";
        return;
      }

      let html = `<p><strong>${dados.total_alunos}</strong> aluno(s) · <strong>${dados.total_aee}</strong> AEE</p>`;

      if (dados.frequencia_por_bimestre.length) {
        html += "<h3>Frequência média por bimestre</h3><ul class='lista-stats'>";
        dados.frequencia_por_bimestre.forEach((f) => {
          const largura = Math.max(0, Math.min(100, f.media));
          html += `<li><span>${f.ano} · ${f.bimestre}º bim.</span>
                     <span class="barra-stats"><span style="width:${largura}%"></span></span>
                     <span>${f.media}%</span></li>`;
        });
        html += "</ul>";
      }

      if (dados.distribuicao_conceito.length) {
        html += "<h3>Distribuição de conceitos/notas</h3><ul class='lista-stats'>";
        const maior = Math.max(...dados.distribuicao_conceito.map((c) => c.total));
        dados.distribuicao_conceito.forEach((c) => {
          const largura = maior ? Math.round((c.total / maior) * 100) : 0;
          const nomeConceito = { P: "P — Plenamente satisfatório", S: "S — Satisfatório", NS: "NS — Não satisfatório" }[c.conceito] || c.conceito;
          html += `<li><span>${nomeConceito}</span>
                     <span class="barra-stats"><span style="width:${largura}%"></span></span>
                     <span>${c.total}</span></li>`;
        });
        html += "</ul>";
      }

      painel.innerHTML = html;
    } catch (e) {
      painel.innerHTML = "<p class='muted'>Não foi possível carregar as estatísticas agora.</p>";
    }
  }

  carregarEstatisticas();
});
