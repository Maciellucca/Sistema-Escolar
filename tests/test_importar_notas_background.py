"""
Testa o processamento em segundo plano da leitura da Ata Bimestral —
criado para resolver o timeout de gateway que acontece em hospedagens como
o Render quando a leitura (1-3 min) roda dentro da própria requisição.
"""
import io
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


@pytest.fixture()
def pdf_ficticio(tmp_path_factory):
    """Gera uma Ata Bimestral fictícia (scripts/gerar_ata_ficticia.py) sob
    demanda em vez de depender de um arquivo binário versionado — a base de
    exemplo (data/exemplo/) não fica mais no repositório."""
    from gerar_ata_ficticia import gerar_pdf

    caminho = tmp_path_factory.mktemp("ata") / "AtaBimestral_ficticia_1bim.pdf"
    gerar_pdf(str(caminho), turma="1A", bimestre=1, ano=2026)
    return caminho


def _esperar_processamento(client, lote_id, timeout=15):
    inicio = time.time()
    while time.time() - inicio < timeout:
        resp = client.get(f"/importar/notas/{lote_id}/status")
        if resp.status_code == 302:
            return resp
        time.sleep(0.2)
    raise AssertionError("processamento em background não terminou a tempo")


def test_upload_responde_rapido_sem_esperar_a_leitura_do_pdf(client, pegar_csrf, criar_admin, pdf_ficticio):
    tok = pegar_csrf("/importar/notas")
    with open(pdf_ficticio, "rb") as f:
        inicio = time.time()
        resp = client.post(
            "/importar/notas/upload",
            data={"pdf": (io.BytesIO(f.read()), "ata.pdf"), "ano": "2026", "bimestre": "1", "csrf_token": tok},
            content_type="multipart/form-data",
        )
        duracao = time.time() - inicio

    assert resp.status_code == 302
    assert "/status" in resp.headers["Location"]
    # a resposta não pode esperar a leitura do PDF (que leva segundos a
    # minutos) — precisa voltar quase na hora, senão o gateway da
    # hospedagem derruba a conexão antes de chegar aqui.
    assert duracao < 3


def test_pagina_de_status_mostra_lendo_e_depois_libera_a_revisao(client, pegar_csrf, criar_admin, pdf_ficticio):
    tok = pegar_csrf("/importar/notas")
    with open(pdf_ficticio, "rb") as f:
        resp = client.post(
            "/importar/notas/upload",
            data={"pdf": (io.BytesIO(f.read()), "ata.pdf"), "ano": "2026", "bimestre": "1", "csrf_token": tok},
            content_type="multipart/form-data",
        )
    lote_id = resp.headers["Location"].rsplit("/", 2)[-2]

    status_resp = client.get(f"/importar/notas/{lote_id}/status")
    assert status_resp.status_code == 200
    assert "Lendo o PDF" in status_resp.get_data(as_text=True)

    final = _esperar_processamento(client, lote_id)
    assert final.headers["Location"].endswith(f"/notas/{lote_id}")

    revisao = client.get(f"/importar/notas/{lote_id}", follow_redirects=True)
    assert "Conferência" in revisao.get_data(as_text=True)


def test_pdf_invalido_mostra_erro_sem_derrubar_o_servidor(client, pegar_csrf, criar_admin):
    tok = pegar_csrf("/importar/notas")
    resp = client.post(
        "/importar/notas/upload",
        data={"pdf": (io.BytesIO(b"nao e um pdf"), "quebrado.pdf"), "ano": "2026", "bimestre": "1", "csrf_token": tok},
        content_type="multipart/form-data",
    )
    lote_id = resp.headers["Location"].rsplit("/", 2)[-2]

    final = _esperar_processamento(client, lote_id)
    pagina_final = client.get(final.headers["Location"], follow_redirects=True)
    assert "Não foi possível ler o PDF" in pagina_final.get_data(as_text=True)


def test_arquivo_enviado_e_apagado_do_servidor_depois_de_processar(app, client, pegar_csrf, criar_admin, pdf_ficticio):
    import config

    tok = pegar_csrf("/importar/notas")
    with open(pdf_ficticio, "rb") as f:
        resp = client.post(
            "/importar/notas/upload",
            data={"pdf": (io.BytesIO(f.read()), "ata.pdf"), "ano": "2026", "bimestre": "1", "csrf_token": tok},
            content_type="multipart/form-data",
        )
    lote_id = resp.headers["Location"].rsplit("/", 2)[-2]
    _esperar_processamento(client, lote_id)

    assert list(config.UPLOADS_DIR.glob("*")) == []


def test_lote_travado_ha_muito_tempo_mostra_aviso_e_permite_cancelar(app, client, pegar_csrf, criar_admin):
    """Cobre o caso de hospedagens (ex: Render Free) que não sustentam
    trabalho em segundo plano de forma confiável — a leitura pode nunca
    terminar, e o usuário precisa de um jeito de sair dessa tela em vez de
    ficar com o spinner girando para sempre."""
    from models import get_db

    from datetime import datetime, timedelta, timezone
    dez_min_atras = (datetime.now(timezone.utc) - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as db:
        lote_id = db.execute(
            """INSERT INTO import_lotes (arquivo, ano, bimestre, criado_por, processando, created_at)
               VALUES ('travado.pdf', 2026, 1, 'Teste', 1, ?)""",
            (dez_min_atras,),
        ).lastrowid

    resp = client.get(f"/importar/notas/{lote_id}/status")
    html = resp.get_data(as_text=True)
    assert "demorando demais" in html.lower()
    assert "Cancelar esta importação" in html
    assert 'http-equiv="refresh"' not in html  # não fica tentando recarregar pra sempre

    tok = pegar_csrf(f"/importar/notas/{lote_id}/status")
    resp2 = client.post(
        f"/importar/notas/{lote_id}/cancelar-travado", data={"csrf_token": tok}, follow_redirects=True
    )
    assert "cancelada" in resp2.get_data(as_text=True).lower()

    with get_db() as db:
        lote = db.execute("SELECT status, processando FROM import_lotes WHERE id=?", (lote_id,)).fetchone()
    assert lote["status"] == "descartado"
    assert lote["processando"] == 0


def test_lote_recente_ainda_processando_nao_mostra_aviso(app, client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        lote_id = db.execute(
            "INSERT INTO import_lotes (arquivo, ano, bimestre, criado_por, processando) VALUES ('agora.pdf', 2026, 1, 'Teste', 1)"
        ).lastrowid

    resp = client.get(f"/importar/notas/{lote_id}/status")
    html = resp.get_data(as_text=True)
    assert "Lendo o PDF" in html
    assert "demorando demais" not in html.lower()
    assert 'http-equiv="refresh"' in html


# --------------------------------------------- upload do JSON já processado
def test_upload_json_ja_processado_e_sincrono_e_pula_a_tela_de_status(client, pegar_csrf, criar_admin, tmp_path, pdf_ficticio):
    """Alternativa ao upload de PDF: roda a leitura pesada localmente
    (scripts/exportar_notas_json.py) e sobe só o resultado — não precisa de
    thread em segundo plano porque gravar em grades_staging é rápido."""
    from exportar_notas_json import exportar

    saida = exportar(str(pdf_ficticio), ano=2026, bimestre=1, saida=tmp_path / "notas.json")

    tok = pegar_csrf("/importar/notas")
    with open(saida, "rb") as f:
        inicio = time.time()
        resp = client.post(
            "/importar/notas/upload-json",
            data={"json": (io.BytesIO(f.read()), "notas.json"), "csrf_token": tok},
            content_type="multipart/form-data",
        )
        duracao = time.time() - inicio

    assert resp.status_code == 302
    assert "/status" not in resp.headers["Location"]  # vai direto pra revisão, sem espera
    assert duracao < 1

    revisao = client.get(resp.headers["Location"], follow_redirects=True)
    assert "Conferência" in revisao.get_data(as_text=True)


def test_upload_json_invalido_mostra_erro_sem_derrubar_o_servidor(client, pegar_csrf, criar_admin):
    tok = pegar_csrf("/importar/notas")
    resp = client.post(
        "/importar/notas/upload-json",
        data={"json": (io.BytesIO(b"nao e json"), "quebrado.json"), "csrf_token": tok},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "inválido" in resp.get_data(as_text=True).lower()


def test_upload_json_com_formato_errado_mostra_erro(client, pegar_csrf, criar_admin):
    import json as j

    tok = pegar_csrf("/importar/notas")
    corpo = j.dumps({"algo": "sem o formato esperado"}).encode()
    resp = client.post(
        "/importar/notas/upload-json",
        data={"json": (io.BytesIO(corpo), "x.json"), "csrf_token": tok},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "formato esperado" in resp.get_data(as_text=True)
