"""
Mudar nome, turma ou nascimento no cadastro do aluno precisa aparecer em
todo lugar que guarda uma cópia desses dados: Arquivo Morto (registro
criado na transferência) e Relatório escolar da Agenda.
"""


def _aluno_transferido(client, pegar_csrf, nome="HELOISA VITORIA SILVA", nasc="2013-10-01"):
    from models import get_db

    with get_db() as db:
        aluno_id = db.execute(
            """INSERT INTO students (codigo_interno, nome, turma, serie, situacao, data_nascimento)
               VALUES ('6148379', ?, '7A', '7º Ano', 'ATIVO', ?)""",
            (nome, nasc),
        ).lastrowid
    tok = pegar_csrf(f"/aluno/{aluno_id}/transferir")
    client.post(f"/aluno/{aluno_id}/transferir", data={"csrf_token": tok, "data_transferencia": "2026-09-15"})
    return aluno_id


def _editar_nome(client, pegar_csrf, aluno_id, nome, nome_social=""):
    tok = pegar_csrf(f"/aluno/{aluno_id}/nome")
    return client.post(
        f"/aluno/{aluno_id}/nome", data={"csrf_token": tok, "nome": nome, "nome_social": nome_social}
    )


def test_editar_nome_atualiza_arquivo_morto(client, pegar_csrf, criar_admin):
    from models import get_db

    aluno_id = _aluno_transferido(client, pegar_csrf)
    with get_db() as db:
        antes = db.execute("SELECT letra, numero, nome FROM arquivo_morto WHERE student_id = ?", (aluno_id,)).fetchone()
    assert antes["nome"] == "HELOISA VITORIA SILVA"

    _editar_nome(client, pegar_csrf, aluno_id, "HELOISA VITORIA SILVA TELES")

    with get_db() as db:
        depois = db.execute("SELECT letra, numero, nome FROM arquivo_morto WHERE student_id = ?", (aluno_id,)).fetchone()
    assert depois["nome"] == "HELOISA VITORIA SILVA TELES"
    # posição física da pasta não muda
    assert (depois["letra"], depois["numero"]) == (antes["letra"], antes["numero"])

    html = client.get("/arquivo-morto/?q=TELES").get_data(as_text=True)
    assert "HELOISA VITORIA SILVA TELES" in html


def test_registro_antigo_desatualizado_e_corrigido_na_inicializacao(client, pegar_csrf, criar_admin):
    """Caso de quem já tinha editado o nome antes da correção: o cadastro
    está certo e o Arquivo Morto ficou com o nome velho."""
    from models import get_db, init_db

    aluno_id = _aluno_transferido(client, pegar_csrf)
    with get_db() as db:
        db.execute("UPDATE students SET nome = 'HELOISA VITORIA SILVA TELES' WHERE id = ?", (aluno_id,))
    init_db()
    with get_db() as db:
        nome = db.execute("SELECT nome FROM arquivo_morto WHERE student_id = ?", (aluno_id,)).fetchone()["nome"]
    assert nome == "HELOISA VITORIA SILVA TELES"


def test_registro_sem_aluno_ligado_nao_e_alterado(client, pegar_csrf, criar_admin):
    from models import get_db, init_db, inserir_arquivo_morto_manual

    with get_db() as db:
        inserir_arquivo_morto_manual(db, "PESSOA ANTIGA", "1970-01-01")
    init_db()
    with get_db() as db:
        assert db.execute("SELECT nome FROM arquivo_morto WHERE nome = 'PESSOA ANTIGA'").fetchone()


def _atendimento_com_relatorio(db, aluno_id, nome_aluno, turma):
    at = db.execute(
        """INSERT INTO atendimentos (data_hora, student_id, nome_responsavel, telefone_contato, assunto,
             responsavel_atendimento, status) VALUES ('2026-09-20 10:00', ?, 'MAE', '11999990000',
             'Conversa', 'Coordenação', 'realizado')""",
        (aluno_id,),
    ).lastrowid
    db.execute(
        "INSERT INTO relatorios_escolares (atendimento_id, nome_aluno, turma, texto) VALUES (?,?,?, 'texto')",
        (at, nome_aluno, turma),
    )
    return at


def test_nome_e_turma_do_relatorio_escolar_acompanham_o_cadastro(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = db.execute(
            "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES ('R1','ANA SOUZA','3B','3º Ano','ATIVO')"
        ).lastrowid
        at = _atendimento_com_relatorio(db, aluno_id, "ANA SOUZA", "3B")

    _editar_nome(client, pegar_csrf, aluno_id, "ANA SOUZA LIMA")
    tok = pegar_csrf(f"/aluno/{aluno_id}/turma")
    client.post(f"/aluno/{aluno_id}/turma", data={"csrf_token": tok, "turma": "3C", "serie": ""})

    with get_db() as db:
        rel = db.execute("SELECT nome_aluno, turma FROM relatorios_escolares WHERE atendimento_id = ?", (at,)).fetchone()
    assert (rel["nome_aluno"], rel["turma"]) == ("ANA SOUZA LIMA", "3C")

    # nome social passa a ser o nome usado no relatório
    _editar_nome(client, pegar_csrf, aluno_id, "ANA SOUZA LIMA", nome_social="ANA LIMA")
    with get_db() as db:
        rel = db.execute("SELECT nome_aluno FROM relatorios_escolares WHERE atendimento_id = ?", (at,)).fetchone()
    assert rel["nome_aluno"] == "ANA LIMA"


def test_relatorio_com_nome_digitado_a_mao_e_preservado(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = db.execute(
            "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES ('R2','BRUNO COSTA','4A','4º Ano','ATIVO')"
        ).lastrowid
        at = _atendimento_com_relatorio(db, aluno_id, "BRUNO C. (IRMÃO DA ANA)", "4A")

    _editar_nome(client, pegar_csrf, aluno_id, "BRUNO COSTA SILVA")
    with get_db() as db:
        rel = db.execute("SELECT nome_aluno FROM relatorios_escolares WHERE atendimento_id = ?", (at,)).fetchone()
    assert rel["nome_aluno"] == "BRUNO C. (IRMÃO DA ANA)"


def test_importacao_de_alunos_propaga_nome_e_nascimento(client, pegar_csrf, criar_admin):
    from models import get_db, propagar_dados_aluno

    aluno_id = _aluno_transferido(client, pegar_csrf, nome="CARLA DIAS", nasc="2012-05-05")
    with get_db() as db:
        antes = db.execute("SELECT id, nome, nome_social, turma FROM students WHERE id = ?", (aluno_id,)).fetchone()
        db.execute("UPDATE students SET nome='CARLA DIAS MOURA', data_nascimento='2012-05-06' WHERE id = ?", (aluno_id,))
        propagar_dados_aluno(db, aluno_id, antes=antes)
        am = db.execute("SELECT nome, data_nascimento FROM arquivo_morto WHERE student_id = ?", (aluno_id,)).fetchone()
    assert (am["nome"], am["data_nascimento"]) == ("CARLA DIAS MOURA", "2012-05-06")
