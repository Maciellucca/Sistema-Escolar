"""
Testa os cabeçalhos anti-cache que impedem o botão "voltar" do navegador
de mostrar uma página autenticada depois do logout (a sessão já foi
encerrada no servidor, mas sem esses cabeçalhos o navegador podia exibir
uma cópia em cache local até a pessoa interagir com a tela).
"""


def test_pagina_dinamica_tem_cabecalhos_anti_cache(client, pegar_csrf, criar_admin):
    resp = client.get("/")
    assert resp.headers.get("Cache-Control") == "no-store, no-cache, must-revalidate, max-age=0"
    assert resp.headers.get("Pragma") == "no-cache"
    assert resp.headers.get("Expires") == "0"


def test_tela_de_login_tambem_tem_cabecalhos_anti_cache(client):
    resp = client.get("/login")
    assert resp.headers.get("Cache-Control") == "no-store, no-cache, must-revalidate, max-age=0"


def test_portal_do_responsavel_tem_cabecalhos_anti_cache(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        db.execute(
            "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?,?,?, 'ATIVO')",
            ("CH1", "ALUNO TESTE CACHE", "1A", "1º Ano"),
        )
    resp = client.get("/responsavel/")
    assert resp.headers.get("Cache-Control") == "no-store, no-cache, must-revalidate, max-age=0"


def test_arquivo_estatico_nao_recebe_cabecalho_forcado(client):
    resp = client.get("/static/css/style.css")
    # não deve ser exatamente igual ao valor que o app força nas páginas
    # dinâmicas — arquivo estático pode continuar sendo cacheado normalmente
    assert resp.headers.get("Cache-Control") != "no-store, no-cache, must-revalidate, max-age=0"


def test_apos_logout_pagina_protegida_redireciona_para_login(client, pegar_csrf, criar_admin):
    """Não simula o botão 'voltar' em si (isso é comportamento do
    navegador local, não do servidor), mas confirma a parte que garante
    que funcione: mesmo que o navegador reenvie a requisição da página
    protegida depois do logout, o servidor manda pro login — não mostra
    o painel."""
    resp = client.get("/")
    assert "Olá" in resp.get_data(as_text=True)

    client.get("/logout")

    resp2 = client.get("/", follow_redirects=True)
    html = resp2.get_data(as_text=True)
    assert "Olá" not in html
    assert 'name="senha"' in html
