"""Busca pelo nome do responsável na tela inicial (/api/responsaveis)."""


def _aluno(db, codigo, nome, turma, filiacao, situacao="ATIVO"):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, situacao, filiacao1) VALUES (?,?,?,?,?)",
        (codigo, nome, turma, situacao, filiacao),
    ).lastrowid


def test_busca_pela_filiacao_responsavel_legal_e_sptrans(client, pegar_csrf, criar_admin):
    from models import get_db, salvar_contato_responsavel
    with get_db() as db:
        a = _aluno(db, "R1", "ANA SOUZA", "4A", "MARIA APARECIDA SOUZA")
        b = _aluno(db, "R2", "BRUNO LIMA", "2B", "JOANA LIMA")
        salvar_contato_responsavel(db, b, telefone_filiacao1=None, telefone_filiacao2=None,
                                   responsavel_legal="APARECIDA FERREIRA", telefone_recados=None)
        c = _aluno(db, "R3", "CAIO TRANSFERIDO", "5C", "APARECIDA NUNES", situacao="TRANSFERIDO")
        d = _aluno(db, "R4", "DANI ROCHA", "1A", "PEDRO ROCHA")
        db.execute("INSERT INTO sptrans_dados_aluno (student_id, nome_responsavel) VALUES (?, 'TIA APARECIDA ROCHA')", (d,))
        _aluno(db, "R5", "SEM RELACAO", "1A", "JOSE")

    r = client.get("/api/responsaveis?q=aparecida").get_json()
    por_id = {x["id"]: x for x in r}
    assert set(por_id) == {a, b, c, d}
    assert r[-1]["id"] == c and not r[-1]["ativo"]  # inativos por último
    assert por_id[a]["responsavel"] == "MARIA APARECIDA SOUZA" and por_id[a]["tipo"] == "Filiação"
    assert por_id[b]["responsavel"] == "APARECIDA FERREIRA" and por_id[b]["tipo"] == "Responsável legal"
    assert por_id[d]["tipo"] == "Responsável (SPTrans)" and por_id[d]["turma"] == "1A"
    assert client.get("/api/responsaveis?q=a").get_json() == []


def test_caixa_de_busca_no_inicio(client, pegar_csrf, criar_admin):
    html = client.get("/").get_data(as_text=True)
    assert 'id="busca-aluno-dashboard"' in html and 'id="busca-responsavel-dashboard"' in html
    assert "Buscar pelo nome do responsável" in html


def test_exige_login(client):
    assert client.get("/api/responsaveis?q=maria").status_code == 302
