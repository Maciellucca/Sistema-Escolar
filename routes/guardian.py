from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, session, redirect, url_for, flash

import config
from models import get_db, recomendacoes_por_bimestre
from auth import guardian_student_from_token
from routes.cursos import ciclo_da_serie

guardian_bp = Blueprint("guardian", __name__, url_prefix="/responsavel")


def _log(referencia, acao):
    with get_db() as db:
        db.execute(
            "INSERT INTO access_log (tipo, referencia, acao, ip) VALUES (?,?,?,?)",
            ("responsavel", referencia, acao, request.remote_addr),
        )


TOKEN_MAX_TENTATIVAS = 10
TOKEN_JANELA_MINUTOS = 15


def _tentativas_recentes_ip(ip):
    corte = (datetime.now(timezone.utc) - timedelta(minutes=TOKEN_JANELA_MINUTOS)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as db:
        row = db.execute(
            """SELECT COUNT(*) c FROM access_log
               WHERE tipo='responsavel' AND acao='login_falhou' AND ip = ?
                 AND created_at > ?""",
            (ip, corte),
        ).fetchone()
    return row["c"]


@guardian_bp.route("/", methods=["GET", "POST"])
def acesso():
    if request.method == "POST":
        if _tentativas_recentes_ip(request.remote_addr) >= TOKEN_MAX_TENTATIVAS:
            flash(f"Muitas tentativas. Aguarde {TOKEN_JANELA_MINUTOS} minutos e tente novamente.", "erro")
            return render_template("guardian_login.html")

        token = request.form.get("token", "").strip()
        aluno = guardian_student_from_token(token)
        if not aluno:
            _log(None, "login_falhou")
            flash("Código inválido. Confira os 6 números enviados pela secretaria.", "erro")
            return render_template("guardian_login.html")
        session["guardian_student_id"] = aluno["id"]
        _log(aluno["id"], "login")
        return redirect(url_for("guardian.boletim"))
    return render_template("guardian_login.html")


@guardian_bp.route("/sair")
def sair():
    session.pop("guardian_student_id", None)
    return redirect(url_for("guardian.acesso"))


@guardian_bp.route("/boletim")
def boletim():
    student_id = session.get("guardian_student_id")
    if not student_id:
        return redirect(url_for("guardian.acesso"))
    with get_db() as db:
        aluno = db.execute(
            """SELECT id, nome, nome_social, turma, serie, foto_path, recomendacoes, alteracoes_pendentes
               FROM students WHERE id = ?""",
            (student_id,),
        ).fetchone()
        grades = db.execute(
            """SELECT * FROM grades WHERE student_id = ?
               ORDER BY ano, bimestre, disciplina""",
            (student_id,),
        ).fetchall()
        recomendacoes = recomendacoes_por_bimestre(db, student_id) if aluno else {}
        cursos = []
        ciclo = ciclo_da_serie(aluno["serie"]) if aluno else None
        if ciclo:
            cursos = db.execute(
                "SELECT * FROM cursos_recomendados WHERE ativo = 1 AND ciclo = ? ORDER BY titulo",
                (ciclo,),
            ).fetchall()
    if not aluno:
        session.pop("guardian_student_id", None)
        return redirect(url_for("guardian.acesso"))

    # mesmo formato da ficha do aluno: {ano: {bimestre: [notas]}}, ano mais
    # recente primeiro — o template é compartilhado (_boletim_bimestres.html)
    por_ano = {}
    for g in grades:
        por_ano.setdefault(g["ano"], {}).setdefault(g["bimestre"], []).append(g)
    boletim = {ano: por_ano[ano] for ano in sorted(por_ano, reverse=True)}
    resumo = {
        (ano, bim): _resumo_bimestre(notas)
        for ano, bimestres in boletim.items() for bim, notas in bimestres.items()
    }

    # O portal do responsavel NUNCA expoe RA/CPF, filiacao, laudo AEE ou
    # qualquer outro dado sensivel alem do proprio boletim do aluno.
    return render_template(
        "area_do_aluno.html", aluno=aluno, boletim=boletim, resumo=resumo, cursos=cursos, ciclo=ciclo,
        recomendacoes_bimestre=recomendacoes,
        escola={"nome": config.ESCOLA_NOME, "endereco": config.ESCOLA_ENDERECO, "telefone": config.ESCOLA_TELEFONE},
        frequencia_minima=config.FREQUENCIA_MINIMA,
    )


@guardian_bp.route("/boletim.pdf")
def boletim_pdf():
    """Mesmo boletim em PDF da ficha do aluno (formato do SGP, uma folha
    por ano letivo), sem o código EOL do aluno."""
    from io import BytesIO
    from flask import send_file
    from scripts.gerar_boletim_detalhado import gerar_pdf_aluno_bytes, numero_na_turma

    student_id = session.get("guardian_student_id")
    if not student_id:
        return redirect(url_for("guardian.acesso"))
    with get_db() as db:
        aluno = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if not aluno:
            session.pop("guardian_student_id", None)
            return redirect(url_for("guardian.acesso"))
        grades = db.execute(
            "SELECT * FROM grades WHERE student_id = ? ORDER BY ano, bimestre, disciplina", (student_id,)
        ).fetchall()
        recomendacoes = recomendacoes_por_bimestre(db, student_id)
        numero = numero_na_turma(db, aluno)
    conteudo = gerar_pdf_aluno_bytes(aluno, grades, recomendacoes, numero, para_responsavel=True)
    _log(aluno["id"], "boletim_pdf")
    nome = (aluno["nome_social"] or aluno["nome"] or "aluno").replace("/", "-")
    return send_file(BytesIO(conteudo), mimetype="application/pdf", as_attachment=False,
                     download_name=f"Boletim - {nome}.pdf")


def _sem_lancamento(n):
    return n["conceito"] in (None, "", "-") and n["faltas"] is None and n["frequencia"] is None


def _resumo_bimestre(notas):
    """Números do topo de cada bimestre: frequência média dos componentes
    com frequência lançada, total de faltas e quantos estão com NS (não
    satisfatório). Conceitos: P = plenamente satisfatório, S = satisfatório,
    NS = não satisfatório."""
    lancadas = [n for n in notas if not _sem_lancamento(n)]
    freqs = [n["frequencia"] for n in lancadas if n["frequencia"] is not None]
    return {
        "frequencia": round(sum(freqs) / len(freqs), 1) if freqs else None,
        "faltas": sum(n["faltas"] or 0 for n in lancadas),
        "compensacoes": sum(n["compensacoes"] or 0 for n in lancadas),
        "nao_satisfatorio": sum(1 for n in lancadas if (n["conceito"] or "").strip().upper() == "NS"),
        "componentes": len(lancadas),
        "vazios": [n for n in notas if _sem_lancamento(n)],
        "lancadas": lancadas,
    }
