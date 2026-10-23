import os

from flask import Flask, request, redirect, flash, url_for, session
from werkzeug.exceptions import RequestEntityTooLarge

import config
import datas
from models import init_db
from csrf import init_csrf
from routes.staff import staff_bp
from routes.guardian import guardian_bp
from routes.importacao import importacao_bp
from routes.api import api_bp
from routes.arquivo_morto import arquivo_morto_bp


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.SECRET_KEY
    # limite geral = o maior entre foto e PDF de ata (a rota de foto ainda
    # valida a extensão/tamanho esperado para imagem separadamente)
    app.config["MAX_CONTENT_LENGTH"] = max(config.MAX_UPLOAD_MB, config.MAX_PDF_UPLOAD_MB) * 1024 * 1024
    # A tela de conferência de notas pode ter dezenas de milhares de campos
    # em importações grandes (ex: 900 alunos x ~40 campos cada). O Werkzeug
    # 3.1+ passou a limitar sozinho o tamanho total de formulários comuns a
    # 500 KB (max_form_memory_size) e a 1000 campos (max_form_parts) — um
    # limite NOVO, separado do MAX_CONTENT_LENGTH acima, e que por padrão
    # bloqueia esse formulário bem antes do nosso próprio limite. Confiamos
    # só no MAX_CONTENT_LENGTH (que já cobre o tamanho total em bytes) e
    # desligamos esses dois limites extras do Werkzeug.
    app.config["MAX_FORM_MEMORY_SIZE"] = None
    app.config["MAX_FORM_PARTS"] = None

    # Cookie de sessão: HttpOnly sempre (padrão do Flask), SameSite=Lax
    # sempre, e Secure (só trafega em HTTPS) quando ESCOLA_FORCE_HTTPS=1 —
    # ligue isso ao hospedar na internet (veja INICIO_RAPIDO.md).
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = config.FORCE_HTTPS
    app.config["PREFERRED_URL_SCHEME"] = "https" if config.FORCE_HTTPS else "http"

    config.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    config.RELATORIO_FOTOS_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    init_csrf(app)
    app.add_template_filter(datas.data_br, "data_br")
    app.add_template_filter(datas.data_hora_br, "data_hora_br")

    app.register_blueprint(staff_bp)
    app.register_blueprint(guardian_bp)
    app.register_blueprint(importacao_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(arquivo_morto_bp)

    @app.before_request
    def sincronizar_usuario():
        # perfil (papel) e nome vêm do banco a cada acesso: uma mudança feita
        # pelo administrador vale na hora, e quem foi desativado sai do sistema
        if not session.get("user_id") or request.endpoint in ("static", "staff.logout"):
            return None
        from models import get_db
        with get_db() as db:
            u = db.execute("SELECT papel, nome, ativo FROM users WHERE id = ?", (session["user_id"],)).fetchone()
        if not u or not u["ativo"]:
            session.clear()
            flash("Seu acesso foi desativado. Fale com o administrador do sistema.", "erro")
            return redirect(url_for("staff.login"))
        from auth import papel_efetivo
        session["papel"], session["papel_cadastro"], session["nome"] = papel_efetivo(u["papel"]), u["papel"], u["nome"]
        return None

    @app.before_request
    def exigir_troca_de_senha():
        # quem entrou com senha provisória só usa o sistema depois de criar a própria
        if session.get("trocar_senha") and request.endpoint not in (
            "staff.alterar_senha", "staff.alterar_email", "staff.logout", "static", "staff.foto",
        ):
            return redirect(url_for("staff.alterar_senha"))

    @app.context_processor
    def inject_globals():
        dados = {"ano_letivo": config.ANO_LETIVO}
        if session.get("user_id"):
            from models import get_db
            from menu_lateral import menu_do_usuario
            with get_db() as db:
                linha = db.execute("SELECT papel FROM users WHERE id = ?", (session["user_id"],)).fetchone()
                from auth import papel_efetivo
                dados["menu"] = menu_do_usuario(db, papel_efetivo(linha["papel"]) if linha else None)
        return dados

    @app.after_request
    def sem_cache_do_navegador(response):
        # Sem isso, o botão "voltar" do navegador pode mostrar uma cópia
        # da página guardada em cache LOCAL depois de sair do sistema —
        # a sessão já foi encerrada no servidor, mas a tela aparece como
        # se ainda estivesse logado até a pessoa interagir com ela (o que
        # dispara uma requisição de verdade e manda pro login). Essas
        # três variações cobrem navegadores diferentes.
        # Fica de fora só o /static/ (CSS, JS, imagens) — não tem dado de
        # ninguém, então cachear normalmente é seguro e evita rebaixar
        # tudo de novo a cada navegação.
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.errorhandler(RequestEntityTooLarge)
    def arquivo_grande_demais(e):
        limite = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        tamanho_enviado = request.content_length
        tamanho_txt = (
            f"{tamanho_enviado / (1024*1024):.1f} MB" if tamanho_enviado else "desconhecido (navegador não informou)"
        )
        app.logger.warning(
            f"[413] {request.method} {request.path} — tamanho enviado: {tamanho_txt} "
            f"(limite atual: {limite} MB) — usuário: {session.get('nome') or session.get('guardian_student_id') or 'anônimo'}"
        )
        flash(
            f"Arquivo grande demais para o limite atual ({limite} MB). "
            f"Se o arquivo é legítimo, aumente MAX_PDF_UPLOAD_MB (ou MAX_UPLOAD_MB "
            f"para fotos) no arquivo .env e reinicie o servidor.",
            "erro",
        )
        destino = request.referrer or url_for("staff.dashboard")
        return redirect(destino)

    return app


app = create_app()

if __name__ == "__main__":
    # debug=True (padrão local) NUNCA deve rodar num servidor exposto à
    # internet. Em produção use gunicorn (ver INICIO_RAPIDO.md),
    # que nem passa por este bloco.
    debug = os.environ.get("ESCOLA_DEBUG", "1") == "1"
    app.run(debug=debug, host="127.0.0.1", port=5000)
