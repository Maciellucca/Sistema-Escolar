"""
Usuários da equipe (só admin): criar usuário com senha provisória, gerar
senha provisória para quem esqueceu, desativar/reativar, e a troca de
senha obrigatória no primeiro acesso com a senha provisória.
"""
import re


def _senha_da_tela(html):
    m = re.search(r'<code class="senha-provisoria-valor">([^<]+)</code>', html)
    assert m, "senha provisória não apareceu na tela"
    return m.group(1)


def _entrar(client, pegar_csrf, username, senha):
    client.get("/logout")
    tok = pegar_csrf("/login")
    return client.post("/login", data={"username": username, "senha": senha, "csrf_token": tok})


def test_admin_cria_usuario_e_pessoa_troca_a_senha_no_primeiro_acesso(client, pegar_csrf, criar_admin):
    from models import get_db
    from auth import verify_password

    tok = pegar_csrf("/configuracoes/usuarios")
    resp = client.post("/configuracoes/usuarios/novo", data={
        "csrf_token": tok, "nome": "Maria da Secretaria", "username": "maria.silva", "papel": "secretaria",
        "setor": "Secretaria", "email": "maria@exemplo.com",
    })
    html = resp.get_data(as_text=True)
    assert "Usuário maria.silva criado" in html
    senha = _senha_da_tela(html)
    assert len(senha) == 10
    with get_db() as db:
        u = db.execute("SELECT * FROM users WHERE username = 'maria.silva'").fetchone()
    assert u["trocar_senha"] == 1 and senha not in u["password_hash"]

    # primeiro acesso: vai direto pra troca e não consegue abrir outra página
    resp = _entrar(client, pegar_csrf, "maria.silva", senha)
    assert resp.headers["Location"].endswith("/minha-conta/senha")
    assert client.get("/").headers["Location"].endswith("/minha-conta/senha")
    assert "Crie a sua senha" in client.get("/minha-conta/senha").get_data(as_text=True)

    tok = pegar_csrf("/minha-conta/senha")
    client.post("/minha-conta/senha", data={"csrf_token": tok, "senha_atual": senha,
                                             "nova_senha": "minha-senha-nova-1", "nova_senha2": "minha-senha-nova-1"})
    assert client.get("/").status_code == 200
    with get_db() as db:
        u = db.execute("SELECT * FROM users WHERE username = 'maria.silva'").fetchone()
    assert u["trocar_senha"] == 0 and verify_password("minha-senha-nova-1", u["password_hash"])


def test_senha_provisoria_para_quem_esqueceu(client, pegar_csrf, criar_admin):
    from models import get_db
    from auth import hash_password

    with get_db() as db:
        uid = db.execute(
            "INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
            ("joao", hash_password("senha-antiga-123"), "João Professor", "Sala", "professor"),
        ).lastrowid
    lista = client.get("/configuracoes/usuarios").get_data(as_text=True)
    assert "João Professor" in lista and "senha-antiga" not in lista

    tok = pegar_csrf("/configuracoes/usuarios")
    html = client.post(f"/configuracoes/usuarios/{uid}/senha-provisoria", data={"csrf_token": tok}).get_data(as_text=True)
    senha = _senha_da_tela(html)

    assert _entrar(client, pegar_csrf, "joao", "senha-antiga-123").status_code == 200  # antiga não entra mais
    resp = _entrar(client, pegar_csrf, "joao", senha)
    assert resp.headers["Location"].endswith("/minha-conta/senha")


def test_desativar_e_reativar(client, pegar_csrf, criar_admin):
    from models import get_db
    from auth import hash_password

    with get_db() as db:
        uid = db.execute(
            "INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
            ("ana", hash_password("senha-da-ana-123"), "Ana AEE", "AEE", "aee"),
        ).lastrowid
    tok = pegar_csrf("/configuracoes/usuarios")
    client.post(f"/configuracoes/usuarios/{uid}/ativo", data={"csrf_token": tok})
    with get_db() as db:
        assert db.execute("SELECT ativo FROM users WHERE id = ?", (uid,)).fetchone()["ativo"] == 0
    tok = pegar_csrf("/configuracoes/usuarios")
    client.post(f"/configuracoes/usuarios/{uid}/ativo", data={"csrf_token": tok})
    with get_db() as db:
        assert db.execute("SELECT ativo FROM users WHERE id = ?", (uid,)).fetchone()["ativo"] == 1


def test_admin_nao_desativa_a_si_mesmo_nem_repete_login(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        admin = db.execute("SELECT id, username FROM users WHERE papel = 'admin'").fetchone()
    tok = pegar_csrf("/configuracoes/usuarios")
    html = client.post(f"/configuracoes/usuarios/{admin['id']}/ativo", data={"csrf_token": tok},
                       follow_redirects=True).get_data(as_text=True)
    assert "não pode desativar o seu próprio usuário" in html

    tok = pegar_csrf("/configuracoes/usuarios")
    html = client.post("/configuracoes/usuarios/novo", data={
        "csrf_token": tok, "nome": "Outro", "username": admin["username"].upper(), "papel": "secretaria",
    }).get_data(as_text=True)
    assert "Já existe um usuário" in html and "senha-provisoria-valor" not in html

    tok = pegar_csrf("/configuracoes/usuarios")
    html = client.post("/configuracoes/usuarios/novo", data={
        "csrf_token": tok, "nome": "Com espaço", "username": "com espaco", "papel": "secretaria",
    }).get_data(as_text=True)
    assert "sem espaço" in html


def test_so_admin_acessa(client, pegar_csrf, criar_admin):
    from models import get_db
    from auth import hash_password

    with get_db() as db:
        db.execute(
            "INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
            ("sec9", hash_password("senha-secretaria-999"), "Sec Nove", "Secretaria", "secretaria"),
        )
    assert "Usuários da equipe" in client.get("/").get_data(as_text=True)
    _entrar(client, pegar_csrf, "sec9", "senha-secretaria-999")
    assert client.get("/configuracoes/usuarios").status_code == 403
    assert "Usuários da equipe" not in client.get("/").get_data(as_text=True)


def _usuario(db, username, papel="secretaria", setor=None, ativo=1):
    from auth import hash_password
    return db.execute(
        "INSERT INTO users (username, password_hash, nome, setor, papel, ativo) VALUES (?,?,?,?,?,?)",
        (username, hash_password("senha-do-" + username), username.capitalize(), setor, papel, ativo),
    ).lastrowid


def test_admin_altera_perfil_e_setor(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        uid = _usuario(db, "fabiana", "secretaria")
    tok = pegar_csrf("/configuracoes/usuarios")
    html = client.get("/configuracoes/usuarios").get_data(as_text=True)
    assert f'form="editar-{uid}"' in html and f"/configuracoes/usuarios/{uid}/editar" in html
    resp = client.post(f"/configuracoes/usuarios/{uid}/editar",
                       data={"csrf_token": tok, "papel": "professor", "setor": "Coordenação"}, follow_redirects=True)
    assert "perfil Secretaria → Professor(a) / Coordenação; setor — → Coordenação" in resp.get_data(as_text=True)
    with get_db() as db:
        u = db.execute("SELECT papel, setor FROM users WHERE id = ?", (uid,)).fetchone()
        assert (u["papel"], u["setor"]) == ("professor", "Coordenação")
        log = db.execute("SELECT acao FROM access_log WHERE acao LIKE 'editar_usuario:%'").fetchone()
    assert log and "fabiana:professor" in log["acao"]
    # setor em branco limpa; perfil inválido é recusado
    client.post(f"/configuracoes/usuarios/{uid}/editar", data={"csrf_token": tok, "papel": "professor", "setor": ""})
    client.post(f"/configuracoes/usuarios/{uid}/editar", data={"csrf_token": tok, "papel": "diretor", "setor": "X"})
    with get_db() as db:
        u = db.execute("SELECT papel, setor FROM users WHERE id = ?", (uid,)).fetchone()
    assert (u["papel"], u["setor"]) == ("professor", None)


def test_admin_nao_muda_o_proprio_perfil_so_o_setor(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        eu = db.execute("SELECT id FROM users WHERE username = 'admin_teste'").fetchone()["id"]
    tok = pegar_csrf("/configuracoes/usuarios")
    client.post(f"/configuracoes/usuarios/{eu}/editar", data={"csrf_token": tok, "papel": "secretaria", "setor": "Direção escolar"})
    with get_db() as db:
        u = db.execute("SELECT papel, setor FROM users WHERE id = ?", (eu,)).fetchone()
    assert (u["papel"], u["setor"]) == ("admin", "Direção escolar")


def test_nao_tira_o_ultimo_admin(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        outro = _usuario(db, "vice", "admin")
    tok = pegar_csrf("/configuracoes/usuarios")
    # com dois admins pode rebaixar o outro
    client.post(f"/configuracoes/usuarios/{outro}/editar", data={"csrf_token": tok, "papel": "secretaria", "setor": ""})
    with get_db() as db:
        assert db.execute("SELECT papel FROM users WHERE id = ?", (outro,)).fetchone()["papel"] == "secretaria"


def test_mudanca_de_perfil_vale_na_hora_e_desativado_sai(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        uid = _usuario(db, "joana", "secretaria")
    _entrar(client, pegar_csrf, "joana", "senha-do-joana")
    assert client.get("/arquivo-morto/").status_code == 200
    with get_db() as db:
        db.execute("UPDATE users SET papel = 'professor' WHERE id = ?", (uid,))
    assert client.get("/arquivo-morto/").status_code == 403  # sem precisar sair e entrar de novo
    with get_db() as db:
        db.execute("UPDATE users SET ativo = 0 WHERE id = ?", (uid,))
    resp = client.get("/")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    assert client.get("/").status_code == 302  # sessão encerrada


def test_professor_nao_edita_usuarios(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        _usuario(db, "prof", "professor")
        alvo = _usuario(db, "alvo", "secretaria")
    _entrar(client, pegar_csrf, "prof", "senha-do-prof")
    tok = pegar_csrf("/minha-conta/senha")
    resp = client.post(f"/configuracoes/usuarios/{alvo}/editar", data={"csrf_token": tok, "papel": "admin", "setor": ""})
    assert resp.status_code == 403


def test_aee_nao_e_perfil_de_login(client, pegar_csrf, criar_admin):
    """AEE é a marcação dos alunos da Educação Especial, não perfil de
    login: não aparece para escolher; usuário antigo com 'aee' aparece como
    perfil antigo, pode ter o setor mudado e ser trocado de perfil."""
    from bs4 import BeautifulSoup
    from models import get_db
    with get_db() as db:
        antigo = _usuario(db, "antigo", "aee", setor="Sala")
    soup = BeautifulSoup(client.get("/configuracoes/usuarios").get_data(as_text=True), "html.parser")
    novo = soup.select_one("form[action$='/usuarios/novo'] select[name=papel]")
    assert [o["value"] for o in novo.select("option")] == ["secretaria", "professor", "pot", "direcao", "admin"]
    opcoes = soup.select_one(f"#papel-{antigo}").select("option")
    assert [o["value"] for o in opcoes] == ["secretaria", "professor", "pot", "direcao", "admin", "aee"]
    assert opcoes[-1].get_text() == "AEE (perfil antigo)" and opcoes[-1].has_attr("selected")

    tok = pegar_csrf("/configuracoes/usuarios")
    resp = client.post("/configuracoes/usuarios/novo", data={
        "csrf_token": tok, "nome": "X", "username": "novo.aee", "papel": "aee", "setor": "", "email": ""})
    assert "Escolha o perfil de acesso" in resp.get_data(as_text=True)
    client.post(f"/configuracoes/usuarios/{antigo}/editar", data={"csrf_token": tok, "papel": "aee", "setor": "Recursos"})
    with get_db() as db:
        assert tuple(db.execute("SELECT papel, setor FROM users WHERE id = ?", (antigo,)).fetchone()) == ("aee", "Recursos")
    resp = client.post(f"/configuracoes/usuarios/{antigo}/editar",
                       data={"csrf_token": tok, "papel": "professor", "setor": "Recursos"}, follow_redirects=True)
    assert "perfil AEE (perfil antigo) → Professor(a) / Coordenação" in resp.get_data(as_text=True)
    # não dá para voltar alguém para AEE
    client.post(f"/configuracoes/usuarios/{antigo}/editar", data={"csrf_token": tok, "papel": "aee", "setor": "Recursos"})
    with get_db() as db:
        assert db.execute("SELECT papel FROM users WHERE id = ?", (antigo,)).fetchone()["papel"] == "professor"
