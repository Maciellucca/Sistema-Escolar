"""Cadastro manual de aluno (Início e tela da turma)."""
from bs4 import BeautifulSoup


def _post(client, pegar_csrf, **dados):
    tok = pegar_csrf("/aluno/novo")
    base = {"csrf_token": tok, "nome": "", "nome_social": "", "codigo_interno": "", "ra_prodesp": "",
            "data_nascimento": "", "turma": "", "serie": "", "filiacao1": "", "telefone_filiacao1": "",
            "telefone_filiacao2": ""}
    base.update(dados)
    return client.post("/aluno/novo", data=base)


def test_cadastra_aluno_e_abre_a_ficha(client, pegar_csrf, criar_admin):
    from models import get_db
    resp = _post(client, pegar_csrf, nome="  maria  de souza ", codigo_interno="77 001", turma="4 a", serie="4º Ano",
                 data_nascimento="2016-05-10", filiacao1="ana de souza", telefone_filiacao1="(11) 99999-1111", aee="1")
    assert resp.status_code == 302 and "/aluno/" in resp.headers["Location"]
    with get_db() as db:
        a = db.execute("SELECT * FROM students WHERE codigo_interno = '77001'").fetchone()
        tel = db.execute("SELECT telefone_filiacao1 FROM contatos_responsaveis WHERE student_id = ?", (a["id"],)).fetchone()
        log = db.execute("SELECT acao FROM access_log WHERE acao LIKE 'novo_aluno:%'").fetchone()
    assert (a["nome"], a["turma"], a["serie"], a["situacao"], a["aee"]) == ("MARIA DE SOUZA", "4A", "4º Ano", "ATIVO", 1)
    assert a["filiacao1"] == "ANA DE SOUZA" and a["data_nascimento"] == "2016-05-10"
    assert tel["telefone_filiacao1"] == "(11) 99999-1111" and log
    html = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "MARIA DE SOUZA" in html and "cadastrado na turma 4A" in html
    # aparece na turma
    assert "MARIA DE SOUZA" in client.get("/turma/4A").get_data(as_text=True)


def test_recusa_eol_repetido_e_avisa_homonimo(client, pegar_csrf, criar_admin):
    from models import get_db
    _post(client, pegar_csrf, nome="JOAO LIMA", codigo_interno="88001", turma="2B", data_nascimento="2018-01-01")
    html = _post(client, pegar_csrf, nome="OUTRO", codigo_interno="88001", turma="2B").get_data(as_text=True)
    assert "Já existe um aluno com o código EOL 88001" in html
    # mesmo nome e nascimento: pede confirmação
    resp = _post(client, pegar_csrf, nome="joão lima".replace("ã", "a"), turma="3C", data_nascimento="2018-01-01")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and "Já existe um aluno com esse nome" in html and 'name="confirmar_homonimo"' in html
    resp = _post(client, pegar_csrf, nome="JOAO LIMA", turma="3C", data_nascimento="2018-01-01", confirmar_homonimo="1")
    assert resp.status_code == 302
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) c FROM students WHERE nome = 'JOAO LIMA'").fetchone()["c"] == 2


def test_campos_obrigatorios(client, pegar_csrf, criar_admin):
    assert "Informe o nome" in _post(client, pegar_csrf, turma="1A").get_data(as_text=True)
    assert "Informe a turma" in _post(client, pegar_csrf, nome="FULANO").get_data(as_text=True)


def test_botoes_e_permissao(client, pegar_csrf, criar_admin):
    from auth import hash_password
    from models import get_db
    _post(client, pegar_csrf, nome="ALUNO A", turma="5A")
    assert "/aluno/novo" in client.get("/").get_data(as_text=True)
    soup = BeautifulSoup(client.get("/turma/5A").get_data(as_text=True), "html.parser")
    assert soup.find("a", href="/aluno/novo?turma=5A")
    assert 'value="5A"' in client.get("/aluno/novo?turma=5A").get_data(as_text=True)
    with get_db() as db:
        db.execute("INSERT INTO users (username, password_hash, nome, papel) VALUES ('prof', ?, 'Prof', 'professor')",
                   (hash_password("senha-prof-123"),))
    client.get("/logout")
    client.post("/login", data={"username": "prof", "senha": "senha-prof-123", "csrf_token": pegar_csrf("/login")})
    assert client.get("/aluno/novo").status_code == 403
    assert "/aluno/novo" not in client.get("/turma/5A").get_data(as_text=True)
