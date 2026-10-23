"""
Boletim em PDF na ficha do aluno: todos os bimestres lançados (inclusive
de anos diferentes) num único arquivo.
"""
import io

import pdfplumber


def _aluno_com_notas(db):
    aluno_id = db.execute(
        """INSERT INTO students (codigo_interno, nome, turma, serie, situacao, ra_prodesp, data_nascimento,
               data_transferencia)
           VALUES ('7359540', 'THALLYSON HENRIQUE SENA DIAS FILGUEIRA', '1B', '1º Ano', 'TRANSFERIDO',
                   '000122194196-3/SP', '2019-04-25', '2026-09-17')"""
    ).lastrowid
    linhas = [
        (2025, 4, "Arte", 0, 0, 100.0, "P"),
        (2026, 1, "Arte", 4, 0, 82.6, "S"),
        (2026, 1, "Inglês", 9, 0, 57.1, "NS"),
        (2026, 2, "Arte", 2, 0, 91.3, "S"),
    ]
    for ano, bim, disc, faltas, comp, freq, conceito in linhas:
        db.execute(
            """INSERT INTO grades (student_id, ano, bimestre, disciplina, faltas, compensacoes, frequencia, conceito, origem)
               VALUES (?,?,?,?,?,?,?,?, 'ata')""",
            (aluno_id, ano, bim, disc, faltas, comp, freq, conceito),
        )
    return aluno_id


def _texto_pdf(conteudo):
    with pdfplumber.open(io.BytesIO(conteudo)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def test_boletim_pdf_formato_sgp_uma_folha_por_ano(client, pegar_csrf, criar_admin):
    import config
    from models import get_db, salvar_recomendacao_bimestre

    with get_db() as db:
        aluno_id = _aluno_com_notas(db)
        salvar_recomendacao_bimestre(db, aluno_id, 2026, 1, "Reforçar a leitura em casa.", "Coordenação")

    html = client.get(f"/aluno/{aluno_id}").get_data(as_text=True)
    assert f"/aluno/{aluno_id}/boletim.pdf" in html and "Imprimir boletim (PDF)" in html

    resp = client.get(f"/aluno/{aluno_id}/boletim.pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    with pdfplumber.open(io.BytesIO(resp.data)) as pdf:
        paginas = [p.extract_text() or "" for p in pdf.pages]
    # uma folha por ano letivo, o mais recente primeiro
    assert len(paginas) == 2
    assert "BOLETIM ESCOLAR - 2026" in paginas[0] and "BOLETIM ESCOLAR - 2025" in paginas[1]
    assert "Estudante: THALLYSON HENRIQUE SENA DIAS FILGUEIRA" in paginas[0]  # transferido: sem nº da lista
    assert "Código EOL: 7359540" in paginas[0]
    assert "1° Bim." in paginas[0] and "Final" in paginas[0]
    assert "82.60%" in paginas[0] and "57.10%" in paginas[0] and "NS" in paginas[0]
    assert "1º bimestre: Reforçar a leitura em casa." in paginas[0]
    assert "100.00%" in paginas[1] and "P" in paginas[1]
    if config.ANO_LETIVO == 2026:
        assert "Turma: EF - 1B" in paginas[0]
    assert "Turma: -" in paginas[1]  # ano anterior: o sistema não guarda a turma


def test_boletim_pdf_numero_da_lista_para_aluno_ativo(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        for cod, nome in (("A1", "ANA PRIMEIRA"), ("A2", "BIA SEGUNDA")):
            db.execute(
                "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?, '2A', '2º Ano', 'ATIVO')",
                (cod, nome),
            )
        bia = db.execute("SELECT id FROM students WHERE codigo_interno = 'A2'").fetchone()["id"]
    texto = _texto_pdf(client.get(f"/aluno/{bia}/boletim.pdf").data)
    assert "Estudante: 2 - BIA SEGUNDA" in texto


def test_boletim_pdf_sem_notas_e_aluno_inexistente(client, pegar_csrf, criar_admin, aluno_exemplo):
    resp = client.get(f"/aluno/{aluno_exemplo}/boletim.pdf")
    assert resp.status_code == 200
    assert "ALUNO DE TESTE" in _texto_pdf(resp.data)
    assert client.get("/aluno/999999/boletim.pdf").status_code == 404


def test_boletim_pdf_exige_login(client, app):
    assert client.get("/aluno/1/boletim.pdf").status_code in (302, 401)


def test_boletim_pdf_na_area_do_responsavel_sem_documentos(client, app):
    from models import get_db
    from auth import codigo_responsavel

    with get_db() as db:
        aluno_id = _aluno_com_notas(db)
        codigo = codigo_responsavel(db, aluno_id)
    assert client.get("/responsavel/boletim.pdf").status_code == 302  # sem código, volta pro acesso

    with client.session_transaction() as sess:
        sess["guardian_student_id"] = aluno_id
    html = client.get("/responsavel/boletim").get_data(as_text=True)
    assert "/responsavel/boletim.pdf" in html
    resp = client.get("/responsavel/boletim.pdf")
    assert resp.status_code == 200 and resp.mimetype == "application/pdf"
    texto = _texto_pdf(resp.data)
    assert "THALLYSON HENRIQUE SENA DIAS FILGUEIRA" in texto
    assert "BOLETIM ESCOLAR - 2026" in texto and "BOLETIM ESCOLAR - 2025" in texto
    # sem código EOL, RA e código de acesso
    assert "Código EOL" not in texto and "7359540" not in texto
    assert "000122194196" not in texto and codigo not in texto


def _turma_com_notas(db):
    ids = []
    for i, nome in enumerate(["BRUNA ALVES", "ANA COSTA", "CAIO SEM NOTA"]):
        ids.append(db.execute(
            "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?, '5C', '5º Ano', 'ATIVO')",
            (f"T{i}", nome),
        ).lastrowid)
    db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES ('TX','DANI TRANSFERIDA','5C','5º Ano','TRANSFERIDO')"
    )
    import config
    for sid in ids[:2]:
        for bim in (1, 2):
            db.execute(
                """INSERT INTO grades (student_id, ano, bimestre, disciplina, faltas, compensacoes, frequencia, conceito, origem)
                   VALUES (?,?,?, 'Matemática', ?, 0, 95.0, 'S', 'ata')""",
                (sid, config.ANO_LETIVO, bim, bim * 10 + sid % 10),
            )
    return ids


def test_boletins_da_turma_formato_sgp_uma_folha_por_aluno(client, pegar_csrf, criar_admin):
    """Formato do Boletim Escolar Detalhado do SGP: uma folha por aluno com
    todos os bimestres do ano, e não um bloco por bimestre."""
    import config
    from models import get_db, salvar_recomendacao_bimestre

    with get_db() as db:
        ids = _turma_com_notas(db)
        salvar_recomendacao_bimestre(db, ids[0], config.ANO_LETIVO, 2, "Ótima evolução.", "Coord")

    html = client.get("/turma/5C").get_data(as_text=True)
    assert "/turma/5C/boletins.pdf" in html and "Boletins da turma" in html

    resp = client.get("/turma/5C/boletins.pdf")
    assert resp.status_code == 200 and resp.mimetype == "application/pdf"
    with pdfplumber.open(io.BytesIO(resp.data)) as pdf:
        paginas = [p.extract_text() or "" for p in pdf.pages]
    ano = config.ANO_LETIVO
    # 2 alunos com nota = 2 folhas, + a página dos sem lançamento
    assert len(paginas) == 3
    # número = posição na lista da turma (ordem alfabética, sem os transferidos)
    assert "Estudante: 1 - ANA COSTA" in paginas[0] and "Estudante: 2 - BRUNA ALVES" in paginas[1]
    for p in paginas[:2]:
        assert f"BOLETIM ESCOLAR - {ano}" in p
        assert "1° Bim." in p and "4° Bim." in p and "Final" in p
        assert "Ciclo: Interdisciplinar" in p and "Turma: EF - 5C" in p
        assert "95.00%" in p
        assert "Recomendações à família" in p
    assert "Frequência Global: 95.00%" in paginas[0]
    assert "2º bimestre: Ótima evolução." in paginas[1]
    # sem recomendação própria, vai o texto padrão do SGP
    assert "Busque ir além dos conhecimentos" in paginas[0]
    assert "3 - CAIO SEM NOTA" in paginas[-1]
    assert not any("DANI TRANSFERIDA" in p for p in paginas)


def test_boletins_da_turma_sem_notas_avisa(client, pegar_csrf, criar_admin, aluno_exemplo):
    resp = client.get("/turma/1A/boletins.pdf", follow_redirects=True)
    assert "ainda não tem notas lançadas" in resp.get_data(as_text=True)
