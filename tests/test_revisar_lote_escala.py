"""
Testa a correção da tela de conferência para importações grandes: antes,
um <select> com TODOS os alunos do sistema era repetido em CADA linha da
revisão — em 900 alunos isso virava ~800 mil <option>, deixando a página
gigante (94 MB) e o formulário de confirmação quebrando em produção. Agora
alunos já casados automaticamente usam um campo oculto + busca ao vivo em
vez do <select> gigante.
"""
import io


def _preparar_lote_grande(db, n_turmas=3, alunos_por_turma=20):
    disciplinas = ["Matemática", "Língua Portuguesa", "Arte"]
    lote_id = db.execute(
        "INSERT INTO import_lotes (arquivo, ano, bimestre, criado_por, processando) VALUES ('t.pdf',2026,1,'T',0)"
    ).lastrowid
    total = 0
    for t in range(n_turmas):
        turma = f"{t+1}A"
        for i in range(alunos_por_turma):
            nome = f"ALUNO {t}-{i}"
            sid = db.execute(
                "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?,?,?,?)",
                (f"C{t}-{i}", nome, turma, f"{t+1}º Ano", "ATIVO"),
            ).lastrowid
            aluno_key = f"{turma}||{nome}"
            for d in disciplinas:
                db.execute(
                    """INSERT INTO grades_staging
                         (lote_id, aluno_key, turma_pdf, nome_pdf, student_id, disciplina,
                          faltas, frequencia, conceito, situacao_conselho, incluir)
                       VALUES (?,?,?,?,?,?,?,?,?,?,1)""",
                    (lote_id, aluno_key, turma, nome, sid, d, 1, 90.0, "S", "REGISTRADO"),
                )
            total += 1
    return lote_id, total


def test_tela_de_revisao_nao_repete_lista_de_alunos_por_linha(app, client, criar_admin):
    """O bug real: nenhum <select> deveria mais aparecer para alunos já
    casados automaticamente — só um campo oculto."""
    from models import get_db

    with get_db() as db:
        lote_id, total = _preparar_lote_grande(db, n_turmas=3, alunos_por_turma=20)

    resp = client.get(f"/importar/notas/{lote_id}")
    html = resp.get_data(as_text=True)
    assert "<select" not in html
    assert html.count('class="campo-aluno-id"') == total


def test_pagina_de_revisao_fica_pequena_mesmo_com_muitos_alunos(app, client, criar_admin):
    """Antes da correção, isso crescia O(alunos²) — testando com uma escala
    menor aqui (tempo de teste), mas o mecanismo é o mesmo em qualquer
    tamanho: sem repetir a lista completa de alunos por linha."""
    from models import get_db

    with get_db() as db:
        lote_id, total = _preparar_lote_grande(db, n_turmas=5, alunos_por_turma=30)  # 150 alunos

    resp = client.get(f"/importar/notas/{lote_id}")
    html = resp.get_data(as_text=True)
    # com o bug antigo (O(n²)), 150 alunos já passariam de vários MB;
    # com a correção, cresce só O(n) e fica bem menor
    assert len(html) < 500_000, f"página maior do que deveria: {len(html)} bytes"


def test_confirmar_grava_corretamente_sem_o_select_gigante(app, client, pegar_csrf, criar_admin):
    from bs4 import BeautifulSoup
    from models import get_db

    with get_db() as db:
        lote_id, total = _preparar_lote_grande(db, n_turmas=2, alunos_por_turma=15)  # 30 alunos

    resp = client.get(f"/importar/notas/{lote_id}")
    soup = BeautifulSoup(resp.get_data(as_text=True), "html.parser")
    form = soup.find("form")
    dados = {}
    for inp in form.find_all("input"):
        nome = inp.get("name")
        if not nome:
            continue
        if inp.get("type") == "checkbox":
            if inp.has_attr("checked"):
                dados[nome] = "on"
        else:
            dados[nome] = inp.get("value", "")

    resp2 = client.post(f"/importar/notas/{lote_id}/confirmar", data=dados, follow_redirects=True)
    assert f"Notas gravadas: {total * 3}" in resp2.get_data(as_text=True)  # 3 disciplinas por aluno


def test_busca_trocar_aluno_encontra_aluno_da_turma(app, client, criar_admin):
    """API usada pelo JS de 'trocar aluno' na tela de revisão."""
    from models import get_db

    with get_db() as db:
        db.execute(
            "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES ('Z1','FULANO DA SILVA','1A','1º Ano','ATIVO')"
        )

    resp = client.get("/api/turma/1A/alunos?q=FULANO")
    dados = resp.get_json()
    assert len(dados) == 1
    assert dados[0]["nome"] == "FULANO DA SILVA"
