def test_hash_password_nunca_guarda_texto_puro():
    from auth import hash_password, verify_password
    h = hash_password("minha-senha-123")
    assert h != "minha-senha-123"
    assert verify_password("minha-senha-123", h)
    assert not verify_password("senha-errada", h)


def test_guardian_token_salvo_apenas_como_hash():
    from auth import new_guardian_token, hash_token
    token, token_hash = new_guardian_token()
    assert token != token_hash
    assert hash_token(token) == token_hash
    # o hash não deve permitir recuperar o token original (não é reversível
    # nem por meio de um hash "raso": comprimentos e formatos diferentes)
    assert len(token_hash) == 64  # sha256 em hex


def test_csrf_bloqueia_post_sem_token(client):
    resp = client.post("/login", data={"username": "x", "senha": "y"})
    assert resp.status_code == 400


def test_csrf_permite_post_com_token_correto(client, pegar_csrf):
    tok = pegar_csrf("/login")
    resp = client.post("/login", data={"username": "x", "senha": "y", "csrf_token": tok})
    # credenciais erradas -> não é 400 de CSRF, é a página de login de novo (200)
    assert resp.status_code == 200


def test_csrf_bloqueia_token_de_outra_sessao(client, pegar_csrf):
    tok = pegar_csrf("/login")
    # zera os cookies -> nova sessão, sem o token guardado no servidor
    client.delete_cookie("session")
    resp = client.post("/login", data={"username": "x", "senha": "y", "csrf_token": tok})
    assert resp.status_code == 400
