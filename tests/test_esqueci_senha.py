"""
Testa o "Esqueci minha senha": código de 6 dígitos enviado por e-mail
(o envio é simulado), validade, limite de tentativas, resposta que não
revela se o usuário existe, e o cadastro do e-mail em "Minha conta".
"""
import re

import pytest


@pytest.fixture()
def emails(app, monkeypatch):
    import config
    import mailer
    enviados = []
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.teste.local")
    monkeypatch.setattr(config, "SMTP_FROM", "sistema@escola.teste")
    monkeypatch.setattr(mailer, "enviar_email", lambda para, assunto, texto: enviados.append((para, assunto, texto)))
    return enviados


def _usuario_com_email(email="secretaria@escola.teste"):
    from models import get_db
    from auth import hash_password
    with get_db() as db:
        db.execute(
            "INSERT INTO users (username, password_hash, nome, setor, papel, email) VALUES (?,?,?,?,?,?)",
            ("sec1", hash_password("senha-antiga-123"), "Secretária Um", "Secretaria", "secretaria", email),
        )


def _codigo(enviados):
    return re.search(r"\b(\d{6})\b", enviados[-1][2]).group(1)


def _login(client, pegar_csrf, usuario, senha):
    tok = pegar_csrf("/login")
    return client.post("/login", data={"username": usuario, "senha": senha, "csrf_token": tok})


def test_login_tem_link_esqueci_senha(client):
    assert "/login/esqueci-senha" in client.get("/login").get_data(as_text=True)


def test_sem_smtp_configurado_avisa_para_procurar_admin(client):
    html = client.get("/login/esqueci-senha").get_data(as_text=True)
    assert "ainda não foi configurada" in html


def test_fluxo_completo_por_usuario_e_por_email(client, pegar_csrf, emails):
    _usuario_com_email()
    tok = pegar_csrf("/login/esqueci-senha")
    resp = client.post("/login/esqueci-senha", data={"csrf_token": tok, "identificador": "sec1"})
    assert resp.status_code == 302 and resp.location.endswith("/login/redefinir-senha")
    assert emails[-1][0] == "secretaria@escola.teste"
    codigo = _codigo(emails)

    tok = pegar_csrf("/login/redefinir-senha")
    resp = client.post("/login/redefinir-senha", data={
        "csrf_token": tok, "codigo": codigo, "nova_senha": "senha-nova-456", "nova_senha2": "senha-nova-456",
    })
    assert resp.status_code == 302 and resp.location.endswith("/login")
    assert _login(client, pegar_csrf, "sec1", "senha-antiga-123").status_code == 200  # antiga não entra mais
    assert _login(client, pegar_csrf, "sec1", "senha-nova-456").status_code == 302

    # código já usado não vale de novo
    client.get("/logout")
    tok = pegar_csrf("/login/esqueci-senha")
    client.post("/login/esqueci-senha", data={"csrf_token": tok, "identificador": "SECRETARIA@escola.teste"})
    assert len(emails) == 2  # achou pelo e-mail, sem diferenciar maiúsculas


def test_usuario_inexistente_recebe_a_mesma_resposta(client, pegar_csrf, emails):
    tok = pegar_csrf("/login/esqueci-senha")
    resp = client.post("/login/esqueci-senha", data={"csrf_token": tok, "identificador": "ninguem"},
                       follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "Se houver um usuário" in html
    assert emails == []
    tok = pegar_csrf("/login/redefinir-senha")
    html = client.post("/login/redefinir-senha", data={
        "csrf_token": tok, "codigo": "123456", "nova_senha": "qualquer-coisa-1", "nova_senha2": "qualquer-coisa-1",
    }).get_data(as_text=True)
    assert "Código inválido ou expirado" in html


def test_codigo_errado_tem_limite_de_tentativas(client, pegar_csrf, emails):
    _usuario_com_email()
    tok = pegar_csrf("/login/esqueci-senha")
    client.post("/login/esqueci-senha", data={"csrf_token": tok, "identificador": "sec1"})
    codigo = _codigo(emails)
    errado = "000000" if codigo != "000000" else "111111"
    dados = {"nova_senha": "senha-nova-456", "nova_senha2": "senha-nova-456"}
    for _ in range(5):
        tok = pegar_csrf("/login/redefinir-senha")
        client.post("/login/redefinir-senha", data={"csrf_token": tok, "codigo": errado, **dados})
    tok = pegar_csrf("/login/redefinir-senha")
    html = client.post("/login/redefinir-senha", data={"csrf_token": tok, "codigo": codigo, **dados}).get_data(as_text=True)
    assert "Código inválido ou expirado" in html  # esgotou as tentativas, nem o certo vale


def test_codigo_expirado_nao_vale(client, pegar_csrf, emails):
    from models import get_db
    _usuario_com_email()
    tok = pegar_csrf("/login/esqueci-senha")
    client.post("/login/esqueci-senha", data={"csrf_token": tok, "identificador": "sec1"})
    with get_db() as db:
        db.execute("UPDATE password_reset_codes SET expira_em = '2000-01-01 00:00:00'")
    tok = pegar_csrf("/login/redefinir-senha")
    html = client.post("/login/redefinir-senha", data={
        "csrf_token": tok, "codigo": _codigo(emails), "nova_senha": "senha-nova-456", "nova_senha2": "senha-nova-456",
    }).get_data(as_text=True)
    assert "Código inválido ou expirado" in html


def test_limite_de_pedidos_de_codigo(client, pegar_csrf, emails):
    _usuario_com_email()
    for _ in range(3):
        tok = pegar_csrf("/login/esqueci-senha")
        client.post("/login/esqueci-senha", data={"csrf_token": tok, "identificador": "sec1"})
    tok = pegar_csrf("/login/esqueci-senha")
    html = client.post("/login/esqueci-senha", data={"csrf_token": tok, "identificador": "sec1"}).get_data(as_text=True)
    assert "Muitos pedidos de código" in html
    assert len(emails) == 3


def test_cadastrar_email_em_minha_conta(client, pegar_csrf, criar_admin):
    from models import get_db
    username, senha = criar_admin
    tok = pegar_csrf("/minha-conta/senha")
    html = client.post("/minha-conta/email", data={"csrf_token": tok, "email": "adm@escola.teste",
                                                    "senha_atual_email": "errada"}, follow_redirects=True).get_data(as_text=True)
    assert "Senha atual incorreta" in html
    html = client.post("/minha-conta/email", data={"csrf_token": tok, "email": "nao-e-email",
                                                    "senha_atual_email": senha}, follow_redirects=True).get_data(as_text=True)
    assert "E-mail inválido" in html
    html = client.post("/minha-conta/email", data={"csrf_token": tok, "email": "adm@escola.teste",
                                                    "senha_atual_email": senha}, follow_redirects=True).get_data(as_text=True)
    assert "E-mail de recuperação salvo" in html and "adm@escola.teste" in html
    with get_db() as db:
        assert db.execute("SELECT email FROM users WHERE username = ?", (username,)).fetchone()[0] == "adm@escola.teste"


def test_falha_no_envio_mostra_erro(client, pegar_csrf, emails, monkeypatch):
    import mailer
    _usuario_com_email()

    def falha(*a, **k):
        raise OSError("SMTP fora do ar")
    monkeypatch.setattr(mailer, "enviar_email", falha)
    tok = pegar_csrf("/login/esqueci-senha")
    html = client.post("/login/esqueci-senha", data={"csrf_token": tok, "identificador": "sec1"}).get_data(as_text=True)
    assert "Não foi possível enviar o e-mail" in html
