def test_criar_admin_recusa_chave_errada(client, pegar_csrf):
    tok = pegar_csrf("/login/criar-admin")
    resp = client.post(
        "/login/criar-admin",
        data={
            "username": "novo", "nome": "Fulano", "setor": "Secretaria",
            "senha": "senha12345678", "senha2": "senha12345678",
            "chave": "chave-errada", "csrf_token": tok,
        },
        follow_redirects=True,
    )
    assert "Chave de configuração inválida" in resp.get_data(as_text=True)


def test_criar_admin_aceita_chave_correta(client, pegar_csrf, app):
    import config
    tok = pegar_csrf("/login/criar-admin")
    resp = client.post(
        "/login/criar-admin",
        data={
            "username": "novo", "nome": "Fulano", "setor": "Secretaria",
            "senha": "senha12345678", "senha2": "senha12345678",
            "chave": config.ADMIN_SETUP_KEY, "csrf_token": tok,
        },
        follow_redirects=True,
    )
    assert "criado" in resp.get_data(as_text=True).lower()

    # e consegue logar de fato
    tok2 = pegar_csrf("/login")
    resp2 = client.post(
        "/login", data={"username": "novo", "senha": "senha12345678", "csrf_token": tok2},
        follow_redirects=True,
    )
    assert "Turmas" in resp2.get_data(as_text=True)


def test_criar_admin_recusa_senha_curta(client, pegar_csrf, app):
    import config
    tok = pegar_csrf("/login/criar-admin")
    resp = client.post(
        "/login/criar-admin",
        data={
            "username": "novo2", "nome": "Fulano", "setor": "Secretaria",
            "senha": "123", "senha2": "123",
            "chave": config.ADMIN_SETUP_KEY, "csrf_token": tok,
        },
        follow_redirects=True,
    )
    assert "8 caracteres" in resp.get_data(as_text=True)


def test_login_bloqueia_apos_muitas_tentativas_erradas(client, pegar_csrf, criar_admin):
    username, _ = criar_admin
    client.get("/logout")
    for _ in range(5):
        tok = pegar_csrf("/login")
        client.post("/login", data={"username": username, "senha": "errada", "csrf_token": tok})
    tok = pegar_csrf("/login")
    resp = client.post(
        "/login", data={"username": username, "senha": "errada", "csrf_token": tok},
        follow_redirects=True,
    )
    assert "Muitas tentativas" in resp.get_data(as_text=True)
