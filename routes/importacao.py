"""
Fluxo de importação de notas com tela de conferência:

  1. Upload do PDF da Ata Bimestral -> a leitura roda em SEGUNDO PLANO
     (thread própria) e o resultado fica em `grades_staging` (rascunho),
     NUNCA direto em `grades`. Isso é necessário porque a leitura de um
     PDF grande (100+ páginas) pode levar de 1 a 3 minutos — tempo maior
     que o limite de requisição HTTP de praticamente qualquer hospedagem
     séria (Render, por exemplo, corta a conexão bem antes disso). Fazer
     a leitura dentro da própria requisição de upload dá erro de
     timeout/gateway em produção, mesmo aumentando o timeout do gunicorn.
  2. Tela de status -> a página do navegador fica se atualizando sozinha
     enquanto a leitura roda, sem travar nem dar timeout.
  3. Tela de revisão -> mostra o que foi lido, deixa corrigir o
     casamento aluno/turma quando não encontrado e editar valores antes
     de confirmar.
  4. Confirmar -> só então os dados viram nota oficial em `grades`
     (o que os responsáveis enxergam no boletim).
"""
import json
import re
import sys
import threading
import time
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, abort, current_app
)
from werkzeug.utils import secure_filename

import arquivos as _arquivos
import config
from models import get_db, agora, salvar_nota
from auth import roles_required, current_user
from routes.staff import ALLOWED_PHOTO_EXT

from _ata_parser_lib import parse_pdf  # noqa: E402  (path ajustado acima)
import import_students as _import_students_lib  # noqa: E402
import import_aee as _import_aee_lib  # noqa: E402
import importar_base_dados as _import_base_lib  # noqa: E402
import import_turma_projeto as _import_projeto_lib  # noqa: E402

importacao_bp = Blueprint("importacao", __name__, url_prefix="/importar")


def _log(acao):
    with get_db() as db:
        db.execute(
            "INSERT INTO access_log (tipo, referencia, acao, ip) VALUES (?,?,?,?)",
            ("staff", session.get("nome"), acao, request.remote_addr),
        )


def _match_student(db, turma_pdf, nome_pdf):
    row = db.execute(
        "SELECT id FROM students WHERE turma = ? AND nome = ?", (turma_pdf, nome_pdf)
    ).fetchone()
    if row:
        return row["id"]
    row = db.execute("SELECT id FROM students WHERE nome = ?", (nome_pdf,)).fetchone()
    if row:
        return row["id"]
    # tolerante: sem diferença de acento, espaço duplo ou maiúscula; ou o nome
    # do PDF cortado (começo do nome do cadastro), só se for um aluno só
    chave = _chave_nome(nome_pdf)
    if not chave:
        return None
    da_turma = db.execute(
        "SELECT id, nome, nome_social FROM students WHERE turma = ?", (turma_pdf,)).fetchall()
    for grupo in (da_turma, None):
        if grupo is None:
            grupo = db.execute("SELECT id, nome, nome_social FROM students").fetchall()
        iguais = {r["id"] for r in grupo
                  if chave in (_chave_nome(r["nome"]), _chave_nome(r["nome_social"]))}
        if len(iguais) == 1:
            return iguais.pop()
    if len(chave) >= 12:
        comeca = {r["id"] for r in da_turma if _chave_nome(r["nome"]).startswith(chave)}
        if len(comeca) == 1:
            return comeca.pop()
    return None


def _gravar_staging(db, lote_id, resultado):
    """Grava em grades_staging a partir de {turma: {aluno: {situacao_conselho,
    disciplinas}}} — o mesmo formato devolvido por parse_pdf() e pelo JSON
    exportado por scripts/exportar_notas_json.py. Compartilhado entre o
    upload de PDF (segundo plano) e o upload de JSON (síncrono, mais rápido
    por já vir processado)."""
    total_alunos, nao_localizados = 0, 0
    for turma_pdf, alunos in resultado.items():
        for nome_pdf, dados in alunos.items():
            total_alunos += 1
            aluno_key = f"{turma_pdf}||{nome_pdf}"
            student_id = _match_student(db, turma_pdf, nome_pdf)
            if not student_id:
                nao_localizados += 1
            for disciplina, valores in dados.get("disciplinas", {}).items():
                db.execute(
                    """INSERT INTO grades_staging
                         (lote_id, aluno_key, turma_pdf, nome_pdf, student_id,
                          disciplina, faltas, compensacoes, frequencia, conceito,
                          situacao_conselho, incluir)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        lote_id, aluno_key, turma_pdf, nome_pdf, student_id,
                        disciplina, valores.get("faltas"), valores.get("compensacoes"),
                        valores.get("frequencia"), valores.get("conceito"),
                        dados.get("situacao_conselho"),
                        1 if student_id else 0,
                    ),
                )
    return total_alunos, nao_localizados


# ------------------------------------------------------------------ lista --
@importacao_bp.route("/notas")
@roles_required("admin", "secretaria")
def notas_index():
    with get_db() as db:
        lotes = db.execute(
            "SELECT * FROM import_lotes ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    return render_template(
        "importar_notas.html", lotes=lotes, series=config.SERIES_EF, user=current_user()
    )


# ---------------------------------------------------------------- upload ---
def _ler_pdf_em_background(app, caminho, lote_id, turmas):
    """Roda numa thread separada da requisição HTTP que fez o upload —
    veja o docstring do módulo para o porquê disso ser necessário."""
    with app.app_context():
        app.logger.info(
            f"[importacao] lote {lote_id}: iniciando leitura em segundo plano de "
            f"'{caminho.name}' ({caminho.stat().st_size if caminho.exists() else '?'} bytes)"
        )
        try:
            resultado = parse_pdf(str(caminho), turmas_alvo=turmas)
        except Exception as exc:  # leitura de PDF de terceiros: nunca deixe sem log
            app.logger.exception(f"[importacao] lote {lote_id}: falha ao ler PDF de ata (background)")
            with get_db() as db:
                db.execute(
                    "UPDATE import_lotes SET processando=0, erro_mensagem=? WHERE id=?",
                    (str(exc), lote_id),
                )
            caminho.unlink(missing_ok=True)
            return

        app.logger.info(f"[importacao] lote {lote_id}: PDF lido, gravando em grades_staging")

        if not resultado:
            with get_db() as db:
                db.execute(
                    """UPDATE import_lotes SET processando=0,
                       erro_mensagem='Nenhuma turma reconhecida nesse PDF (confira o filtro de turmas e se é mesmo um relatório de Ata Bimestral do SGP).'
                       WHERE id=?""",
                    (lote_id,),
                )
            caminho.unlink(missing_ok=True)
            return

        with get_db() as db:
            total_alunos, nao_localizados = _gravar_staging(db, lote_id, resultado)
            db.execute(
                """UPDATE import_lotes
                   SET total_alunos=?, total_nao_localizados=?, processando=0
                   WHERE id=?""",
                (total_alunos, nao_localizados, lote_id),
            )
        # o conteúdo já foi extraído para o banco — não há motivo para manter
        # uma cópia do PDF original (pode ter dado real de aluno) parada no
        # disco do servidor além do necessário.
        caminho.unlink(missing_ok=True)
        app.logger.info(f"[importacao] lote {lote_id}: concluído ({total_alunos} aluno(s) lido(s))")


@importacao_bp.route("/notas/upload", methods=["POST"])
@roles_required("admin", "secretaria")
def notas_upload():
    file = request.files.get("pdf")
    ano = request.form.get("ano", type=int)
    bimestre = request.form.get("bimestre", type=int)
    turmas_raw = request.form.get("turmas", "").strip()
    turmas = {t.strip().upper() for t in turmas_raw.split(",") if t.strip()} or None

    if not file or file.filename == "" or not file.filename.lower().endswith(".pdf"):
        flash("Selecione um arquivo PDF da Ata Bimestral.", "erro")
        return redirect(url_for("importacao.notas_index"))
    if not ano or not bimestre:
        flash("Informe o ano letivo e o bimestre.", "erro")
        return redirect(url_for("importacao.notas_index"))

    filename = secure_filename(f"{int(time.time())}_{file.filename}")
    caminho = config.UPLOADS_DIR / filename
    file.save(caminho)

    with get_db() as db:
        cur = db.execute(
            """INSERT INTO import_lotes (arquivo, ano, bimestre, criado_por, processando)
               VALUES (?,?,?,?,1)""",
            (file.filename, ano, bimestre, session.get("nome")),
        )
        lote_id = cur.lastrowid

    app_obj = current_app._get_current_object()
    threading.Thread(
        target=_ler_pdf_em_background, args=(app_obj, caminho, lote_id, turmas), daemon=True
    ).start()

    _log(f"upload_lote:{lote_id}")
    return redirect(url_for("importacao.status", lote_id=lote_id))


# ------------------------------------------------------ upload já processado
@importacao_bp.route("/notas/upload-json", methods=["POST"])
@roles_required("admin", "secretaria")
def notas_upload_json():
    """Recebe um .json já processado (gerado localmente por
    scripts/exportar_notas_json.py) em vez do PDF cru. Como não precisa
    fazer a leitura pesada — só INSERTs simples em grades_staging — roda
    de forma síncrona mesmo, sem precisar de thread nem tela de espera:
    funciona bem mesmo em hospedagens com pouca CPU."""
    file = request.files.get("json")
    if not file or file.filename == "" or not file.filename.lower().endswith(".json"):
        flash("Selecione o arquivo .json gerado por scripts/exportar_notas_json.py.", "erro")
        return redirect(url_for("importacao.notas_index"))

    try:
        pacote = json.load(file.stream)
    except Exception as exc:
        flash(f"Arquivo JSON inválido: {exc}", "erro")
        return redirect(url_for("importacao.notas_index"))

    ano = pacote.get("ano")
    bimestre = pacote.get("bimestre")
    turmas_dados = pacote.get("turmas")
    if not ano or not bimestre or not isinstance(turmas_dados, dict):
        flash(
            "Esse JSON não tem o formato esperado — ele precisa ser gerado por "
            "scripts/exportar_notas_json.py.",
            "erro",
        )
        return redirect(url_for("importacao.notas_index"))

    with get_db() as db:
        cur = db.execute(
            """INSERT INTO import_lotes (arquivo, ano, bimestre, criado_por, processando)
               VALUES (?,?,?,?,0)""",
            (pacote.get("arquivo_origem", file.filename), ano, bimestre, session.get("nome")),
        )
        lote_id = cur.lastrowid
        total_alunos, nao_localizados = _gravar_staging(db, lote_id, turmas_dados)
        db.execute(
            "UPDATE import_lotes SET total_alunos=?, total_nao_localizados=? WHERE id=?",
            (total_alunos, nao_localizados, lote_id),
        )

    _log(f"upload_json_lote:{lote_id}")
    return redirect(url_for("importacao.revisar", lote_id=lote_id))


# ---------------------------------------------------------------- status ---
TEMPO_MAX_PROCESSAMENTO_MINUTOS = 6


def _minutos_desde(texto_data):
    """created_at vem como 'YYYY-MM-DD HH:MM:SS' (SQLite ou MySQL)."""
    from datetime import datetime, timezone
    try:
        texto = str(texto_data)[:19].replace("T", " ")
        dt = datetime.strptime(texto, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60


@importacao_bp.route("/notas/<int:lote_id>/status")
@roles_required("admin", "secretaria")
def status(lote_id):
    with get_db() as db:
        lote = db.execute("SELECT * FROM import_lotes WHERE id = ?", (lote_id,)).fetchone()
    if not lote:
        abort(404)
    if lote["processando"]:
        minutos = _minutos_desde(lote["created_at"])
        return render_template(
            "processando_notas.html", lote=lote, user=current_user(),
            demorando_muito=minutos > TEMPO_MAX_PROCESSAMENTO_MINUTOS, minutos=int(minutos),
        )
    if lote["erro_mensagem"]:
        flash(f"Não foi possível ler o PDF: {lote['erro_mensagem']}", "erro")
        return redirect(url_for("importacao.notas_index"))
    return redirect(url_for("importacao.revisar", lote_id=lote_id))


@importacao_bp.route("/notas/<int:lote_id>/cancelar-travado", methods=["POST"])
@roles_required("admin", "secretaria")
def cancelar_travado(lote_id):
    """Só existe para o caso de a leitura em segundo plano nunca terminar
    (visto em hospedagens que não sustentam trabalho em background fora do
    ciclo de requisição, como o plano Free do Render) — permite descartar
    manualmente em vez de ficar com o spinner girando para sempre."""
    with get_db() as db:
        lote = db.execute("SELECT * FROM import_lotes WHERE id = ?", (lote_id,)).fetchone()
        if not lote or not lote["processando"]:
            abort(404)
        db.execute("DELETE FROM grades_staging WHERE lote_id = ?", (lote_id,))
        db.execute(
            "UPDATE import_lotes SET status='descartado', processando=0 WHERE id=?",
            (lote_id,),
        )
    _log(f"cancelar_lote_travado:{lote_id}")
    flash("Importação cancelada.", "ok")
    return redirect(url_for("importacao.notas_index"))


# --------------------------------------------------------------- revisão ---
@importacao_bp.route("/notas/<int:lote_id>")
@roles_required("admin", "secretaria")
def revisar(lote_id):
    with get_db() as db:
        lote = db.execute("SELECT * FROM import_lotes WHERE id = ?", (lote_id,)).fetchone()
        if not lote:
            abort(404)
        if lote["processando"]:
            return redirect(url_for("importacao.status", lote_id=lote_id))
        linhas = db.execute(
            """SELECT gs.*, s.nome AS nome_sistema
               FROM grades_staging gs
               LEFT JOIN students s ON s.id = gs.student_id
               WHERE gs.lote_id = ?
               ORDER BY gs.turma_pdf, gs.nome_pdf, gs.disciplina""",
            (lote_id,),
        ).fetchall()
        turmas_sistema = db.execute(
            "SELECT DISTINCT turma FROM students ORDER BY turma"
        ).fetchall()

    # agrupa em: turma_pdf -> aluno_key -> {info, disciplinas: [linhas]}
    turmas = {}
    for l in linhas:
        turma_grp = turmas.setdefault(l["turma_pdf"], {})
        aluno_grp = turma_grp.setdefault(
            l["aluno_key"],
            {
                "nome_pdf": l["nome_pdf"],
                "student_id": l["student_id"],
                "nome_sistema": l["nome_sistema"],
                "incluir": l["incluir"],
                "disciplinas": [],
            },
        )
        aluno_grp["disciplinas"].append(l)

    return render_template(
        "revisar_lote.html",
        lote=lote,
        turmas=turmas,
        user=current_user(),
    )


# -------------------------------------------------------------- confirmar --
@importacao_bp.route("/notas/<int:lote_id>/confirmar", methods=["POST"])
@roles_required("admin", "secretaria")
def confirmar(lote_id):
    with get_db() as db:
        lote = db.execute("SELECT * FROM import_lotes WHERE id = ?", (lote_id,)).fetchone()
        if not lote or lote["status"] != "pendente" or lote["processando"]:
            abort(404)
        linhas = db.execute(
            "SELECT * FROM grades_staging WHERE lote_id = ?", (lote_id,)
        ).fetchall()

        # agrupa por aluno_key para aplicar a escolha de casamento/inclusão 1x
        por_aluno = {}
        for l in linhas:
            por_aluno.setdefault(l["aluno_key"], []).append(l)

        gravados = 0
        for aluno_key, rows in por_aluno.items():
            campo = aluno_key.replace(" ", "_")
            student_id_form = request.form.get(f"student_id::{aluno_key}", "")
            incluir = request.form.get(f"incluir::{aluno_key}") == "on"
            student_id = int(student_id_form) if student_id_form else None

            for r in rows:
                faltas = request.form.get(f"faltas::{r['id']}", "")
                comp = request.form.get(f"comp::{r['id']}", "")
                freq = request.form.get(f"freq::{r['id']}", "")
                conc = request.form.get(f"conc::{r['id']}", r["conceito"] or "")

                faltas = int(faltas) if faltas.strip() else None
                comp = int(comp) if comp.strip() else None
                freq = float(freq.replace(",", ".")) if freq.strip() else None

                if incluir and student_id:
                    salvar_nota(
                        db, student_id, lote["ano"], lote["bimestre"], r["disciplina"],
                        faltas, comp, freq, conc, r["situacao_conselho"], "conferido_web",
                    )
                    gravados += 1

        db.execute(
            """UPDATE import_lotes
               SET status='confirmado', total_gravado=?, confirmado_em=?
               WHERE id=?""",
            (gravados, agora(), lote_id),
        )
        db.execute("DELETE FROM grades_staging WHERE lote_id = ?", (lote_id,))

    _log(f"confirmar_lote:{lote_id}")
    flash(f"Notas gravadas: {gravados}. O boletim dos responsáveis já reflete essa atualização.", "ok")
    return redirect(url_for("importacao.notas_index"))


@importacao_bp.route("/notas/<int:lote_id>/descartar", methods=["POST"])
@roles_required("admin", "secretaria")
def descartar(lote_id):
    with get_db() as db:
        lote = db.execute("SELECT * FROM import_lotes WHERE id = ?", (lote_id,)).fetchone()
        if not lote or lote["status"] != "pendente" or lote["processando"]:
            abort(404)
        db.execute("DELETE FROM grades_staging WHERE lote_id = ?", (lote_id,))
        db.execute("UPDATE import_lotes SET status='descartado' WHERE id=?", (lote_id,))
    _log(f"descartar_lote:{lote_id}")
    flash("Lote descartado — nada foi gravado no boletim.", "ok")
    return redirect(url_for("importacao.notas_index"))


# --------------------------------------------------------- alunos / AEE ----
# Diferente da importação de notas, aqui não existe tela de conferência:
# o resultado (novo/atualizado) é objetivo e determinístico, sem
# interpretação de layout de PDF envolvida — o mesmo comportamento dos
# scripts de linha de comando, só que acionado pelo navegador. Isso permite
# subir a lista de alunos direto no servidor de produção sem o arquivo
# passar pelo Git/GitHub em nenhum momento.
def _salvar_upload_temporario(file):
    filename = secure_filename(f"{int(time.time())}_{file.filename}")
    caminho = config.UPLOADS_DIR / filename
    file.save(caminho)
    return caminho


@importacao_bp.route("/alunos")
@roles_required("admin", "secretaria")
def alunos_index():
    return render_template("importar_alunos.html", user=current_user(), series=config.SERIES_EF)


@importacao_bp.route("/alunos/upload-piloto", methods=["POST"])
@roles_required("admin", "secretaria")
def alunos_upload_piloto():
    file = request.files.get("planilha")
    serie = request.form.get("serie", "").strip()
    if not file or file.filename == "" or not file.filename.lower().endswith(".xlsx"):
        flash(
            "Selecione um arquivo .xlsx (se o original for .xls, converta no "
            "Excel/LibreOffice antes: \"Salvar como\" .xlsx).",
            "erro",
        )
        return redirect(url_for("importacao.alunos_index"))

    caminho = _salvar_upload_temporario(file)
    try:
        resultado = _import_students_lib.importar(str(caminho), serie)
    except Exception as exc:
        current_app.logger.exception("Falha ao importar planilha de alunos (PILOTO)")
        flash(f"Não foi possível importar a planilha: {exc}", "erro")
        return redirect(url_for("importacao.alunos_index"))
    finally:
        caminho.unlink(missing_ok=True)

    _log("upload_alunos_piloto")
    flash(
        f"Alunos importados: {resultado['novos']} novo(s), "
        f"{resultado['atualizados']} atualizado(s) (total na planilha: {resultado['total']}).",
        "ok",
    )
    return redirect(url_for("importacao.alunos_index"))


@importacao_bp.route("/alunos/upload-simplificado", methods=["POST"])
@roles_required("admin", "secretaria")
def alunos_upload_simplificado():
    file = request.files.get("planilha")
    if not file or file.filename == "" or not file.filename.lower().endswith(".xlsx"):
        flash("Selecione um arquivo .xlsx no formato simplificado (Turno, Turma, Nome do Aluno, ...).", "erro")
        return redirect(url_for("importacao.alunos_index"))

    caminho = _salvar_upload_temporario(file)
    try:
        resultado = _import_base_lib.importar(str(caminho))
    except Exception as exc:
        current_app.logger.exception("Falha ao importar planilha simplificada de alunos")
        flash(f"Não foi possível importar a planilha: {exc}", "erro")
        return redirect(url_for("importacao.alunos_index"))
    finally:
        caminho.unlink(missing_ok=True)

    _log("upload_alunos_simplificado")
    flash(
        f"Alunos importados: {resultado['novos']} novo(s), "
        f"{resultado['atualizados']} atualizado(s), "
        f"{resultado['aee_marcados']} marcado(s) como AEE.",
        "ok",
    )
    return redirect(url_for("importacao.alunos_index"))


@importacao_bp.route("/alunos/upload-projeto", methods=["POST"])
@roles_required("admin", "secretaria")
def alunos_upload_projeto():
    """Turma de projeto a partir do relatório "Alunos da Turma" do SGP
    (.xls, que é HTML por dentro, ou .xlsx). Não altera a turma regular
    dos alunos."""
    file = request.files.get("planilha")
    if not file or file.filename == "" or not file.filename.lower().endswith((".xls", ".xlsx", ".htm", ".html")):
        flash("Selecione o arquivo \"Alunos da Turma\" exportado do SGP (.xls ou .xlsx).", "erro")
        return redirect(url_for("importacao.alunos_index"))

    caminho = _salvar_upload_temporario(file)
    try:
        resultado = _import_projeto_lib.importar(str(caminho))
    except ValueError as exc:
        flash(str(exc), "erro")
        return redirect(url_for("importacao.alunos_index"))
    except Exception as exc:
        current_app.logger.exception("Falha ao importar turma de projeto")
        flash(f"Não foi possível importar o arquivo: {exc}", "erro")
        return redirect(url_for("importacao.alunos_index"))
    finally:
        caminho.unlink(missing_ok=True)

    _log(f"upload_turma_projeto:{resultado['turma_id']}")
    flash(
        f"Turma de projeto {'criada' if resultado['novo'] else 'atualizada'}: {resultado['nome']} "
        f"({resultado['turno'] or 'turno não informado'}). {resultado['total']} aluno(s) no arquivo, "
        f"{resultado['ativos']} ativo(s), {resultado['ligados']} ligado(s) ao cadastro.",
        "ok",
    )
    if resultado["nao_encontrados"]:
        flash(
            f"{len(resultado['nao_encontrados'])} aluno(s) sem cadastro no sistema (pelo código EOL) "
            f"ficaram só com o nome na turma de projeto.",
            "erro",
        )
    return redirect(url_for("staff.projeto_view", projeto_id=resultado["turma_id"]))


@importacao_bp.route("/alunos/upload-aee", methods=["POST"])
@roles_required("admin", "secretaria")
def alunos_upload_aee():
    file = request.files.get("planilha")
    if not file or file.filename == "" or not file.filename.lower().endswith(".xlsx"):
        flash("Selecione um arquivo .xlsx da lista AEE.", "erro")
        return redirect(url_for("importacao.alunos_index"))

    caminho = _salvar_upload_temporario(file)
    try:
        resultado = _import_aee_lib.importar(str(caminho))
    except Exception as exc:
        current_app.logger.exception("Falha ao importar planilha AEE")
        flash(f"Não foi possível importar a planilha: {exc}", "erro")
        return redirect(url_for("importacao.alunos_index"))
    finally:
        caminho.unlink(missing_ok=True)

    nao_localizados = len(resultado["nao_encontrados"])
    msg = f"AEE cruzados com sucesso: {resultado['encontrados']}."
    if nao_localizados:
        msg += (
            f" {nao_localizados} não localizado(s) — normal se ainda faltar "
            f"importar alunos de outras séries/turmas."
        )
    _log("upload_alunos_aee")
    flash(msg, "ok")
    return redirect(url_for("importacao.alunos_index"))


# ------------------------------------------------------------------ fotos --
# Upload de várias fotos de uma vez, casando cada arquivo com o aluno certo
# pelo nome do arquivo, no padrão "NOME DO ALUNO-EOL.jpg" (EOL = código do
# aluno): o EOL identifica o aluno e o nome confere se é mesmo ele. Arquivo
# só com o nome ("NOME DO ALUNO.jpg") continua valendo, casando pelo nome.
# Nada é salvo quando há dúvida (EOL de outro aluno, nome duplicado ou não
# encontrado): o arquivo aparece na lista de pendências, sem arriscar
# salvar a foto no aluno errado. Usado aqui e na aba Carteirinhas.
_EOL_NO_NOME = re.compile(r"^(?P<nome>.*?)[\s_\-.]*(?P<eol>\d{4,})$")


def _chave_nome(texto):
    texto = (texto or "").strip().upper().replace("_", " ").replace("-", " ")
    texto = " ".join(texto.split())
    sem_acento = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acento if not unicodedata.combining(c))


def separar_nome_e_eol(nome_arquivo):
    """'MARIA SILVA-7584678.jpg' -> ('MARIA SILVA', '7584678');
    'MARIA SILVA.jpg' -> ('MARIA SILVA', None)."""
    base = Path(nome_arquivo).stem.strip()
    m = _EOL_NO_NOME.match(base)
    if m and m.group("nome").strip(" _-."):
        return m.group("nome").strip(" _-."), m.group("eol")
    return base, None


def _nome_confere(nome_arquivo, aluno):
    """O nome do arquivo bate com o cadastro? Aceita o nome completo (de
    registro ou social) ou pequenas diferenças — mesmo primeiro nome e a
    maior parte dos nomes em comum (ex: arquivo sem um sobrenome)."""
    chave = _chave_nome(nome_arquivo)
    for cadastro in (aluno["nome"], aluno["nome_social"]):
        if not cadastro:
            continue
        chave_cad = _chave_nome(cadastro)
        if chave == chave_cad:
            return True
        a, b = chave.split(), chave_cad.split()
        if a and b and a[0] == b[0]:
            comuns = len(set(a) & set(b))
            if comuns >= 2 and comuns / max(len(a), len(b)) >= 0.6:
                return True
    return False


def casar_e_salvar_fotos(db, arquivos, turma_filtro=""):
    """Casa cada arquivo com um aluno ativo e salva a foto. Devolve
    (casados, nao_casados): casados = (arquivo, nome, turma, observação);
    nao_casados = (arquivo, motivo)."""
    alunos = db.execute(
        "SELECT id, nome, nome_social, turma, codigo_interno FROM students WHERE situacao = 'ATIVO'"
    ).fetchall()
    por_eol = {}
    por_chave = {}
    for a in alunos:
        if a["codigo_interno"]:
            por_eol.setdefault(str(a["codigo_interno"]).strip().lstrip("0"), []).append(a)
        if turma_filtro and a["turma"] != turma_filtro:
            continue
        for nome in {a["nome"], a["nome_social"]} - {None, ""}:
            por_chave.setdefault(_chave_nome(nome), []).append(a)

    casados, nao_casados = [], []
    for file in arquivos:
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_PHOTO_EXT:
            nao_casados.append((file.filename, "formato inválido (use JPG, PNG ou WEBP)"))
            continue

        nome_arquivo, eol = separar_nome_e_eol(file.filename)
        aluno, observacao = None, ""
        if eol:
            pelo_eol = por_eol.get(eol.lstrip("0"), [])
            if len(pelo_eol) == 1:
                candidato = pelo_eol[0]
                if _nome_confere(nome_arquivo, candidato):
                    aluno = candidato
                    observacao = "EOL e nome conferem"
                else:
                    nao_casados.append((
                        file.filename,
                        f"o EOL {eol} é de {candidato['nome']} ({candidato['turma']}), mas o nome no arquivo "
                        f"é \"{nome_arquivo}\" — confira o nome ou o EOL",
                    ))
                    continue
            elif len(pelo_eol) > 1:
                nao_casados.append((file.filename, f"mais de um aluno com o EOL {eol} no cadastro"))
                continue

        if aluno is None:
            candidatos = {c["id"]: c for c in por_chave.get(_chave_nome(nome_arquivo), [])}
            candidatos = list(candidatos.values())
            if len(candidatos) == 1:
                aluno = candidatos[0]
                observacao = (f"EOL {eol} não encontrado no cadastro — casado pelo nome" if eol
                              else "casado pelo nome (arquivo sem EOL)")
            elif not candidatos:
                motivo = "nenhum aluno com esse nome encontrado"
                if eol:
                    motivo = f"EOL {eol} não encontrado e nenhum aluno com esse nome"
                nao_casados.append((file.filename, motivo))
                continue
            else:
                nomes = ", ".join(f"{c['nome']} ({c['turma']})" for c in candidatos)
                nao_casados.append((file.filename, f"mais de um aluno com esse nome: {nomes} — inclua o EOL no nome do arquivo"))
                continue

        if turma_filtro and aluno["turma"] != turma_filtro:
            nao_casados.append((file.filename, f"é de {aluno['nome']}, da turma {aluno['turma']} (não da {turma_filtro})"))
            continue

        filename = secure_filename(f"aluno_{aluno['id']}.{ext}")
        _arquivos.salvar(_arquivos.FOTOS, filename, file.read(), db=db)
        # troca de formato (jpg -> png) não deixa foto velha pra trás
        _arquivos.apagar_por_prefixo(_arquivos.FOTOS, f"aluno_{aluno['id']}.", exceto=filename, db=db)
        db.execute("UPDATE students SET foto_path=?, updated_at=? WHERE id=?", (filename, agora(), aluno["id"]))
        casados.append((file.filename, aluno["nome_social"] or aluno["nome"], aluno["turma"], observacao))
    return casados, nao_casados


@importacao_bp.route("/fotos")
@roles_required("admin", "secretaria")
def fotos_index():
    with get_db() as db:
        turmas = db.execute("SELECT DISTINCT turma FROM students ORDER BY turma").fetchall()
    return render_template("importar_fotos.html", turmas=turmas, user=current_user())


@importacao_bp.route("/fotos/upload", methods=["POST"])
@roles_required("admin", "secretaria")
def fotos_upload():
    arquivos = [f for f in request.files.getlist("fotos") if f and f.filename]
    turma_filtro = request.form.get("turma", "").strip()

    if not arquivos:
        flash("Selecione pelo menos um arquivo de foto.", "erro")
        return redirect(url_for("importacao.fotos_index"))

    with get_db() as db:
        casados, nao_casados = casar_e_salvar_fotos(db, arquivos, turma_filtro)

    _log(f"upload_fotos_lote:{len(casados)}_casadas_{len(nao_casados)}_pendentes")
    return render_template(
        "importar_fotos_resultado.html", casados=casados, nao_casados=nao_casados, user=current_user()
    )
