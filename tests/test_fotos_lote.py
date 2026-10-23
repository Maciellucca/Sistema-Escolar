"""
Testa o envio de fotos em lote: cada arquivo casado com o aluno certo
pelo nome do arquivo (ignorando maiúsculas/minúsculas, acentos, "_"/"-").
"""
import io

from PIL import Image


def _imagem(fmt="JPEG"):
    img = Image.new("RGB", (10, 10), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf


def _aluno(db, codigo, nome, turma="1A"):
    return db.execute(
        "INSERT INTO students (codigo_interno, nome, turma, serie, situacao) VALUES (?,?,?, '1º Ano', 'ATIVO')",
        (codigo, nome, turma),
    ).lastrowid


def test_tela_de_upload_carrega(client, pegar_csrf, criar_admin):
    resp = client.get("/importar/fotos")
    assert resp.status_code == 200
    assert "Enviar fotos em lote" in resp.get_data(as_text=True)


def test_foto_casa_com_aluno_por_nome_exato(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "F1", "MARIA EDUARDA SANTOS")

    tok = pegar_csrf("/importar/fotos")
    resp = client.post(
        "/importar/fotos/upload",
        data={"turma": "", "csrf_token": tok, "fotos": [(_imagem("JPEG"), "MARIA EDUARDA SANTOS.jpg")]},
        content_type="multipart/form-data",
    )
    html = resp.get_data(as_text=True)
    assert "MARIA EDUARDA SANTOS.jpg" in html
    assert "Casadas com sucesso" in html

    from models import get_db
    with get_db() as db:
        aluno = db.execute("SELECT foto_path FROM students WHERE id=?", (aluno_id,)).fetchone()
    assert aluno["foto_path"] == f"aluno_{aluno_id}.jpg"


def test_nome_do_arquivo_normaliza_underscore_e_minuscula(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        aluno_id = _aluno(db, "F2", "JOAO PEDRO ALVES")

    tok = pegar_csrf("/importar/fotos")
    resp = client.post(
        "/importar/fotos/upload",
        data={"turma": "", "csrf_token": tok, "fotos": [(_imagem("PNG"), "joao_pedro_alves.png")]},
        content_type="multipart/form-data",
    )
    assert "joao_pedro_alves.png" in resp.get_data(as_text=True)

    with get_db() as db:
        aluno = db.execute("SELECT foto_path FROM students WHERE id=?", (aluno_id,)).fetchone()
    assert aluno["foto_path"] == f"aluno_{aluno_id}.png"


def test_nome_ambiguo_entre_turmas_fica_pendente(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "F3", "PEDRO HENRIQUE LIMA", turma="1A")
        _aluno(db, "F4", "PEDRO HENRIQUE LIMA", turma="2A")

    tok = pegar_csrf("/importar/fotos")
    resp = client.post(
        "/importar/fotos/upload",
        data={"turma": "", "csrf_token": tok, "fotos": [(_imagem("JPEG"), "PEDRO HENRIQUE LIMA.jpg")]},
        content_type="multipart/form-data",
    )
    html = resp.get_data(as_text=True)
    assert "mais de um aluno com esse nome" in html


def test_filtro_de_turma_resolve_nome_ambiguo(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "F5", "CARLA MENDES", turma="1A")
        aluno_2a = _aluno(db, "F6", "CARLA MENDES", turma="2A")

    tok = pegar_csrf("/importar/fotos")
    resp = client.post(
        "/importar/fotos/upload",
        data={"turma": "2A", "csrf_token": tok, "fotos": [(_imagem("JPEG"), "CARLA MENDES.jpg")]},
        content_type="multipart/form-data",
    )
    html = resp.get_data(as_text=True)
    assert "Casadas com sucesso" in html
    assert "2A" in html

    with get_db() as db:
        aluno = db.execute("SELECT foto_path FROM students WHERE id=?", (aluno_2a,)).fetchone()
    assert aluno["foto_path"] is not None


def test_nome_nao_encontrado_fica_pendente(client, pegar_csrf, criar_admin):
    tok = pegar_csrf("/importar/fotos")
    resp = client.post(
        "/importar/fotos/upload",
        data={"turma": "", "csrf_token": tok, "fotos": [(_imagem("JPEG"), "ALUNO QUE NAO EXISTE.jpg")]},
        content_type="multipart/form-data",
    )
    assert "nenhum aluno com esse nome encontrado" in resp.get_data(as_text=True)


def test_extensao_invalida_fica_pendente(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "F7", "TESTE EXTENSAO")

    tok = pegar_csrf("/importar/fotos")
    resp = client.post(
        "/importar/fotos/upload",
        data={"turma": "", "csrf_token": tok, "fotos": [(io.BytesIO(b"nao e imagem"), "TESTE EXTENSAO.txt")]},
        content_type="multipart/form-data",
    )
    assert "formato inválido" in resp.get_data(as_text=True)


def test_upload_sem_arquivos_mostra_erro(client, pegar_csrf, criar_admin):
    tok = pegar_csrf("/importar/fotos")
    resp = client.post(
        "/importar/fotos/upload",
        data={"turma": "", "csrf_token": tok},
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert "Selecione pelo menos um arquivo" in resp.get_data(as_text=True)


def test_varias_fotos_de_uma_vez(client, pegar_csrf, criar_admin):
    from models import get_db

    with get_db() as db:
        _aluno(db, "F8", "ALUNO UM")
        _aluno(db, "F9", "ALUNO DOIS")

    tok = pegar_csrf("/importar/fotos")
    resp = client.post(
        "/importar/fotos/upload",
        data={
            "turma": "", "csrf_token": tok,
            "fotos": [
                (_imagem("JPEG"), "ALUNO UM.jpg"),
                (_imagem("PNG"), "ALUNO DOIS.png"),
                (_imagem("JPEG"), "NAO EXISTE.jpg"),
            ],
        },
        content_type="multipart/form-data",
    )
    html = resp.get_data(as_text=True)
    assert "ALUNO UM.jpg" in html
    assert "ALUNO DOIS.png" in html
    assert "NAO EXISTE.jpg" in html


def _enviar(client, pegar_csrf, arquivos, turma=""):
    tok = pegar_csrf("/importar/fotos")
    return client.post(
        "/importar/fotos/upload",
        data={"turma": turma, "csrf_token": tok, "fotos": [(_imagem("JPEG"), n) for n in arquivos]},
        content_type="multipart/form-data",
    ).get_data(as_text=True)


def _foto(aluno_id):
    from models import get_db
    with get_db() as db:
        return db.execute("SELECT foto_path FROM students WHERE id=?", (aluno_id,)).fetchone()["foto_path"]


def test_separar_nome_e_eol():
    from routes.importacao import separar_nome_e_eol
    assert separar_nome_e_eol("AGATHA LIECK SANTOS-7584678.jpg") == ("AGATHA LIECK SANTOS", "7584678")
    assert separar_nome_e_eol("agatha_lieck_santos - 7584678.png") == ("agatha_lieck_santos", "7584678")
    assert separar_nome_e_eol("AGATHA LIECK SANTOS.jpg") == ("AGATHA LIECK SANTOS", None)


def test_foto_nome_eol_casa_pelo_codigo_e_confere_nome(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        certo = _aluno(db, "7584678", "AGATHA LIECK SANTOS")
        homonimo = _aluno(db, "7000001", "AGATHA LIECK SANTOS", turma="2B")
    html = _enviar(client, pegar_csrf, ["Agatha Lieck Santos-7584678.jpg"])
    assert "EOL e nome conferem" in html
    assert _foto(certo) == f"aluno_{certo}.jpg"
    assert _foto(homonimo) is None  # nome repetido não atrapalha: o EOL decide


def test_eol_de_outro_aluno_nao_salva(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        aluno = _aluno(db, "7584678", "AGATHA LIECK SANTOS")
    html = _enviar(client, pegar_csrf, ["BRUNO ALVES COSTA-7584678.jpg"])
    assert "o EOL 7584678 é de AGATHA LIECK SANTOS" in html
    assert _foto(aluno) is None


def test_nome_com_pequena_diferenca_e_eol_certo_casa(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        aluno = _aluno(db, "7388995", "ANDRE GONCALVES OLIVEIRA")
    _enviar(client, pegar_csrf, ["André Gonçalves-7388995.jpg"])  # sem o último sobrenome, com acento
    assert _foto(aluno) == f"aluno_{aluno}.jpg"


def test_eol_nao_cadastrado_cai_para_o_nome(client, pegar_csrf, criar_admin):
    from models import get_db
    with get_db() as db:
        aluno = _aluno(db, "F77", "CAIO NUNES")
    html = _enviar(client, pegar_csrf, ["CAIO NUNES-9999999.jpg"])
    assert "EOL 9999999 não encontrado no cadastro — casado pelo nome" in html
    assert _foto(aluno) is not None
