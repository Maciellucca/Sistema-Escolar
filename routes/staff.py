import hmac
import mimetypes
import re
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from flask import (
    Blueprint, render_template, request, redirect, url_for, session,
    flash, send_file, send_from_directory, abort, current_app
)
from werkzeug.utils import secure_filename

import arquivos
import config
import mailer
from models import salvar_nota, trocar_todos_codigos_responsavel, salvar_recomendacao_bimestre, recomendacoes_por_bimestre, get_db, agora, salvar_turma_turno, get_config, set_config, adicionar_ao_arquivo_morto, propagar_dados_aluno, salvar_contato_responsavel
from auth import (
    login_required, roles_required, verify_password, hash_password, current_user,
    codigo_responsavel, papel_efetivo,
)

staff_bp = Blueprint("staff", __name__)

ALLOWED_PHOTO_EXT = {"jpg", "jpeg", "png", "webp"}


def _log(tipo, referencia, acao):
    with get_db() as db:
        db.execute(
            "INSERT INTO access_log (tipo, referencia, acao, ip) VALUES (?,?,?,?)",
            (tipo, referencia, acao, request.remote_addr),
        )


# --------------------------------------------------------------- login -----
LOGIN_MAX_TENTATIVAS = 5
LOGIN_JANELA_MINUTOS = 15


def _tentativas_recentes(username, ip):
    corte = (datetime.now(timezone.utc) - timedelta(minutes=LOGIN_JANELA_MINUTOS)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as db:
        row = db.execute(
            """SELECT COUNT(*) c FROM access_log
               WHERE tipo='staff' AND acao='login_falhou'
                 AND (referencia = ? OR ip = ?)
                 AND created_at > ?""",
            (username, ip, corte),
        ).fetchone()
    return row["c"]


@staff_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        senha = request.form.get("senha", "")

        if _tentativas_recentes(username, request.remote_addr) >= LOGIN_MAX_TENTATIVAS:
            flash(
                f"Muitas tentativas de login. Aguarde {LOGIN_JANELA_MINUTOS} minutos e tente novamente.",
                "erro",
            )
            return render_template("login.html")

        with get_db() as db:
            user = db.execute(
                "SELECT * FROM users WHERE username = ? AND ativo = 1", (username,)
            ).fetchone()
        if user and verify_password(senha, user["password_hash"]):
            session.clear()
            session["user_id"] = user["id"]
            session["papel"] = papel_efetivo(user["papel"])
            session["papel_cadastro"] = user["papel"]
            session["nome"] = user["nome"]
            _log("staff", username, "login")
            if user["trocar_senha"]:
                # senha provisória gerada pelo admin: só entra no sistema depois de criar a própria
                session["trocar_senha"] = True
                flash("Você entrou com uma senha provisória. Crie agora a sua senha para continuar.", "erro")
                return redirect(url_for("staff.alterar_senha"))
            return redirect(request.args.get("next") or url_for("staff.dashboard"))
        _log("staff", username, "login_falhou")
        flash("Usuário ou senha inválidos.", "erro")
    return render_template("login.html")


@staff_bp.route("/logout")
def logout():
    if session.get("user_id"):
        _log("staff", session.get("nome"), "logout")
    session.clear()
    return redirect(url_for("staff.login"))


# -------------------------------------------------- esqueci minha senha ----
RESET_MAX_PEDIDOS = 3          # códigos por usuário na janela
RESET_MAX_PEDIDOS_IP = 10      # códigos por IP na janela
RESET_JANELA_MINUTOS = 30
RESET_MAX_TENTATIVAS = 5       # códigos errados antes de invalidar
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _corte(minutos):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutos)).strftime("%Y-%m-%d %H:%M:%S")


def _mascarar_email(email):
    usuario, _, dominio = email.partition("@")
    return f"{usuario[:2]}{'*' * max(1, len(usuario) - 2)}@{dominio}"


@staff_bp.route("/login/esqueci-senha", methods=["GET", "POST"])
def esqueci_senha():
    """Passo 1: a pessoa informa o usuário ou o e-mail; se existir um
    usuário ativo com e-mail cadastrado, um código de 6 dígitos é enviado
    pra esse e-mail. A resposta é a mesma exista ou não o usuário (não
    revela quem tem cadastro)."""
    configurado = mailer.email_configurado()
    if request.method == "GET" or not configurado:
        return render_template("esqueci_senha.html", configurado=configurado)

    identificador = request.form.get("identificador", "").strip()
    if not identificador:
        flash("Informe seu usuário ou e-mail.", "erro")
        return render_template("esqueci_senha.html", configurado=configurado)

    ip = request.remote_addr
    with get_db() as db:
        pedidos_ip = db.execute(
            """SELECT COUNT(*) c FROM access_log WHERE tipo='staff' AND acao='reset_senha_pedido'
               AND ip = ? AND created_at > ?""",
            (ip, _corte(RESET_JANELA_MINUTOS)),
        ).fetchone()["c"]
        user = db.execute(
            """SELECT * FROM users WHERE ativo = 1 AND email IS NOT NULL AND email <> ''
               AND (username = ? OR LOWER(email) = LOWER(?))""",
            (identificador, identificador),
        ).fetchone()
        pedidos_user = 0
        if user:
            pedidos_user = db.execute(
                "SELECT COUNT(*) c FROM password_reset_codes WHERE user_id = ? AND created_at > ?",
                (user["id"], _corte(RESET_JANELA_MINUTOS)),
            ).fetchone()["c"]

    if pedidos_ip >= RESET_MAX_PEDIDOS_IP or pedidos_user >= RESET_MAX_PEDIDOS:
        flash(f"Muitos pedidos de código. Aguarde {RESET_JANELA_MINUTOS} minutos e tente novamente.", "erro")
        return render_template("esqueci_senha.html", configurado=configurado)

    _log("staff", identificador[:80], "reset_senha_pedido")
    session.pop("reset_user_id", None)
    if user:
        codigo = f"{secrets.randbelow(10**6):06d}"
        expira = (datetime.now(timezone.utc) + timedelta(minutes=config.RESET_SENHA_MINUTOS)).strftime("%Y-%m-%d %H:%M:%S")
        with get_db() as db:
            db.execute("UPDATE password_reset_codes SET usado = 1 WHERE user_id = ? AND usado = 0", (user["id"],))
            db.execute(
                """INSERT INTO password_reset_codes (user_id, codigo_hash, expira_em, ip, created_at)
                   VALUES (?,?,?,?,?)""",
                (user["id"], hash_password(codigo), expira, ip, agora()),
            )
        try:
            mailer.enviar_email(
                user["email"],
                "Código para redefinir sua senha - Sistema Escolar",
                f"Olá, {user['nome']}.\n\n"
                f"Seu código para redefinir a senha do Sistema Escolar é: {codigo}\n\n"
                f"Ele vale por {config.RESET_SENHA_MINUTOS} minutos e só pode ser usado uma vez.\n"
                f"Usuário: {user['username']}\n\n"
                "Se não foi você que pediu, ignore este e-mail — sua senha continua a mesma.",
            )
        except Exception:
            current_app.logger.exception("Falha ao enviar e-mail de redefinição de senha")
            flash("Não foi possível enviar o e-mail agora. Tente novamente mais tarde ou procure o administrador.", "erro")
            return render_template("esqueci_senha.html", configurado=configurado)
        session["reset_user_id"] = user["id"]
        _log("staff", user["username"], "reset_senha_codigo_enviado")

    flash(
        "Se houver um usuário com esse login ou e-mail e um e-mail cadastrado, enviamos um código de "
        f"6 dígitos (válido por {config.RESET_SENHA_MINUTOS} minutos). Confira também a caixa de spam.",
        "ok",
    )
    return redirect(url_for("staff.redefinir_senha"))


@staff_bp.route("/login/redefinir-senha", methods=["GET", "POST"])
def redefinir_senha():
    """Passo 2: código recebido por e-mail + nova senha."""
    if request.method == "GET":
        return render_template("redefinir_senha.html")

    codigo = re.sub(r"\D", "", request.form.get("codigo", ""))
    nova = request.form.get("nova_senha", "")
    nova2 = request.form.get("nova_senha2", "")
    if len(nova) < 8:
        flash("A nova senha deve ter pelo menos 8 caracteres.", "erro")
        return render_template("redefinir_senha.html")
    if nova != nova2:
        flash("As senhas não conferem.", "erro")
        return render_template("redefinir_senha.html")

    user_id = session.get("reset_user_id")
    invalido = "Código inválido ou expirado. Peça um novo código."
    if not user_id:
        flash(invalido, "erro")
        return render_template("redefinir_senha.html")

    with get_db() as db:
        pedido = db.execute(
            """SELECT * FROM password_reset_codes WHERE user_id = ? AND usado = 0
               ORDER BY id DESC LIMIT 1""",
            (user_id,),
        ).fetchone()
        valido = (
            pedido is not None
            and str(pedido["expira_em"])[:19] > agora()
            and pedido["tentativas"] < RESET_MAX_TENTATIVAS
        )
        if valido and len(codigo) == 6 and verify_password(codigo, pedido["codigo_hash"]):
            db.execute("UPDATE users SET password_hash = ?, trocar_senha = 0 WHERE id = ?", (hash_password(nova), user_id))
            db.execute("UPDATE password_reset_codes SET usado = 1 WHERE user_id = ?", (user_id,))
            user = db.execute("SELECT username FROM users WHERE id = ?", (user_id,)).fetchone()
            ok = True
        else:
            ok = False
            if pedido is not None:
                db.execute(
                    "UPDATE password_reset_codes SET tentativas = tentativas + 1 WHERE id = ?", (pedido["id"],)
                )
                restantes = RESET_MAX_TENTATIVAS - pedido["tentativas"] - 1
                if valido and restantes > 0:
                    invalido = f"Código incorreto. Você ainda tem {restantes} tentativa(s)."

    if not ok:
        _log("staff", str(user_id), "reset_senha_codigo_errado")
        flash(invalido, "erro")
        return render_template("redefinir_senha.html")

    session.pop("reset_user_id", None)
    _log("staff", user["username"], "reset_senha_concluido")
    flash("Senha redefinida. Entre com a nova senha.", "ok")
    return redirect(url_for("staff.login"))


# --------------------------------------------------- criação de admin ------
@staff_bp.route("/login/criar-admin", methods=["GET", "POST"])
def criar_admin():
    """Provisiona um usuário ADMINISTRADOR. Não é um cadastro público: só
    segue em frente quem digitar a chave de configuração do servidor
    (ADMIN_SETUP_KEY / SECRET_KEY no .env) — quem não tem acesso ao
    servidor não consegue criar um acesso admin por aqui."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        nome = request.form.get("nome", "").strip()
        setor = request.form.get("setor", "").strip()
        email = request.form.get("email", "").strip()
        senha = request.form.get("senha", "")
        senha2 = request.form.get("senha2", "")
        chave = request.form.get("chave", "")

        erro = None
        if not hmac.compare_digest(chave, config.ADMIN_SETUP_KEY):
            erro = "Chave de configuração inválida."
        elif not username or not nome or not setor:
            erro = "Preencha usuário, nome e setor."
        elif email and (len(email) > 150 or not EMAIL_RE.match(email)):
            erro = "E-mail inválido."
        elif len(senha) < 8:
            erro = "A senha deve ter pelo menos 8 caracteres."
        elif senha != senha2:
            erro = "As senhas não conferem."

        if not erro:
            with get_db() as db:
                existe = db.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone()
                if existe:
                    erro = "Já existe um usuário com esse nome de login."
                else:
                    db.execute(
                        """INSERT INTO users (username, password_hash, nome, setor, papel, email)
                           VALUES (?,?,?,?, 'admin', ?)""",
                        (username, hash_password(senha), nome, setor, email or None),
                    )
            if not erro:
                _log("staff", username, "criar_admin")

        if erro:
            flash(erro, "erro")
            return render_template("criar_admin.html", username=username, nome=nome, setor=setor, email=email)

        flash(f"Usuário administrador '{username}' criado. Faça login normalmente.", "ok")
        return redirect(url_for("staff.login"))

    return render_template("criar_admin.html")


# ------------------------------------------------------- minha conta -------
@staff_bp.route("/minha-conta/senha", methods=["GET", "POST"])
@login_required
def alterar_senha():
    if request.method == "POST":
        atual = request.form.get("senha_atual", "")
        nova = request.form.get("nova_senha", "")
        nova2 = request.form.get("nova_senha2", "")

        with get_db() as db:
            user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

        erro = None
        if not verify_password(atual, user["password_hash"]):
            erro = "Senha atual incorreta."
        elif len(nova) < 8:
            erro = "A nova senha deve ter pelo menos 8 caracteres."
        elif nova != nova2:
            erro = "As senhas não conferem."
        elif nova == atual:
            erro = "A nova senha precisa ser diferente da atual."

        if erro:
            flash(erro, "erro")
            return render_template("alterar_senha.html", user=current_user())

        with get_db() as db:
            db.execute(
                "UPDATE users SET password_hash = ?, trocar_senha = 0 WHERE id = ?",
                (hash_password(nova), session["user_id"]),
            )
        session.pop("trocar_senha", None)
        _log("staff", session.get("nome"), "alterar_senha")
        flash("Senha alterada com sucesso.", "ok")
        return redirect(url_for("staff.dashboard"))

    return render_template("alterar_senha.html", user=current_user())


@staff_bp.route("/minha-conta/email", methods=["POST"])
@login_required
def alterar_email():
    """E-mail usado pra receber o código do "Esqueci minha senha". Pede a
    senha atual, pra ninguém trocar o e-mail de uma sessão esquecida aberta."""
    email = request.form.get("email", "").strip()
    senha = request.form.get("senha_atual_email", "")
    with get_db() as db:
        user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if not verify_password(senha, user["password_hash"]):
            flash("Senha atual incorreta — o e-mail não foi alterado.", "erro")
            return redirect(url_for("staff.alterar_senha"))
        if email and (len(email) > 150 or not EMAIL_RE.match(email)):
            flash("E-mail inválido.", "erro")
            return redirect(url_for("staff.alterar_senha"))
        if email and db.execute(
            "SELECT 1 FROM users WHERE LOWER(email) = LOWER(?) AND id <> ?", (email, user["id"])
        ).fetchone():
            flash("Esse e-mail já está cadastrado para outro usuário.", "erro")
            return redirect(url_for("staff.alterar_senha"))
        db.execute("UPDATE users SET email = ? WHERE id = ?", (email or None, user["id"]))
    _log("staff", session.get("nome"), "alterar_email")
    flash("E-mail de recuperação salvo." if email else "E-mail de recuperação removido.", "ok")
    return redirect(url_for("staff.alterar_senha"))


def _mover(lista, item, direcao, mesmo_grupo=None):
    """Troca o item de lugar com o vizinho de cima/baixo. Com
    mesmo_grupo, o vizinho é o próximo item da mesma categoria (a ordem
    dos itens é uma lista só, mas cada um só se move dentro da sua)."""
    if item not in lista:
        return lista
    vizinhos = [i for i in lista if mesmo_grupo is None or i in mesmo_grupo]
    idx = vizinhos.index(item)
    alvo_idx = idx - 1 if direcao == "subir" else idx + 1 if direcao == "descer" else idx
    if alvo_idx == idx or not 0 <= alvo_idx < len(vizinhos):
        return lista
    a, b = lista.index(item), lista.index(vizinhos[alvo_idx])
    lista[a], lista[b] = lista[b], lista[a]
    return lista


@staff_bp.route("/configuracoes/menu-lateral", methods=["GET", "POST"])
@roles_required("admin")
def ordenar_sidebar():
    """Ordem do menu lateral — configuração única, vale pra todo mundo
    que usa o sistema (não é por usuário). Move categorias inteiras
    (campo "grupo") ou itens dentro da própria categoria (campo "item")."""
    import menu_lateral

    with get_db() as db:
        if request.method == "POST":
            direcao = request.form.get("direcao", "")
            grupo = request.form.get("grupo", "")
            item = request.form.get("item", "")
            if grupo:
                set_config(db, "ordem_sidebar_grupos", ",".join(_mover(menu_lateral.ordem_grupos(db), grupo, direcao)))
                alvo = f"grupo:{grupo}"
            else:
                do_grupo = next((g["itens"] for g in config.GRUPOS_SIDEBAR if item in g["itens"]), [])
                set_config(db, "ordem_sidebar", ",".join(_mover(menu_lateral.ordem_itens(db), item, direcao, do_grupo)))
                alvo = item
        else:
            grupos = [
                (g, [(i, config.ROTULOS_SIDEBAR[i]) for i in ids])
                for g, ids in menu_lateral.grupos_ordenados(db)
            ]

    if request.method == "POST":
        _log("staff", session.get("nome"), f"ordenar_sidebar:{alvo}:{direcao}")
        return redirect(url_for("staff.ordenar_sidebar"))

    return render_template("ordenar_sidebar.html", grupos=grupos, user=current_user())


# ----------------------------------------------------------- dashboard -----
ORDEM_TURNOS = ["Manhã", "Integral", "Tarde"]


@staff_bp.route("/")
@login_required
def dashboard():
    with get_db() as db:
        turmas = db.execute(
            """SELECT s.turma, s.serie, COUNT(*) AS total, SUM(s.aee) AS total_aee, tt.turno
               FROM students s
               LEFT JOIN turma_turno tt ON tt.turma = s.turma
               WHERE s.situacao = 'ATIVO'
               GROUP BY s.turma
               ORDER BY s.serie, s.turma"""
        ).fetchall()
        total_alunos = db.execute(
            "SELECT COUNT(*) c FROM students WHERE situacao = 'ATIVO'"
        ).fetchone()["c"]
        total_aee = db.execute(
            "SELECT COUNT(*) c FROM students WHERE situacao = 'ATIVO' AND aee = 1"
        ).fetchone()["c"]

    total_turmas = len(turmas)

    # turno -> {serie: [turmas]} ; turmas sem turno ficam num grupo à parte,
    # mas ainda separadas por série. Resumo (contagem) por turno é
    # calculado aqui pra aparecer fechado na gaveta, sem precisar abrir.
    turmas_por_turno = {turno: {} for turno in ORDEM_TURNOS}
    resumo_turno = {turno: {"turmas": 0, "alunos": 0} for turno in ORDEM_TURNOS}
    turmas_sem_turno = {}
    resumo_sem_turno = {"turmas": 0, "alunos": 0}
    for t in turmas:
        if t["turno"] in turmas_por_turno:
            destino, resumo = turmas_por_turno[t["turno"]], resumo_turno[t["turno"]]
        else:
            destino, resumo = turmas_sem_turno, resumo_sem_turno
        destino.setdefault(t["serie"] or "Série não definida", []).append(t)
        resumo["turmas"] += 1
        resumo["alunos"] += t["total"]

    with get_db() as db:
        projetos = db.execute(
            """SELECT p.id, p.nome, p.turma, p.descricao, p.turno, p.ano,
                      SUM(CASE WHEN UPPER(TRIM(a.situacao)) = 'ATIVO' THEN 1 ELSE 0 END) AS ativos
               FROM turmas_projeto p LEFT JOIN turma_projeto_alunos a ON a.turma_projeto_id = p.id
               GROUP BY p.id, p.nome, p.turma, p.descricao, p.turno, p.ano
               ORDER BY p.turno, p.nome"""
        ).fetchall()

    return render_template(
        "dashboard.html", user=current_user(), projetos=projetos,
        ordem_turnos=ORDEM_TURNOS, turmas_por_turno=turmas_por_turno, turmas_sem_turno=turmas_sem_turno,
        resumo_turno=resumo_turno, resumo_sem_turno=resumo_sem_turno,
        total_alunos=total_alunos, total_aee=total_aee, total_turmas=total_turmas,
    )


@staff_bp.route("/turmas/turnos", methods=["GET", "POST"])
@roles_required("admin", "secretaria")
def configurar_turnos():
    with get_db() as db:
        if request.method == "POST":
            for turma in request.form.getlist("turma"):
                turno = request.form.get(f"turno::{turma}", "").strip()
                salvar_turma_turno(db, turma, turno or None)
            atualizado = True
        else:
            atualizado = False
            turmas = db.execute(
                """SELECT s.turma, COUNT(*) total, tt.turno
                   FROM students s
                   LEFT JOIN turma_turno tt ON tt.turma = s.turma
                   WHERE s.situacao = 'ATIVO'
                   GROUP BY s.turma
                   ORDER BY s.turma"""
            ).fetchall()

    if atualizado:
        _log("staff", session.get("nome"), "configurar_turnos")
        flash("Turnos atualizados.", "ok")
        return redirect(url_for("staff.dashboard"))

    return render_template(
        "configurar_turnos.html", turmas=turmas, ordem_turnos=ORDEM_TURNOS, user=current_user()
    )


@staff_bp.route("/turma/<turma>")
@login_required
def turma_view(turma):
    with get_db() as db:
        alunos = db.execute(
            """SELECT id, nome, nome_social, foto_path, aee, situacao, serie
               FROM students WHERE turma = ? AND situacao = 'ATIVO' ORDER BY nome""",
            (turma,),
        ).fetchall()
        bimestres = _bimestres_lancados_turma(db, turma)
    if not alunos:
        abort(404)
    return render_template("turma.html", turma=turma, alunos=alunos, bimestres_lancados=bimestres,
                           ano_letivo=config.ANO_LETIVO, user=current_user())


def _bimestres_lancados_turma(db, turma):
    """Bimestres do ano letivo vigente com nota lançada para algum aluno
    ativo da turma, em ordem (o último é o bimestre vigente)."""
    linhas = db.execute(
        """SELECT DISTINCT g.bimestre FROM grades g JOIN students s ON s.id = g.student_id
           WHERE s.turma = ? AND s.situacao = 'ATIVO' AND g.ano = ? ORDER BY g.bimestre""",
        (turma, config.ANO_LETIVO),
    ).fetchall()
    return [l["bimestre"] for l in linhas]


@staff_bp.route("/turma/<turma>/boletins.pdf")
@login_required
def boletins_turma_pdf(turma):
    """Boletins dos alunos ativos da turma no formato do Boletim Escolar
    Detalhado do SGP: uma folha por aluno com o ano letivo inteiro
    (1º a 4º bimestre + Final). O número de cada aluno é a posição dele na
    lista da turma (ordem alfabética)."""
    from scripts.gerar_boletim_detalhado import gerar_pdf_turma_bytes

    ano = config.ANO_LETIVO
    with get_db() as db:
        if not _bimestres_lancados_turma(db, turma):
            flash(f"A turma {turma} ainda não tem notas lançadas em {ano}.", "erro")
            return redirect(url_for("staff.turma_view", turma=turma))
        alunos = db.execute(
            "SELECT * FROM students WHERE turma = ? AND situacao = 'ATIVO' ORDER BY nome", (turma,)
        ).fetchall()
        itens, sem_lancamento = [], []
        for numero, aluno in enumerate(alunos, start=1):
            notas = db.execute(
                "SELECT * FROM grades WHERE student_id = ? AND ano = ? ORDER BY bimestre, disciplina",
                (aluno["id"], ano),
            ).fetchall()
            if not notas:
                sem_lancamento.append((numero, aluno))
                continue
            itens.append((numero, aluno, notas, recomendacoes_por_bimestre(db, aluno["id"])))
    conteudo = gerar_pdf_turma_bytes(itens, ano, turma, sem_lancamento)
    _log("staff", session.get("nome"), f"boletins_turma_pdf:{turma}:{ano}")
    return send_file(BytesIO(conteudo), mimetype="application/pdf", as_attachment=False,
                     download_name=f"Boletins - Turma {turma} - {ano}.pdf")


# ------------------------------------------------------ turmas de projeto ----
@staff_bp.route("/projeto/<int:projeto_id>")
@login_required
def projeto_view(projeto_id):
    """Turma de projeto (importada do "Alunos da Turma" do SGP): lista dos
    alunos com a turma regular de cada um. Os ativos vêm primeiro; os
    demais (ex: VÍNCULO INDEVIDO) ficam numa lista à parte."""
    with get_db() as db:
        projeto = db.execute("SELECT * FROM turmas_projeto WHERE id = ?", (projeto_id,)).fetchone()
        if not projeto:
            abort(404)
        alunos = db.execute(
            """SELECT tpa.*, s.turma AS turma_regular, s.serie, s.foto_path, s.aee, s.nome_social,
                      s.situacao AS situacao_cadastro
               FROM turma_projeto_alunos tpa LEFT JOIN students s ON s.id = tpa.student_id
               WHERE tpa.turma_projeto_id = ? ORDER BY tpa.numero, tpa.nome""",
            (projeto_id,),
        ).fetchall()
        ativos = [a for a in alunos if (a["situacao"] or "").strip().upper() == "ATIVO"]
    outros = [a for a in alunos if a not in ativos]
    return render_template("projeto.html", projeto=projeto, ativos=ativos, outros=outros, user=current_user())


@staff_bp.route("/projeto/<int:projeto_id>/excluir", methods=["POST"])
@roles_required("admin", "secretaria")
def excluir_projeto(projeto_id):
    """Apaga só a turma de projeto; o cadastro dos alunos não muda."""
    with get_db() as db:
        projeto = db.execute("SELECT nome FROM turmas_projeto WHERE id = ?", (projeto_id,)).fetchone()
        if not projeto:
            abort(404)
        db.execute("DELETE FROM turma_projeto_alunos WHERE turma_projeto_id = ?", (projeto_id,))
        db.execute("DELETE FROM turmas_projeto WHERE id = ?", (projeto_id,))
    _log("staff", session.get("nome"), f"excluir_projeto:{projeto_id}")
    flash(f"Turma de projeto {projeto['nome']} excluída.", "ok")
    return redirect(url_for("staff.dashboard"))


# ------------------------------------------------------ usuários da equipe ----
# AEE não é perfil de login (é a marcação dos alunos da Educação Especial);
# usuários antigos com papel 'aee' continuam entrando e aparecem na tela com
# "AEE (perfil antigo)" para o admin trocar pelo perfil certo.
PAPEIS_USUARIO = [("secretaria", "Secretaria"), ("professor", "Professor(a) / Coordenação"),
                  ("pot", "POT"), ("direcao", "Direção"), ("admin", "Administrador")]
DESCRICAO_PAPEL = {
    "secretaria": "Alunos, turmas, importações e Arquivo Morto.",
    "professor": "Alunos, turmas e boletins.",
    "pot": "Consulta de alunos e turmas.",
    "direcao": "Acesso completo, igual ao administrador.",
    "admin": "Acesso completo, inclusive usuários da equipe.",
}
ROTULOS_PAPEL_ANTIGO = {"aee": "AEE (perfil antigo)"}
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,40}$")
ALFABETO_SENHA = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"  # sem 0/O, 1/l/I


def gerar_senha_provisoria(tamanho=10):
    return "".join(secrets.choice(ALFABETO_SENHA) for _ in range(tamanho))


def _tela_usuarios(senha_gerada=None, usuario_senha=None, form=None):
    with get_db() as db:
        usuarios = db.execute(
            "SELECT id, username, nome, setor, papel, email, ativo, trocar_senha FROM users ORDER BY ativo DESC, nome"
        ).fetchall()
    return render_template(
        "usuarios.html", usuarios=usuarios, papeis=PAPEIS_USUARIO, rotulo_papel={**ROTULOS_PAPEL_ANTIGO, **dict(PAPEIS_USUARIO)}, descricao_papel=DESCRICAO_PAPEL,
        senha_gerada=senha_gerada, usuario_senha=usuario_senha, form=form or {}, user=current_user(),
    )


@staff_bp.route("/configuracoes/usuarios")
@roles_required("admin")
def usuarios():
    """Usuários da equipe: só o administrador vê. As senhas nunca aparecem
    (o banco guarda só o hash); para quem esqueceu, gera-se uma senha
    provisória, que a pessoa é obrigada a trocar no primeiro acesso."""
    return _tela_usuarios()


@staff_bp.route("/configuracoes/usuarios/novo", methods=["POST"])
@roles_required("admin")
def criar_usuario():
    form = {k: request.form.get(k, "").strip() for k in ("username", "nome", "setor", "papel", "email")}
    erro = None
    if not USERNAME_RE.match(form["username"]):
        erro = "Usuário (login) com 3 a 40 caracteres, sem espaço nem acento (letras, números, ponto, - ou _)."
    elif not form["nome"]:
        erro = "Informe o nome da pessoa."
    elif form["papel"] not in dict(PAPEIS_USUARIO):
        erro = "Escolha o perfil de acesso."
    elif form["email"] and (len(form["email"]) > 150 or not EMAIL_RE.match(form["email"])):
        erro = "E-mail inválido."
    if not erro:
        with get_db() as db:
            if db.execute("SELECT 1 FROM users WHERE LOWER(username) = LOWER(?)", (form["username"],)).fetchone():
                erro = f"Já existe um usuário com o login {form['username']}."
    if erro:
        flash(erro, "erro")
        return _tela_usuarios(form=form)

    senha = gerar_senha_provisoria()
    with get_db() as db:
        db.execute(
            """INSERT INTO users (username, password_hash, nome, setor, papel, email, ativo, trocar_senha)
               VALUES (?,?,?,?,?,?,1,1)""",
            (form["username"], hash_password(senha), form["nome"], form["setor"] or None, form["papel"],
             form["email"] or None),
        )
    _log("staff", session.get("nome"), f"criar_usuario:{form['username']}")
    flash(f"Usuário {form['username']} criado.", "ok")
    return _tela_usuarios(senha_gerada=senha, usuario_senha=form["username"])


@staff_bp.route("/configuracoes/usuarios/<int:usuario_id>/senha-provisoria", methods=["POST"])
@roles_required("admin")
def senha_provisoria(usuario_id):
    with get_db() as db:
        alvo = db.execute("SELECT id, username, nome FROM users WHERE id = ?", (usuario_id,)).fetchone()
        if not alvo:
            abort(404)
        if alvo["id"] == session.get("user_id"):
            flash("Para a sua própria senha use Minha conta → Senha e e-mail.", "erro")
            return redirect(url_for("staff.usuarios"))
        senha = gerar_senha_provisoria()
        db.execute("UPDATE users SET password_hash = ?, trocar_senha = 1, ativo = 1 WHERE id = ?",
                   (hash_password(senha), usuario_id))
        db.execute("DELETE FROM password_reset_codes WHERE user_id = ?", (usuario_id,))
    _log("staff", session.get("nome"), f"senha_provisoria:{alvo['username']}")
    flash(f"Nova senha provisória gerada para {alvo['nome']}. A senha anterior deixou de funcionar.", "ok")
    return _tela_usuarios(senha_gerada=senha, usuario_senha=alvo["username"])


@staff_bp.route("/configuracoes/usuarios/<int:usuario_id>/editar", methods=["POST"])
@roles_required("admin")
def editar_usuario(usuario_id):
    """Muda o perfil de acesso e o setor de um funcionário. O próprio perfil
    não muda por aqui, e o sistema nunca fica sem administrador ativo."""
    setor = request.form.get("setor", "").strip()[:100] or None
    papel = request.form.get("papel", "").strip()
    with get_db() as db:
        alvo = db.execute("SELECT id, username, nome, papel, setor, ativo FROM users WHERE id = ?",
                          (usuario_id,)).fetchone()
        if not alvo:
            abort(404)
        if alvo["id"] == session.get("user_id") or not papel:
            papel = alvo["papel"]
        if papel not in dict(PAPEIS_USUARIO) and papel != alvo["papel"]:
            flash("Perfil de acesso inválido.", "erro")
            return redirect(url_for("staff.usuarios"))
        adm = config.PAPEIS_ADMINISTRADORES
        if alvo["papel"] in adm and papel not in adm and alvo["ativo"]:
            outros = db.execute(
                "SELECT COUNT(*) AS n FROM users WHERE papel IN ('admin', 'direcao') AND ativo = 1 AND id <> ?",
                (usuario_id,),
            ).fetchone()["n"]
            if not outros:
                flash("Não dá para tirar o perfil de administrador do único administrador ativo.", "erro")
                return redirect(url_for("staff.usuarios"))
        if papel == alvo["papel"] and setor == alvo["setor"]:
            flash("Nada mudou.", "ok")
            return redirect(url_for("staff.usuarios"))
        db.execute("UPDATE users SET papel = ?, setor = ? WHERE id = ?", (papel, setor, usuario_id))
    rotulos = dict(PAPEIS_USUARIO)
    mudancas = []
    if papel != alvo["papel"]:
        antes = rotulos.get(alvo["papel"]) or ROTULOS_PAPEL_ANTIGO.get(alvo["papel"], alvo["papel"])
        mudancas.append(f"perfil {antes} → {rotulos[papel]}")
    if setor != alvo["setor"]:
        mudancas.append(f"setor {alvo['setor'] or '—'} → {setor or '—'}")
    _log("staff", session.get("nome"), f"editar_usuario:{alvo['username']}:{papel}:{setor or ''}")
    flash(f"{alvo['nome']}: " + "; ".join(mudancas) + ".", "ok")
    return redirect(url_for("staff.usuarios"))


@staff_bp.route("/configuracoes/usuarios/<int:usuario_id>/ativo", methods=["POST"])
@roles_required("admin")
def alternar_usuario_ativo(usuario_id):
    with get_db() as db:
        alvo = db.execute("SELECT id, username, nome, papel, ativo FROM users WHERE id = ?", (usuario_id,)).fetchone()
        if not alvo:
            abort(404)
        if alvo["id"] == session.get("user_id"):
            flash("Você não pode desativar o seu próprio usuário.", "erro")
            return redirect(url_for("staff.usuarios"))
        if alvo["ativo"] and alvo["papel"] in config.PAPEIS_ADMINISTRADORES:
            outros = db.execute(
                "SELECT COUNT(*) AS n FROM users WHERE papel IN ('admin', 'direcao') AND ativo = 1 AND id <> ?",
                (usuario_id,),
            ).fetchone()["n"]
            if not outros:
                flash("Não dá para desativar o único administrador ativo.", "erro")
                return redirect(url_for("staff.usuarios"))
        db.execute("UPDATE users SET ativo = ? WHERE id = ?", (0 if alvo["ativo"] else 1, usuario_id))
    _log("staff", session.get("nome"), f"{'desativar' if alvo['ativo'] else 'reativar'}_usuario:{alvo['username']}")
    flash(f"{alvo['nome']} {'desativado(a): não consegue mais entrar' if alvo['ativo'] else 'reativado(a)'}.", "ok")
    return redirect(url_for("staff.usuarios"))


# --------------------------------------------------------- aluno detail ----
def _agrupar_boletim(grades):
    """Notas agrupadas por ano e depois por bimestre, para as abas da
    ficha e o boletim em PDF (ano mais recente primeiro; dentro do ano,
    bimestre 1..4). "grades" já vem ordenado por ano, bimestre e
    disciplina."""
    por_ano = {}
    for g in grades:
        por_ano.setdefault(g["ano"], {}).setdefault(g["bimestre"], []).append(g)
    return {ano: por_ano[ano] for ano in sorted(por_ano, reverse=True)}


@staff_bp.route("/aluno/<int:student_id>")
@login_required
def aluno_detail(student_id):
    with get_db() as db:
        aluno = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if not aluno:
            abort(404)
        grades = db.execute(
            """SELECT * FROM grades WHERE student_id = ?
               ORDER BY ano, bimestre, disciplina""",
            (student_id,),
        ).fetchall()
        aee_detalhe = None
        if aluno["aee"] and session.get("papel") in config.PAPEIS_COM_ACESSO_AEE_DETALHE:
            aee_detalhe = db.execute(
                "SELECT * FROM aee_info WHERE student_id = ?", (student_id,)
            ).fetchone()
        # código fixo de acesso do responsável: só admin/secretaria veem
        # (e é criado na primeira vez que alguém deles abre a ficha)
        codigo_acesso = None
        if session.get("papel") in ("admin", "secretaria"):
            codigo_acesso = codigo_responsavel(db, student_id)
        recomendacoes = recomendacoes_por_bimestre(db, student_id)
        colegas = db.execute(
            """SELECT id, nome, nome_social, aee FROM students
               WHERE turma = ? AND situacao = 'ATIVO' ORDER BY nome""",
            (aluno["turma"],),
        ).fetchall()
        turmas = _turmas_ativas(db)

    boletim = _agrupar_boletim(grades)

    return render_template(
        "aluno.html",
        aluno=aluno,
        boletim=boletim,
        aee_detalhe=aee_detalhe,
        codigo_acesso=codigo_acesso,
        recomendacoes_bimestre=recomendacoes,
        pode_editar_recomendacao=session.get("papel") in PAPEIS_RECOMENDACAO,
        colegas=colegas, turmas=turmas, **_vizinhos(colegas, student_id),
        user=current_user(),
    )


def _turmas_ativas(db):
    return [r["turma"] for r in db.execute(
        """SELECT DISTINCT turma FROM students WHERE situacao = 'ATIVO' AND turma IS NOT NULL
           AND turma <> '' AND turma <> 'TEG-PROV' ORDER BY turma""").fetchall()]


@staff_bp.route("/turma/ir")
@login_required
def ir_para_turma():
    """Troca de turma pela ficha do aluno: abre a ficha do 1º aluno da
    chamada da turma escolhida (a lista lateral passa a ser a dela)."""
    turma = request.args.get("turma", "").strip()
    with get_db() as db:
        primeiro = db.execute(
            "SELECT id FROM students WHERE turma = ? AND situacao = 'ATIVO' ORDER BY nome LIMIT 1",
            (turma,)).fetchone()
    if not primeiro:
        flash("Turma não encontrada ou sem alunos ativos.", "erro")
        return redirect(request.referrer or url_for("staff.dashboard"))
    return redirect(url_for("staff.aluno_detail", student_id=primeiro["id"]))


def _vizinhos(colegas, student_id):
    """Aluno anterior e próximo na lista da turma (ordem alfabética, a mesma
    do número de chamada) — para a coluna lateral da ficha."""
    ids = [c["id"] for c in colegas]
    if student_id not in ids:
        return {"colega_anterior": None, "colega_proximo": None}
    i = ids.index(student_id)
    return {"colega_anterior": colegas[i - 1] if i > 0 else None,
            "colega_proximo": colegas[i + 1] if i + 1 < len(colegas) else None}



@staff_bp.route("/aluno/<int:student_id>/boletim.pdf")
@login_required
def boletim_pdf(student_id):
    """Boletim no formato do SGP (o mesmo dos boletins da turma): uma
    folha por ano letivo com nota, com os 4 bimestres e a Final."""
    from scripts.gerar_boletim_detalhado import gerar_pdf_aluno_bytes, numero_na_turma

    with get_db() as db:
        aluno = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if not aluno:
            abort(404)
        grades = db.execute(
            "SELECT * FROM grades WHERE student_id = ? ORDER BY ano, bimestre, disciplina", (student_id,)
        ).fetchall()
        recomendacoes = recomendacoes_por_bimestre(db, student_id)
        numero = numero_na_turma(db, aluno)
    conteudo = gerar_pdf_aluno_bytes(aluno, grades, recomendacoes, numero)
    _log("staff", session.get("nome"), f"boletim_pdf:{student_id}")
    nome = (aluno["nome"] or f"aluno {student_id}").replace("/", "-")
    return send_file(BytesIO(conteudo), mimetype="application/pdf", as_attachment=False,
                     download_name=f"Boletim - {nome}.pdf")

@staff_bp.route("/aluno/<int:student_id>/foto", methods=["POST"])
@login_required
def upload_foto(student_id):
    file = request.files.get("foto")
    if not file or file.filename == "":
        flash("Selecione um arquivo de imagem.", "erro")
        return redirect(url_for("staff.aluno_detail", student_id=student_id))

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_PHOTO_EXT:
        flash("Formato inválido. Use JPG, PNG ou WEBP.", "erro")
        return redirect(url_for("staff.aluno_detail", student_id=student_id))

    filename = secure_filename(f"aluno_{student_id}.{ext}")
    arquivos.salvar(arquivos.FOTOS, filename, file.read())
    arquivos.apagar_por_prefixo(arquivos.FOTOS, f"aluno_{student_id}.", exceto=filename)

    with get_db() as db:
        db.execute(
            "UPDATE students SET foto_path = ?, updated_at = ? WHERE id = ?",
            (filename, agora(), student_id),
        )
    _log("staff", session.get("nome"), f"upload_foto:{student_id}")
    flash("Foto atualizada.", "ok")
    return redirect(url_for("staff.aluno_detail", student_id=student_id))


_FOTO_ALUNO_RE = re.compile(r"^aluno_(\d+)\.")


@staff_bp.route("/fotos/<path:filename>")
def foto(filename):
    """Serve as fotos de alunos fora da pasta static/ (para funcionar com
    disco persistente em hospedagem na nuvem) e só libera para quem tem
    motivo: a equipe logada, ou o responsável logado pelo token — e, nesse
    caso, só a foto do próprio aluno dele."""
    m = _FOTO_ALUNO_RE.match(filename)
    student_id = int(m.group(1)) if m else None

    autorizado = bool(session.get("user_id"))
    if not autorizado and student_id and session.get("guardian_student_id") == student_id:
        autorizado = True
    if not autorizado:
        abort(403)

    conteudo = arquivos.ler(arquivos.FOTOS, filename)
    if conteudo is None:
        abort(404)
    tipo = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    resp = send_file(BytesIO(conteudo), mimetype=tipo)
    resp.headers["Cache-Control"] = "private, max-age=300"
    return resp


# ---------------------------------------------------- token responsavel ----
@staff_bp.route("/responsaveis/trocar-todos-os-codigos", methods=["POST"])
@roles_required("admin")
def trocar_todos_codigos():
    """Troca o código de acesso de todos os alunos de uma vez (ex: início
    do ano letivo). Todos os códigos e tokens anteriores deixam de valer."""
    if request.form.get("confirmacao", "").strip().upper() != "TROCAR TODOS":
        flash('Para trocar o código de todos, digite TROCAR TODOS no campo de confirmação.', "erro")
        return redirect(request.referrer or url_for("staff.dashboard"))
    with get_db() as db:
        n = trocar_todos_codigos_responsavel(db)
    _log("staff", session.get("nome"), f"trocar_todos_codigos_responsavel:{n}")
    flash(f"Código de acesso trocado para todos os {n} alunos. Os códigos e tokens anteriores não funcionam mais.", "ok")
    return redirect(request.referrer or url_for("staff.dashboard"))


@staff_bp.route("/aluno/<int:student_id>/gerar-token", methods=["POST"])
@roles_required("admin", "secretaria")
def gerar_token(student_id):
    """Troca o código de acesso do responsável (ex: foi passado pra pessoa
    errada). O código anterior deixa de funcionar na hora."""
    with get_db() as db:
        if not db.execute("SELECT 1 FROM students WHERE id = ?", (student_id,)).fetchone():
            abort(404)
        codigo_responsavel(db, student_id, trocar=True)
    _log("staff", session.get("nome"), f"trocar_codigo_responsavel:{student_id}")
    flash("Novo código de acesso gerado — o anterior não funciona mais. Entregue o novo ao responsável.", "ok")
    return redirect(url_for("staff.aluno_detail", student_id=student_id))


PAPEIS_RECOMENDACAO = ("admin", "secretaria", "professor")  # coordenação usa admin ou professor


@staff_bp.route("/aluno/<int:student_id>/recomendacao", methods=["POST"])
@roles_required(*PAPEIS_RECOMENDACAO)
def salvar_recomendacao(student_id):
    """Recomendação do conselho de classe de um bimestre (ano+bimestre no
    formulário) ou, sem bimestre, a recomendação geral do aluno — editadas
    direto na aba Boletim & Frequência. A tela envia via fetch e recebe
    JSON; sem JavaScript, volta pra ficha com mensagem."""
    texto = request.form.get("texto", "").strip()
    ano = request.form.get("ano", type=int)
    bimestre = request.form.get("bimestre", type=int)
    via_fetch = request.headers.get("X-Requested-With") == "fetch"
    with get_db() as db:
        if not db.execute("SELECT 1 FROM students WHERE id = ?", (student_id,)).fetchone():
            abort(404)
        if ano and bimestre in (1, 2, 3, 4):
            salvar_recomendacao_bimestre(db, student_id, ano, bimestre, texto, session.get("nome"))
            onde = f"{bimestre}º bimestre de {ano}"
        else:
            db.execute("UPDATE students SET recomendacoes=?, updated_at=? WHERE id=?",
                       (texto or None, agora(), student_id))
            onde = "geral"
    _log("staff", session.get("nome"), f"recomendacao:{student_id}:{onde}")
    mensagem = f"Recomendação ({onde}) {'salva' if texto else 'removida'}."
    if via_fetch:
        return {"ok": True, "mensagem": mensagem, "autor": session.get("nome")}
    flash(mensagem, "ok")
    return redirect(url_for("staff.aluno_detail", student_id=student_id))


@staff_bp.route("/aluno/<int:student_id>/area-do-aluno", methods=["GET", "POST"])
@roles_required("admin", "secretaria", "professor")
def editar_area_do_aluno(student_id):
    """Pendências cadastrais (ex: telefone desatualizado, documento
    faltando) — aparecem em destaque para o responsável na Área do aluno.
    As recomendações ficam na aba Boletim & Frequência (por bimestre, como
    no conselho de classe). Nada aqui é dado de saúde/diagnóstico."""
    with get_db() as db:
        aluno = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if not aluno:
            abort(404)

        if request.method == "POST":
            db.execute(
                "UPDATE students SET alteracoes_pendentes=?, updated_at=? WHERE id=?",
                (request.form.get("alteracoes_pendentes", "").strip() or None, agora(), student_id),
            )
            atualizado = True
        else:
            atualizado = False

    if atualizado:
        _log("staff", session.get("nome"), f"editar_area_do_aluno:{student_id}")
        flash("Pendências cadastrais atualizadas.", "ok")
        return redirect(url_for("staff.aluno_detail", student_id=student_id))

    return render_template("editar_area_do_aluno.html", aluno=aluno, user=current_user())


# ------------------------------------------------------------ transferência --
@staff_bp.route("/aluno/<int:student_id>/nome", methods=["GET", "POST"])
@roles_required("admin", "secretaria")
def editar_nome(student_id):
    """Corrige o nome de registro (acento, erro de digitação vindo da
    importação etc.) e/ou registra o nome social do aluno — usado no
    dia a dia do sistema (listagens, busca, área do aluno), mas nunca
    substitui o nome de registro civil nos documentos oficiais
    (histórico escolar, planilha da SPTrans), que precisam bater com a
    identidade legal do aluno."""
    with get_db() as db:
        aluno = db.execute("SELECT id, nome, nome_social, turma FROM students WHERE id = ?", (student_id,)).fetchone()
        if not aluno:
            abort(404)

        if request.method == "POST":
            nome = request.form.get("nome", "").strip()
            if not nome:
                flash("O nome de registro não pode ficar em branco.", "erro")
                return redirect(url_for("staff.editar_nome", student_id=student_id))
            db.execute(
                "UPDATE students SET nome=?, nome_social=?, updated_at=? WHERE id=?",
                (nome, request.form.get("nome_social", "").strip() or None, agora(), student_id),
            )
            propagar_dados_aluno(db, student_id, antes=aluno)
            atualizado = True
        else:
            atualizado = False

    if atualizado:
        _log("staff", session.get("nome"), f"editar_nome:{student_id}")
        flash("Nome atualizado.", "ok")
        return redirect(url_for("staff.aluno_detail", student_id=student_id))

    return render_template("editar_nome.html", aluno=aluno, user=current_user())


@staff_bp.route("/aluno/<int:student_id>/turma", methods=["GET", "POST"])
@roles_required("admin", "secretaria")
def editar_turma(student_id):
    """Corrige a turma (e opcionalmente a série) do aluno — usada
    sobretudo pra corrigir a turma provisória 'TEG-PROV' que fica em
    quem é criado automaticamente na importação do TEG (essa planilha
    não traz a turma específica, só a série). Assim que a turma vira
    uma turma de verdade, o aluno passa a contar no turno certo
    (a turma provisória some sozinha do painel principal quando
    ninguém mais estiver nela)."""
    with get_db() as db:
        aluno = db.execute("SELECT id, nome, nome_social, turma, serie FROM students WHERE id = ?", (student_id,)).fetchone()
        if not aluno:
            abort(404)

        if request.method == "POST":
            turma = request.form.get("turma", "").strip().upper()
            if not turma:
                flash("A turma não pode ficar em branco.", "erro")
                return redirect(url_for("staff.editar_turma", student_id=student_id))
            db.execute(
                "UPDATE students SET turma=?, serie=?, updated_at=? WHERE id=?",
                (turma, request.form.get("serie", "").strip() or aluno["serie"], agora(), student_id),
            )
            propagar_dados_aluno(db, student_id, antes=aluno)
            proxima = request.form.get("next", "").strip()
            atualizado = True
        else:
            atualizado = False
            proxima = request.args.get("next", "").strip()

    if atualizado:
        _log("staff", session.get("nome"), f"editar_turma:{student_id}")
        flash(f"Turma de {aluno['nome_social'] or aluno['nome']} atualizada.", "ok")
        if proxima == "turma_atual":
            return redirect(url_for("staff.turma_view", turma=aluno["turma"]))
        return redirect(url_for("staff.aluno_detail", student_id=student_id))

    return render_template("editar_turma.html", aluno=aluno, proxima=proxima, user=current_user())


CAMPOS_NOVO_ALUNO = ("nome", "nome_social", "codigo_interno", "ra_prodesp", "data_nascimento", "turma", "serie",
                     "filiacao1", "telefone_filiacao1", "telefone_filiacao2")


@staff_bp.route("/aluno/novo", methods=["GET", "POST"])
@roles_required("admin", "secretaria")
def novo_aluno():
    """Cadastro manual de um aluno (ex: matrícula nova que ainda não veio na
    planilha do SGP). Quando a planilha for importada depois, o aluno é
    reconhecido pelo código EOL e só tem os dados atualizados."""
    with get_db() as db:
        turmas = [r["turma"] for r in db.execute(
            """SELECT DISTINCT turma FROM students WHERE situacao = 'ATIVO' AND turma IS NOT NULL
               AND turma <> '' AND turma <> 'TEG-PROV' ORDER BY turma""").fetchall()]
    form = {k: request.form.get(k, "").strip() for k in CAMPOS_NOVO_ALUNO}
    form["aee"] = request.form.get("aee") == "1"
    if request.method == "GET":
        form["turma"] = request.args.get("turma", "").strip().upper()
        return render_template("novo_aluno.html", form=form, turmas=turmas, series=config.SERIES_EF,
                               duplicado=None, user=current_user())

    form["nome"] = " ".join(form["nome"].upper().split())
    form["nome_social"] = " ".join(form["nome_social"].upper().split())
    form["filiacao1"] = " ".join(form["filiacao1"].upper().split())
    form["turma"] = form["turma"].upper().replace(" ", "")
    form["codigo_interno"] = re.sub(r"\s+", "", form["codigo_interno"])
    erro, duplicado = None, None
    if not form["nome"]:
        erro = "Informe o nome do aluno."
    elif not form["turma"]:
        erro = "Informe a turma (ex: 4A)."
    elif form["data_nascimento"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", form["data_nascimento"]):
        erro = "Data de nascimento inválida."
    with get_db() as db:
        if not erro and form["codigo_interno"]:
            existe = db.execute("SELECT id, nome FROM students WHERE codigo_interno = ?",
                                (form["codigo_interno"],)).fetchone()
            if existe:
                erro = f"Já existe um aluno com o código EOL {form['codigo_interno']}: {existe['nome']}."
                duplicado = existe
        if not erro and request.form.get("confirmar_homonimo") != "1":
            sql = "SELECT id, nome, turma, situacao, data_nascimento FROM students WHERE nome = ?"
            params = [form["nome"]]
            if form["data_nascimento"]:
                sql += " AND (data_nascimento = ? OR data_nascimento IS NULL OR data_nascimento = '')"
                params.append(form["data_nascimento"])
            parecido = db.execute(sql, params).fetchone()
            if parecido:
                erro = (f"Já existe um aluno com esse nome ({parecido['nome']}, turma {parecido['turma']}, "
                        f"{(parecido['situacao'] or '').lower()}). Confira se não é o mesmo aluno; se for outro, "
                        "marque a confirmação e salve de novo.")
                duplicado = parecido
        if erro:
            flash(erro, "erro")
            return render_template("novo_aluno.html", form=form, turmas=turmas, series=config.SERIES_EF,
                                   duplicado=duplicado, user=current_user())
        student_id = db.execute(
            """INSERT INTO students (codigo_interno, ra_prodesp, nome, nome_social, filiacao1, data_nascimento,
                                     turma, serie, situacao, aee)
               VALUES (?,?,?,?,?,?,?,?, 'ATIVO', ?)""",
            (form["codigo_interno"] or None, form["ra_prodesp"] or None, form["nome"], form["nome_social"] or None,
             form["filiacao1"] or None, form["data_nascimento"] or None, form["turma"], form["serie"] or None,
             1 if form["aee"] else 0),
        ).lastrowid
        if form["telefone_filiacao1"] or form["telefone_filiacao2"]:
            salvar_contato_responsavel(db, student_id, telefone_filiacao1=form["telefone_filiacao1"] or None,
                                       telefone_filiacao2=form["telefone_filiacao2"] or None,
                                       responsavel_legal=None, telefone_recados=None)
    _log("staff", session.get("nome"), f"novo_aluno:{student_id}:{form['turma']}")
    flash(f"Aluno {form['nome']} cadastrado na turma {form['turma']}.", "ok")
    return redirect(url_for("staff.aluno_detail", student_id=student_id))


@staff_bp.route("/aluno/<int:student_id>/transferir", methods=["GET", "POST"])
@roles_required("admin", "secretaria")
def transferir_aluno(student_id):
    """Marca o aluno como transferido pra outra escola durante o ano
    letivo. Ele deixa de contar como 'ativo' (some das turmas, contagens
    do painel, exportação da SPTrans etc.) mas o cadastro continua
    intacto — dá pra reverter em 'Reativar matrícula' se for engano."""
    with get_db() as db:
        aluno = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if not aluno:
            abort(404)

        if request.method == "POST":
            data_transferencia = request.form.get("data_transferencia", "").strip()
            if not data_transferencia:
                flash("Informe a data da transferência.", "erro")
                return redirect(url_for("staff.transferir_aluno", student_id=student_id))
            db.execute(
                "UPDATE students SET situacao='TRANSFERIDO', data_transferencia=?, updated_at=? WHERE id=?",
                (data_transferencia, agora(), student_id),
            )
            entrou_no_arquivo_morto = adicionar_ao_arquivo_morto(
                db, student_id, aluno["nome"], aluno["data_nascimento"]
            )
            atualizado = True
        else:
            atualizado = False

    if atualizado:
        _log("staff", session.get("nome"), f"transferir_aluno:{student_id}")
        flash(f"{aluno['nome']} foi marcado(a) como transferido(a).", "ok")
        if not entrou_no_arquivo_morto:
            flash(
                f"{aluno['nome']} já constava no Arquivo Morto — nenhum registro duplicado foi criado.",
                "erro",
            )
        return redirect(url_for("staff.aluno_detail", student_id=student_id))

    return render_template("transferir_aluno.html", aluno=aluno, user=current_user())


@staff_bp.route("/aluno/<int:student_id>/reativar", methods=["POST"])
@roles_required("admin", "secretaria")
def reativar_aluno(student_id):
    with get_db() as db:
        aluno = db.execute("SELECT id, nome FROM students WHERE id = ?", (student_id,)).fetchone()
        if not aluno:
            abort(404)
        db.execute(
            "UPDATE students SET situacao='ATIVO', data_transferencia=NULL, updated_at=? WHERE id=?",
            (agora(), student_id),
        )
    _log("staff", session.get("nome"), f"reativar_aluno:{student_id}")
    flash(f"{aluno['nome']} voltou a ser considerado(a) ativo(a).", "ok")
    return redirect(url_for("staff.aluno_detail", student_id=student_id))


# ------------------------------------------------------------ notas manuais --
# componentes da Ata Bimestral (mesma ordem do relatório do SGP) — usados
# quando a turma ainda não tem nenhuma nota importada para servir de modelo
DISCIPLINAS_PADRAO = ["Arte", "Ciências", "Ed. Física", "Geografia", "História", "Inglês",
                      "Língua Portuguesa", "Matemática", "Laboratório de Educação Digital", "Sala de leitura"]
CONCEITOS = ("P", "S", "NS")


def _disciplinas_da_turma(db, turma, ano, bimestre, student_id):
    """Componentes que a turma usa (das notas dos colegas no bimestre, depois
    no ano), mais os que o aluno já tem; sem nada lançado, a lista padrão."""
    def da_turma(sql_extra, params):
        return [r["disciplina"] for r in db.execute(
            f"""SELECT DISTINCT g.disciplina FROM grades g JOIN students s ON s.id = g.student_id
                WHERE s.turma = ? AND g.ano = ? {sql_extra} ORDER BY g.disciplina""",
            (turma, ano, *params)).fetchall()]
    lista = da_turma("AND g.bimestre = ?", (bimestre,)) or da_turma("", ()) or list(DISCIPLINAS_PADRAO)
    for r in db.execute("SELECT DISTINCT disciplina FROM grades WHERE student_id = ? AND ano = ? AND bimestre = ?",
                        (student_id, ano, bimestre)).fetchall():
        if r["disciplina"] not in lista:
            lista.append(r["disciplina"])
    return lista


def _inteiro(texto):
    texto = (texto or "").strip()
    return int(texto) if texto.isdigit() else None


def _percentual(texto):
    texto = (texto or "").strip().replace(",", ".").rstrip("%")
    try:
        v = float(texto)
    except ValueError:
        return None
    return v if 0 <= v <= 100 else None


@staff_bp.route("/aluno/<int:student_id>/notas", methods=["GET", "POST"])
@roles_required("admin", "secretaria")
def lancar_notas(student_id):
    """Lançamento manual das notas/faltas de um bimestre — para quando o
    aluno não veio na Ata Bimestral importada (ou para corrigir algo)."""
    ano = request.values.get("ano", type=int) or config.ANO_LETIVO
    bimestre = request.values.get("bimestre", type=int) or 1
    if bimestre not in (1, 2, 3, 4) or not 2000 <= ano <= 2100:
        abort(400)
    with get_db() as db:
        aluno = db.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if not aluno:
            abort(404)
        existentes = {g["disciplina"]: g for g in db.execute(
            "SELECT * FROM grades WHERE student_id = ? AND ano = ? AND bimestre = ?",
            (student_id, ano, bimestre)).fetchall()}
        disciplinas = _disciplinas_da_turma(db, aluno["turma"], ano, bimestre, student_id)

        if request.method == "POST":
            nova = " ".join(request.form.get("nova_disciplina", "").split())[:80]
            if nova and nova not in disciplinas:
                disciplinas.append(nova)
            gravadas, apagadas = 0, 0
            for i, disciplina in enumerate(disciplinas):
                chave = "nova" if disciplina == nova and nova not in existentes else str(i)
                faltas = _inteiro(request.form.get(f"faltas::{chave}"))
                comp = _inteiro(request.form.get(f"comp::{chave}"))
                freq = _percentual(request.form.get(f"freq::{chave}"))
                conceito = request.form.get(f"conc::{chave}", "").strip().upper()
                conceito = conceito if conceito in CONCEITOS else None
                if faltas is None and comp is None and freq is None and conceito is None:
                    if disciplina in existentes:
                        db.execute("DELETE FROM grades WHERE id = ?", (existentes[disciplina]["id"],))
                        apagadas += 1
                    continue
                anterior = existentes.get(disciplina)
                salvar_nota(db, student_id, ano, bimestre, disciplina, faltas, comp, freq, conceito,
                            anterior["situacao_conselho"] if anterior else None, "manual")
                gravadas += 1

    if request.method == "POST":
        _log("staff", session.get("nome"), f"lancar_notas:{student_id}:{ano}:{bimestre}")
        flash(f"Notas do {bimestre}º bimestre de {ano} salvas ({gravadas} componente(s)"
              + (f", {apagadas} apagado(s)" if apagadas else "") + ").", "ok")
        return redirect(url_for("staff.aluno_detail", student_id=student_id))
    return render_template("lancar_notas.html", aluno=aluno, ano=ano, bimestre=bimestre,
                           disciplinas=disciplinas, existentes=existentes, conceitos=CONCEITOS,
                           user=current_user())
