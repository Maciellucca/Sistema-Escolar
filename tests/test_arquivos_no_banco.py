"""
Fotos (aluno e relatório escolar) ficam no banco: apagar a pasta local
(o que acontece a cada reinício em hospedagem gratuita) não perde nada.
"""
import io
import shutil

from PIL import Image


def _jpeg(cor=(200, 100, 50)):
    buf = io.BytesIO()
    Image.new("RGB", (60, 80), cor).save(buf, "JPEG")
    return buf.getvalue()


def test_foto_do_aluno_sobrevive_a_pasta_apagada(client, pegar_csrf, criar_admin):
    import config
    from models import get_db
    with get_db() as db:
        sid = db.execute("INSERT INTO students (codigo_interno, nome, turma, situacao) VALUES ('F1','ALUNO FOTO','1A','ATIVO')").lastrowid
    tok = pegar_csrf(f"/aluno/{sid}")
    client.post(f"/aluno/{sid}/foto", data={"csrf_token": tok, "foto": (io.BytesIO(_jpeg()), "f.jpg")},
                content_type="multipart/form-data")
    with get_db() as db:
        assert db.execute("SELECT foto_path FROM students WHERE id = ?", (sid,)).fetchone()["foto_path"] == f"aluno_{sid}.jpg"
        assert db.execute("SELECT tamanho FROM arquivos WHERE categoria = 'fotos'").fetchone()["tamanho"] > 0
    shutil.rmtree(config.PHOTOS_DIR)  # "reinício" do servidor
    resp = client.get(f"/fotos/aluno_{sid}.jpg")
    assert resp.status_code == 200 and resp.mimetype == "image/jpeg" and resp.data == _jpeg()
    # trocar por PNG apaga a JPG antiga
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, "PNG")
    client.post(f"/aluno/{sid}/foto", data={"csrf_token": tok, "foto": (io.BytesIO(buf.getvalue()), "f.png")},
                content_type="multipart/form-data")
    with get_db() as db:
        nomes = [r["nome"] for r in db.execute("SELECT nome FROM arquivos WHERE categoria = 'fotos'").fetchall()]
    assert nomes == [f"aluno_{sid}.png"]
    assert client.get(f"/fotos/aluno_{sid}.jpg").status_code == 404
    assert client.get("/fotos/..%2Fsistema_escolar.db").status_code in (403, 404)


def test_foto_antiga_so_no_disco_vai_para_o_banco(client, pegar_csrf, criar_admin):
    import config
    from models import get_db
    with get_db() as db:
        sid = db.execute("INSERT INTO students (codigo_interno, nome, turma, situacao, foto_path) VALUES ('F2','ANTIGO','1A','ATIVO', 'aluno_x.jpg')").lastrowid
    config.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    (config.PHOTOS_DIR / f"aluno_{sid}.jpg").write_bytes(_jpeg((1, 2, 3)))
    assert client.get(f"/fotos/aluno_{sid}.jpg").status_code == 200
    with get_db() as db:
        assert db.execute("SELECT COUNT(*) c FROM arquivos WHERE nome = ?", (f"aluno_{sid}.jpg",)).fetchone()["c"] == 1
