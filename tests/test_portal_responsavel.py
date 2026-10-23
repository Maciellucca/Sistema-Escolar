import re


def _gerar_token_para(client, pegar_csrf, student_id):
    """O código de acesso (6 números, fixo) aparece na ficha do aluno pra
    admin/secretaria, com o botão Copiar."""
    html = client.get(f"/aluno/{student_id}").get_data(as_text=True)
    m = re.search(r'data-copiar="(\d{6})"', html)
    assert m, "código de acesso não apareceu na ficha do aluno"
    return m.group(1)


def test_responsavel_com_token_valido_ve_o_boletim(client, pegar_csrf, aluno_exemplo):
    token = _gerar_token_para(client, pegar_csrf, aluno_exemplo)

    tok = pegar_csrf("/responsavel/")
    resp = client.post("/responsavel/", data={"token": token, "csrf_token": tok}, follow_redirects=True)
    assert "ALUNO DE TESTE" in resp.get_data(as_text=True)


def test_responsavel_com_token_invalido_e_recusado(client, pegar_csrf):
    tok = pegar_csrf("/responsavel/")
    resp = client.post(
        "/responsavel/", data={"token": "token-que-nao-existe", "csrf_token": tok},
        follow_redirects=True,
    )
    assert "Código inválido" in resp.get_data(as_text=True)


def test_responsavel_nao_ve_dados_de_outro_aluno(app, client, pegar_csrf, aluno_exemplo):
    from models import get_db
    with get_db() as db:
        outro_id = db.execute(
            """INSERT INTO students (codigo_interno, nome, turma, serie, situacao, aee)
               VALUES ('COD2', 'OUTRO ALUNO', '1A', '1º Ano', 'ATIVO', 0)"""
        ).lastrowid

    token = _gerar_token_para(client, pegar_csrf, aluno_exemplo)
    tok = pegar_csrf("/responsavel/")
    client.post("/responsavel/", data={"token": token, "csrf_token": tok})

    resp = client.get("/responsavel/boletim")
    html = resp.get_data(as_text=True)
    assert "ALUNO DE TESTE" in html
    assert "OUTRO ALUNO" not in html


def test_foto_exige_autorizacao(app, client, pegar_csrf, aluno_exemplo):
    from models import get_db
    with get_db() as db:
        db.execute("UPDATE students SET foto_path = 'aluno_%d.png' WHERE id = ?" % aluno_exemplo, (aluno_exemplo,))

    # staff logado acessa
    resp = client.get(f"/fotos/aluno_{aluno_exemplo}.png")
    assert resp.status_code in (200, 404)  # 404 só se o arquivo físico não existir; nunca 403 pro staff

    # cliente sem nenhuma sessão é bloqueado
    anonimo = app.test_client()
    resp2 = anonimo.get(f"/fotos/aluno_{aluno_exemplo}.png")
    assert resp2.status_code == 403


def test_codigo_e_fixo_de_6_numeros_e_aceita_espacos(client, pegar_csrf, aluno_exemplo):
    codigo = _gerar_token_para(client, pegar_csrf, aluno_exemplo)
    assert len(codigo) == 6 and codigo.isdigit()
    assert _gerar_token_para(client, pegar_csrf, aluno_exemplo) == codigo  # não muda ao reabrir a ficha
    assert "Token gerado" not in client.get(f"/aluno/{aluno_exemplo}").get_data(as_text=True)

    responsavel = client.application.test_client()
    tok = _csrf(responsavel, "/responsavel/")
    resp = responsavel.post("/responsavel/", data={"token": f"{codigo[:3]} {codigo[3:]}", "csrf_token": tok},
                            follow_redirects=True)
    assert "ALUNO DE TESTE" in resp.get_data(as_text=True)


def _csrf(cliente, path):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(cliente.get(path).get_data(as_text=True), "html.parser")
    return soup.find("input", {"name": "csrf_token"})["value"]


def test_trocar_codigo_invalida_o_anterior(client, pegar_csrf, aluno_exemplo):
    antigo = _gerar_token_para(client, pegar_csrf, aluno_exemplo)
    tok = pegar_csrf(f"/aluno/{aluno_exemplo}")
    html = client.post(f"/aluno/{aluno_exemplo}/gerar-token", data={"csrf_token": tok},
                       follow_redirects=True).get_data(as_text=True)
    assert "Novo código de acesso gerado" in html
    novo = _gerar_token_para(client, pegar_csrf, aluno_exemplo)
    assert novo != antigo

    responsavel = client.application.test_client()
    resp = responsavel.post("/responsavel/", data={"token": antigo, "csrf_token": _csrf(responsavel, "/responsavel/")},
                            follow_redirects=True)
    assert "Código inválido" in resp.get_data(as_text=True)


def test_token_antigo_continua_valendo_ate_trocar(client, pegar_csrf, aluno_exemplo):
    from auth import new_guardian_token
    from models import get_db
    token, token_hash = new_guardian_token()
    with get_db() as db:
        db.execute("UPDATE students SET guardian_token_hash = ? WHERE id = ?", (token_hash, aluno_exemplo))
    responsavel = client.application.test_client()
    resp = responsavel.post("/responsavel/", data={"token": token, "csrf_token": _csrf(responsavel, "/responsavel/")},
                            follow_redirects=True)
    assert "ALUNO DE TESTE" in resp.get_data(as_text=True)


def test_professor_nao_ve_o_codigo(client, pegar_csrf, aluno_exemplo):
    from models import get_db
    from auth import hash_password
    with get_db() as db:
        db.execute("INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
                   ("prof_r", hash_password("senha-professor-1"), "Prof", "Sala", "professor"))
    client.get("/logout")
    tok = pegar_csrf("/login")
    client.post("/login", data={"username": "prof_r", "senha": "senha-professor-1", "csrf_token": tok})
    html = client.get(f"/aluno/{aluno_exemplo}").get_data(as_text=True)
    assert "data-copiar" not in html
    assert client.post(f"/aluno/{aluno_exemplo}/gerar-token", data={"csrf_token": tok}).status_code in (400, 403)


def test_troca_geral_unica_ao_atualizar_o_sistema(client, pegar_csrf, aluno_exemplo):
    """Bancos que já existiam: na primeira inicialização desta versão, todo
    aluno ganha código novo e os tokens longos antigos param de valer."""
    from auth import new_guardian_token
    from models import get_db, init_db
    token, token_hash = new_guardian_token()
    with get_db() as db:
        db.execute("UPDATE students SET guardian_token_hash = ?, guardian_codigo = '111111' WHERE id = ?",
                   (token_hash, aluno_exemplo))
        outro = db.execute("""INSERT INTO students (codigo_interno, nome, turma, serie, situacao)
                              VALUES ('COD9', 'OUTRO ALUNO', '1A', '1º Ano', 'ATIVO')""").lastrowid
        db.execute("DELETE FROM configuracoes WHERE chave = 'codigos_responsavel_troca_geral'")
    init_db()
    with get_db() as db:
        linhas = {r["id"]: r for r in db.execute("SELECT id, guardian_codigo, guardian_token_hash FROM students")}
    assert linhas[aluno_exemplo]["guardian_token_hash"] is None
    assert linhas[aluno_exemplo]["guardian_codigo"] != "111111"
    assert all(len(r["guardian_codigo"]) == 6 for r in linhas.values())
    assert linhas[aluno_exemplo]["guardian_codigo"] != linhas[outro]["guardian_codigo"]

    responsavel = client.application.test_client()
    resp = responsavel.post("/responsavel/", data={"token": token, "csrf_token": _csrf(responsavel, "/responsavel/")},
                            follow_redirects=True)
    assert "Código inválido" in resp.get_data(as_text=True)

    # não repete em reinícios seguintes
    init_db()
    with get_db() as db:
        assert db.execute("SELECT guardian_codigo FROM students WHERE id = ?", (aluno_exemplo,)).fetchone()[0] \
            == linhas[aluno_exemplo]["guardian_codigo"]


def test_admin_troca_o_codigo_de_todos(client, pegar_csrf, aluno_exemplo):
    antigo = _gerar_token_para(client, pegar_csrf, aluno_exemplo)
    tok = pegar_csrf(f"/aluno/{aluno_exemplo}")
    html = client.post("/responsaveis/trocar-todos-os-codigos", data={"csrf_token": tok, "confirmacao": "sim"},
                       follow_redirects=True).get_data(as_text=True)
    assert "digite TROCAR TODOS" in html
    assert _gerar_token_para(client, pegar_csrf, aluno_exemplo) == antigo
    html = client.post("/responsaveis/trocar-todos-os-codigos", data={"csrf_token": tok, "confirmacao": "trocar todos"},
                       follow_redirects=True).get_data(as_text=True)
    assert "trocado para todos os 1 alunos" in html
    assert _gerar_token_para(client, pegar_csrf, aluno_exemplo) != antigo
