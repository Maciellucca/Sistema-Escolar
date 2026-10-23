"""
Arquivo morto: registro permanente de todo aluno que já passou pela
escola, organizado em gavetas por letra (A-Z) — igual à organização em
abas da planilha original. Aluno transferido entra aqui automaticamente
(ver models.adicionar_ao_arquivo_morto, chamada em
staff.transferir_aluno).
"""
import re
import string
import time
from datetime import date, datetime

import config
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

from models import get_db, inserir_arquivo_morto_manual, liberar_numero_arquivo_morto
from auth import roles_required, current_user
from scripts.import_arquivo_morto import importar as _importar_arquivo_morto

arquivo_morto_bp = Blueprint("arquivo_morto", __name__, url_prefix="/arquivo-morto")

LETRAS = list(string.ascii_uppercase)


def _data_nascimento(valor):
    """Lê a data como veio de cada origem — "2005-03-12" (sistema,
    transferência, cadastro manual) ou "12/03/2005" / "12/03/05" (texto de
    planilha importada) — e devolve um date, ou None se não der pra ler."""
    texto = str(valor or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto[:10] if formato == "%Y-%m-%d" else texto, formato).date()
        except ValueError:
            continue
    return None


def _log(acao):
    with get_db() as db:
        db.execute(
            "INSERT INTO access_log (tipo, referencia, acao, ip) VALUES (?,?,?,?)",
            ("staff", session.get("nome"), acao, request.remote_addr),
        )


@arquivo_morto_bp.route("/")
@roles_required("admin", "secretaria")
def index():
    busca = request.args.get("q", "").strip()
    nascimento_bruto = request.args.get("nascimento", "").strip()
    nascimento = _data_nascimento(nascimento_bruto)
    if nascimento_bruto and not nascimento:
        flash("Data de nascimento inválida — use o formato dd/mm/aaaa.", "erro")

    with get_db() as db:
        if busca:
            registros = db.execute(
                "SELECT * FROM arquivo_morto WHERE nome LIKE ? ORDER BY letra, id DESC",
                (f"%{busca}%",),
            ).fetchall()
        else:
            registros = db.execute("SELECT * FROM arquivo_morto ORDER BY letra, id DESC").fetchall()

    # a data é comparada já convertida (as origens gravam em formatos
    # diferentes), por isso o filtro é feito aqui e não no SQL
    if nascimento:
        registros = [r for r in registros if _data_nascimento(r["data_nascimento"]) == nascimento]

    por_letra = {letra: [] for letra in LETRAS}
    for r in registros:
        if r["letra"] in por_letra:
            por_letra[r["letra"]].append(r)

    filtrando = bool(busca or nascimento)
    return render_template(
        "arquivo_morto_index.html", letras=LETRAS, por_letra=por_letra, busca=busca,
        nascimento=nascimento.isoformat() if nascimento else "", filtrando=filtrando,
        total_encontrados=len(registros), formatar_data=_formatar_data, user=current_user(),
    )


def _formatar_data(valor):
    d = _data_nascimento(valor)
    return d.strftime("%d/%m/%Y") if d else (valor or "—")


@arquivo_morto_bp.route("/<int:registro_id>/liberar", methods=["POST"])
@roles_required("admin", "secretaria")
def liberar(registro_id):
    """Deixa o registro em branco (ex: aluno duplicado) sem perder o
    número: o próximo aluno que entrar nessa letra fica nesse lugar."""
    with get_db() as db:
        registro = liberar_numero_arquivo_morto(db, registro_id)
    if not registro:
        flash("Registro não encontrado ou já liberado.", "erro")
        return redirect(url_for("arquivo_morto.index"))
    _log(f"liberar_arquivo_morto:{registro['letra']}{registro['numero']}:{registro['nome']}")
    flash(
        f"Nº {registro['numero']} da letra {registro['letra']} liberado ({registro['nome']} saiu do Arquivo Morto). "
        f"O próximo aluno da letra {registro['letra']} ocupa esse número.",
        "ok",
    )
    return redirect(url_for("arquivo_morto.index", _anchor=f"letra-{registro['letra']}"))


@arquivo_morto_bp.route("/importar", methods=["GET", "POST"])
@roles_required("admin", "secretaria")
def importar():
    if request.method == "GET":
        return render_template("arquivo_morto_importar.html", user=current_user())

    file = request.files.get("planilha")
    if not file or file.filename == "" or not file.filename.lower().endswith(".xlsx"):
        flash("Selecione um arquivo .xlsx (converta de .xls pelo Excel/LibreOffice, se precisar).", "erro")
        return redirect(url_for("arquivo_morto.importar"))

    filename = f"{int(time.time())}_{file.filename}"
    caminho = config.UPLOADS_DIR / filename
    file.save(caminho)
    try:
        resultado = _importar_arquivo_morto(str(caminho))
    except Exception as exc:
        flash(f"Não foi possível importar a planilha: {exc}", "erro")
        return redirect(url_for("arquivo_morto.importar"))
    finally:
        caminho.unlink(missing_ok=True)

    _log(f"importar_arquivo_morto:{resultado['importados']}")
    return render_template("arquivo_morto_importar_resultado.html", resultado=resultado, user=current_user())


@arquivo_morto_bp.route("/novo", methods=["GET", "POST"])
@roles_required("admin", "secretaria")
def novo():
    if request.method == "GET":
        return render_template("arquivo_morto_novo.html", user=current_user())

    nome = request.form.get("nome", "").strip().upper()
    data_nascimento = request.form.get("data_nascimento", "").strip() or None
    if not nome:
        flash("Informe o nome do aluno.", "erro")
        return redirect(url_for("arquivo_morto.novo"))

    with get_db() as db:
        inserido = inserir_arquivo_morto_manual(db, nome, data_nascimento)

    if not inserido:
        flash(f"{nome} já consta no Arquivo Morto — nenhum registro duplicado foi criado.", "erro")
        return redirect(url_for("arquivo_morto.novo"))

    _log(f"criar_arquivo_morto_manual:{nome}")
    flash(f"{nome} adicionado ao Arquivo Morto.", "ok")
    return redirect(url_for("arquivo_morto.index"))
