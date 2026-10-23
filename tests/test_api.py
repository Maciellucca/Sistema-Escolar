def _add_aluno(db, codigo, nome, turma, aee=0):
    return db.execute(
        """INSERT INTO students (codigo_interno, nome, turma, serie, situacao, aee)
           VALUES (?,?,?, '1º Ano', 'ATIVO', ?)""",
        (codigo, nome, turma, aee),
    ).lastrowid


def test_api_exige_login(client):
    resp = client.get("/api/turma/1A/alunos")
    assert resp.status_code in (302, 401)  # redireciona pro login


def test_api_busca_filtra_por_nome(app, client, criar_admin):
    from models import get_db
    with get_db() as db:
        _add_aluno(db, "C1", "AGATHA SANTOS", "1A")
        _add_aluno(db, "C2", "BRUNO SILVA", "1A")
        _add_aluno(db, "C3", "AGATHO PEREIRA", "1A")

    resp = client.get("/api/turma/1A/alunos?q=AGAT")
    dados = resp.get_json()
    nomes = {a["nome"] for a in dados}
    assert nomes == {"AGATHA SANTOS", "AGATHO PEREIRA"}


def test_api_busca_nao_vaza_aluno_de_outra_turma(app, client, criar_admin):
    from models import get_db
    with get_db() as db:
        _add_aluno(db, "C1", "FULANO DE TESTE", "1A")
        _add_aluno(db, "C2", "FULANO DE TESTE", "2B")

    resp = client.get("/api/turma/1A/alunos")
    dados = resp.get_json()
    assert len(dados) == 1


def test_api_estatisticas_agrega_notas_corretamente(app, client, criar_admin):
    from models import get_db
    with get_db() as db:
        aluno1 = _add_aluno(db, "C1", "ALUNO UM", "1A")
        aluno2 = _add_aluno(db, "C2", "ALUNO DOIS", "1A", aee=1)
        for sid, freq, conc in [(aluno1, 90.0, "S"), (aluno2, 70.0, "P")]:
            db.execute(
                """INSERT INTO grades (student_id, ano, bimestre, disciplina, frequencia, conceito)
                   VALUES (?, 2026, 1, 'Matemática', ?, ?)""",
                (sid, freq, conc),
            )

    resp = client.get("/api/turma/1A/estatisticas")
    dados = resp.get_json()
    assert dados["total_alunos"] == 2
    assert dados["total_aee"] == 1
    assert dados["frequencia_por_bimestre"] == [{"ano": 2026, "bimestre": 1, "media": 80.0}]
    conceitos = {c["conceito"]: c["total"] for c in dados["distribuicao_conceito"]}
    assert conceitos == {"S": 1, "P": 1}


def test_api_estatisticas_ignora_aluno_transferido(app, client, criar_admin):
    from models import get_db
    with get_db() as db:
        ativo = _add_aluno(db, "C1", "ALUNO ATIVO", "1A")
        transferido = _add_aluno(db, "C2", "ALUNO TRANSFERIDO", "1A", aee=1)
        db.execute("UPDATE students SET situacao='TRANSFERIDO' WHERE id=?", (transferido,))
        for sid, freq, conc in [(ativo, 90.0, "S"), (transferido, 50.0, "P")]:
            db.execute(
                """INSERT INTO grades (student_id, ano, bimestre, disciplina, frequencia, conceito)
                   VALUES (?, 2026, 1, 'Matemática', ?, ?)""",
                (sid, freq, conc),
            )

    resp = client.get("/api/turma/1A/estatisticas")
    dados = resp.get_json()
    assert dados["total_alunos"] == 1
    assert dados["total_aee"] == 0
    assert dados["frequencia_por_bimestre"] == [{"ano": 2026, "bimestre": 1, "media": 90.0}]
    conceitos = {c["conceito"]: c["total"] for c in dados["distribuicao_conceito"]}
    assert conceitos == {"S": 1}


def test_api_turma_inexistente_da_404(app, client, criar_admin):
    resp = client.get("/api/turma/99Z/estatisticas")
    assert resp.status_code == 404
