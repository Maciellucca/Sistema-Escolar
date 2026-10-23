"""
Testa o menu lateral do recorte (Início, Arquivo Morto e as importações
no menu da conta) e a tela de configuração da ordem (só admin), incluindo
o caso de uma ordem salva antiga com itens que não existem mais.
"""


def _html(client):
    return client.get("/").get_data(as_text=True)


def _entrar(client, pegar_csrf, username, senha, papel):
    from models import get_db
    from auth import hash_password

    with get_db() as db:
        db.execute(
            "INSERT INTO users (username, password_hash, nome, setor, papel) VALUES (?,?,?,?,?)",
            (username, hash_password(senha), username.title(), "Sala", papel),
        )
    client.get("/logout")
    tok = pegar_csrf("/login")
    client.post("/login", data={"username": username, "senha": senha, "csrf_token": tok})


def test_menu_tem_inicio_no_topo_e_arquivo_morto_em_alunos(client, pegar_csrf, criar_admin):
    html = _html(client)
    assert html.find(">Início<") < html.find('<span class="sidebar-grupo-nome">Alunos</span>') < html.find(">Arquivo Morto<")
    assert 'id="busca-menu"' in html


def test_importacoes_ficam_no_menu_da_conta(client, pegar_csrf, criar_admin):
    html = _html(client)
    barra = html[html.find('id="sidebar-nav"'):html.find("</nav>")]
    assert "Importar notas" not in barra and "Importar alunos" not in barra
    conta = html[html.find('id="menu-conta"'):]
    assert "Importar notas" in conta and "Importar alunos" in conta


def test_tela_de_configuracao_carrega(client, pegar_csrf, criar_admin):
    resp = client.get("/configuracoes/menu-lateral")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Ordem do menu lateral" in html and "Arquivo Morto" in html


def test_mover_item_unico_da_categoria_nao_muda_nada(client, pegar_csrf, criar_admin):
    from models import get_db
    import menu_lateral

    tok = pegar_csrf("/configuracoes/menu-lateral")
    with get_db() as db:
        antes = menu_lateral.ordem_itens(db)
    for direcao in ("subir", "descer"):
        client.post("/configuracoes/menu-lateral", data={"csrf_token": tok, "item": "arquivo_morto", "direcao": direcao})
    with get_db() as db:
        assert menu_lateral.ordem_itens(db) == antes


def test_mover_ultima_categoria_para_baixo_nao_muda_nada(client, pegar_csrf, criar_admin):
    """Usa a última categoria de config.GRUPOS_SIDEBAR dinamicamente, pra
    não quebrar quando uma categoria nova for adicionada."""
    import config
    from models import get_db
    import menu_lateral

    ultima = config.GRUPOS_SIDEBAR[-1]["id"]
    tok = pegar_csrf("/configuracoes/menu-lateral")
    client.post("/configuracoes/menu-lateral", data={"csrf_token": tok, "grupo": ultima, "direcao": "descer"})
    with get_db() as db:
        assert menu_lateral.ordem_grupos(db)[-1] == ultima


def test_ordem_salva_antiga_continua_valendo(client, pegar_csrf, criar_admin):
    """Ordem salva de antes do recorte (com itens que não existem mais):
    os desconhecidos são ignorados e os que faltam aparecem."""
    from models import get_db, set_config

    with get_db() as db:
        set_config(db, "ordem_sidebar", "agenda,inicio,cursos,importar_notas,sptrans,teg,afastamentos")
    html = _html(client)
    assert ">Arquivo Morto<" in html
    assert "SPTrans" not in html and "Agenda de atendimento" not in html


def test_professor_nao_ve_arquivo_morto_nem_importacoes(client, pegar_csrf, criar_admin):
    _entrar(client, pegar_csrf, "prof9", "senha-professor-999", "professor")
    html = _html(client)
    assert '<span class="sidebar-grupo-nome">Alunos</span>' not in html
    assert "Arquivo Morto" not in html
    assert "Importar notas" not in html


def test_professor_nao_acessa_configuracao_de_menu(client, pegar_csrf, criar_admin):
    _entrar(client, pegar_csrf, "prof8", "senha-professor-333", "professor")
    assert client.get("/configuracoes/menu-lateral").status_code == 403


def test_secretaria_tambem_nao_acessa_configuracao_de_menu(client, pegar_csrf, criar_admin):
    """A ordem do menu é só do admin: afeta a navegação de todo mundo,
    decisão de uma pessoa só."""
    _entrar(client, pegar_csrf, "sec1", "senha-secretaria-444", "secretaria")
    assert client.get("/configuracoes/menu-lateral").status_code == 403
