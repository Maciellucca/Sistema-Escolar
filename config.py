import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _carregar_dotenv(caminho):
    """Loader simples de .env (evita depender do pacote python-dotenv)."""
    if not caminho.exists():
        return
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip())


_carregar_dotenv(BASE_DIR / ".env")

# Nunca comite o arquivo .env nem a pasta data/ com dados reais - veja README.md
SECRET_KEY = os.environ.get("SECRET_KEY", "troque-esta-chave-em-producao")

# Chave exigida para criar um novo usuário ADMINISTRADOR pela tela de login
# (/login/criar-admin). Só quem tem acesso ao servidor (arquivo .env) consegue
# criar um admin — não existe cadastro público. Por padrão usa a própria
# SECRET_KEY para não exigir configuração extra, mas o recomendado em
# produção é definir ADMIN_SETUP_KEY com um valor PRÓPRIO e diferente da
# SECRET_KEY (que também assina a sessão de login) — assim é possível trocar
# uma sem invalidar a outra.
ADMIN_SETUP_KEY = os.environ.get("ADMIN_SETUP_KEY", SECRET_KEY)


# Em hospedagem na nuvem, o disco do próprio código costuma ser APAGADO a
# cada novo deploy/reinício — então o banco de dados e as fotos NÃO podem
# morar dentro da pasta do projeto nesse cenário. Configure ESCOLA_DATA_DIR
# apontando para um disco persistente (ex: Render Persistent Disk, volume do
# Railway/Fly.io) e tudo abaixo passa a morar lá automaticamente. Sem essa
# variável, continua tudo dentro do projeto — ótimo para uso local.
DATA_DIR = Path(os.environ.get("ESCOLA_DATA_DIR", str(BASE_DIR / "instance")))

# ------------------------------------------------------------- banco de dados
# DB_BACKEND = "sqlite" (padrão — zero configuração, ótimo para rodar local
# e para os testes automatizados) ou "mysql" (para o banco relacional do
# projeto integrador). Trocar de banco NÃO exige mudar nenhuma rota nem
# script — toda a diferença de sintaxe fica isolada em models.py.
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").strip().lower()

DB_PATH = os.environ.get("ESCOLA_DB_PATH", str(DATA_DIR / "sistema_escolar.db"))

MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE", "sistema_escolar")
# SSL (obrigatório nos MySQL na nuvem, como Aiven e TiDB Cloud):
#   MYSQL_SSL = "" (sem SSL) | "required" (conexão criptografada) |
#               "verify" (criptografada + confere o certificado)
#   MYSQL_SSL_CA = caminho do certificado da autoridade (ca.pem) OU o próprio
#                  conteúdo do arquivo colado na variável (-----BEGIN ...)
MYSQL_SSL = os.environ.get("MYSQL_SSL", "").strip().lower()
MYSQL_SSL_CA = os.environ.get("MYSQL_SSL_CA", "").strip()

# Atalho: tudo numa URL só, como os provedores mostram no painel, ex:
#   MYSQL_URL=mysql://usuario:senha@host:porta/banco?ssl-mode=REQUIRED
# Com MYSQL_URL (ou DATABASE_URL começando com mysql://) definida, o
# DB_BACKEND vira "mysql" automaticamente.
_URL_MYSQL = os.environ.get("MYSQL_URL", "").strip() or (
    os.environ.get("DATABASE_URL", "").strip() if os.environ.get("DATABASE_URL", "").strip().lower().startswith("mysql") else ""
)
if _URL_MYSQL:
    from urllib.parse import parse_qs, unquote, urlparse

    _u = urlparse(_URL_MYSQL)
    _q = {k.lower().replace("_", "-"): v[-1] for k, v in parse_qs(_u.query).items()}
    DB_BACKEND = "mysql"
    MYSQL_HOST = _u.hostname or MYSQL_HOST
    MYSQL_PORT = _u.port or MYSQL_PORT
    MYSQL_USER = unquote(_u.username or "") or MYSQL_USER
    MYSQL_PASSWORD = unquote(_u.password or "") if _u.password is not None else MYSQL_PASSWORD
    MYSQL_DATABASE = (_u.path or "").lstrip("/") or MYSQL_DATABASE
    _modo = _q.get("ssl-mode", "").lower().replace("_", "-")
    if not MYSQL_SSL and _modo:
        MYSQL_SSL = {"disabled": "", "preferred": "required", "required": "required",
                     "verify-ca": "verify", "verify-identity": "verify"}.get(_modo, "required")
    MYSQL_SSL_CA = MYSQL_SSL_CA or _q.get("ssl-ca", "")

DATA_RAW_DIR = BASE_DIR / "data" / "raw"
TEMPLATES_DIR = BASE_DIR / "data" / "templates"
PHOTOS_DIR = DATA_DIR / "photos"
EXPORTS_DIR = DATA_DIR / "exports"
UPLOADS_DIR = DATA_DIR / "uploads"
RELATORIO_FOTOS_DIR = DATA_DIR / "relatorios_fotos"  # fotos anexadas aos Relatórios Escolares (agenda)

ANO_LETIVO = int(os.environ.get("ESCOLA_ANO_LETIVO", "2026"))

# Papeis que podem ver o detalhe (laudo/observacoes) do cadastro AEE.
# Todos os papeis de staff veem o badge "AEE" no card do aluno; apenas estes
# veem o detalhe do laudo/diagnostico.
PAPEIS_COM_ACESSO_AEE_DETALHE = {"admin", "aee"}

# Perfis de login. "direcao" tem acesso completo: para as permissões do
# sistema vale como "admin" (auth.papel_efetivo). "pot" é o perfil da equipe de apoio à família.
PAPEL_EFETIVO = {"direcao": "admin"}
PAPEIS_ADMINISTRADORES = ("admin", "direcao")

# Envio de e-mail (código de "Esqueci minha senha"). Sem SMTP_HOST
# configurado, a recuperação por e-mail fica desativada e a tela avisa
# pra procurar o administrador. Gmail: smtp.gmail.com, porta 587, com uma
# "senha de app" (não a senha normal da conta).
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM", "").strip() or SMTP_USER
SMTP_SSL = os.environ.get("SMTP_SSL", "1" if SMTP_PORT == 465 else "0") == "1"  # porta 465 = SSL direto; 587 = STARTTLS
RESET_SENHA_MINUTOS = int(os.environ.get("RESET_SENHA_MINUTOS", "15"))  # validade do código

MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "5"))            # fotos de alunos
MAX_PDF_UPLOAD_MB = int(os.environ.get("MAX_PDF_UPLOAD_MB", "150"))   # Atas Bimestrais em PDF (podem ter 150+ páginas e pesar bem mais que os arquivos de teste)

# Ligue isso (ESCOLA_FORCE_HTTPS=1) quando o sistema estiver atrás de HTTPS
# de verdade (qualquer hospedagem séria na internet). Isso faz o cookie de
# sessão só trafegar criptografado. Em desenvolvimento local (http://
# 127.0.0.1) deixe desligado, senão o login não funciona.
FORCE_HTTPS = os.environ.get("ESCOLA_FORCE_HTTPS", "0") == "1"

# Series/turmas disponiveis para importacao (usado no formulario de upload).
# Ajuste se a nomenclatura de turmas da sua rede for diferente.
SERIES_EF = [
    "1º Ano", "2º Ano", "3º Ano", "4º Ano", "5º Ano",
    "6º Ano", "7º Ano", "8º Ano", "9º Ano",
]

# Dados de contato da escola mostrados na área do responsável. Os valores
# abaixo são fictícios: a escola define os reais pelas variáveis de ambiente.
ESCOLA_NOME = os.environ.get("ESCOLA_NOME", "EMEF Escola Modelo (fictícia)")
ESCOLA_ENDERECO = os.environ.get("ESCOLA_ENDERECO", "Endereço fictício, 100 – São Paulo/SP")
ESCOLA_TELEFONE = os.environ.get("ESCOLA_TELEFONE", "(11) 0000-0000")

# frequência mínima exigida (LDB: 75%) — abaixo disso a tela destaca em vermelho
FREQUENCIA_MINIMA = 75

# Menu lateral: categorias e itens de cada uma. A ORDEM aqui é a de
# fábrica; o admin pode reordenar categorias e itens dentro delas em
# "Ordem do menu lateral" (tabela configuracoes, chaves
# 'ordem_sidebar_grupos' e 'ordem_sidebar'). "Início" fica fixo no topo e
# as importações ficam no menu da conta (veja menu_lateral.py).
GRUPOS_SIDEBAR = [
    {"id": "alunos", "rotulo": "Alunos", "itens": ["arquivo_morto"]},
]
ROTULOS_SIDEBAR = {
    "inicio": "Início",
    "importar_notas": "Importar notas",
    "importar_alunos": "Importar alunos",
    "arquivo_morto": "Arquivo Morto",
}
