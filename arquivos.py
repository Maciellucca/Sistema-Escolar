"""
Arquivos enviados pela equipe (fotos dos alunos e fotos dos relatórios
escolares) guardados DENTRO do banco de dados, na tabela "arquivos".

Em hospedagem gratuita (ex: Render free) o disco do servidor é apagado a
cada reinício; com os arquivos no banco (MySQL na nuvem), nada se perde.
A pasta local de cada categoria (PHOTOS_DIR, RELATORIO_FOTOS_DIR) vira só
um cache: bibliotecas que precisam de um caminho de arquivo (PDF, planilha
das carteirinhas) usam caminho_local(), que recria o arquivo a partir do
banco quando ele não está no disco.

Instalações antigas, que têm os arquivos só no disco, continuam
funcionando: ao ler um arquivo que ainda não está no banco mas existe na
pasta, ele é copiado para o banco na hora.
"""
import mimetypes
from contextlib import nullcontext
from pathlib import Path

import config
from models import agora, get_db

FOTOS = "fotos"
RELATORIOS = "relatorios"


def _conexao(db):
    """Usa a conexão de quem chamou (dentro de uma transação já aberta — no
    SQLite uma segunda conexão ficaria esperando o lock) ou abre uma."""
    return nullcontext(db) if db is not None else get_db()


def _pasta(categoria):
    return {FOTOS: config.PHOTOS_DIR, RELATORIOS: config.RELATORIO_FOTOS_DIR}[categoria]


def _nome_seguro(nome):
    nome = Path(str(nome or "")).name  # nunca sai da pasta da categoria
    if not nome or nome in (".", ".."):
        raise ValueError("nome de arquivo inválido")
    return nome


def _gravar_cache(categoria, nome, conteudo):
    try:
        pasta = _pasta(categoria)
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / nome).write_bytes(conteudo)
    except OSError:
        pass  # o cache é opcional: o arquivo está no banco


def salvar(categoria, nome, conteudo, tipo=None, db=None):
    """Grava (ou substitui) o arquivo no banco e no cache local."""
    nome = _nome_seguro(nome)
    tipo = tipo or mimetypes.guess_type(nome)[0] or "application/octet-stream"
    with _conexao(db) as db:
        db.execute("DELETE FROM arquivos WHERE categoria = ? AND nome = ?", (categoria, nome))
        db.execute(
            "INSERT INTO arquivos (categoria, nome, conteudo, tipo, tamanho, updated_at) VALUES (?,?,?,?,?,?)",
            (categoria, nome, conteudo, tipo, len(conteudo), agora()),
        )
    _gravar_cache(categoria, nome, conteudo)


def ler(categoria, nome):
    """Bytes do arquivo, ou None se não existir."""
    try:
        nome = _nome_seguro(nome)
    except ValueError:
        return None
    with get_db() as db:
        r = db.execute("SELECT conteudo FROM arquivos WHERE categoria = ? AND nome = ?", (categoria, nome)).fetchone()
    if r is not None:
        return bytes(r["conteudo"])
    local = _pasta(categoria) / nome
    if local.is_file():  # instalação antiga: arquivo só no disco -> copia para o banco
        conteudo = local.read_bytes()
        salvar(categoria, nome, conteudo)
        return conteudo
    return None


def existe(categoria, nome):
    if not nome:
        return False
    try:
        nome = _nome_seguro(nome)
    except ValueError:
        return False
    with get_db() as db:
        if db.execute("SELECT 1 FROM arquivos WHERE categoria = ? AND nome = ?", (categoria, nome)).fetchone():
            return True
    return (_pasta(categoria) / nome).is_file()


def caminho_local(categoria, nome):
    """Caminho no disco local (recriado a partir do banco se preciso), ou
    None se o arquivo não existir."""
    if not nome:
        return None
    try:
        nome = _nome_seguro(nome)
    except ValueError:
        return None
    local = _pasta(categoria) / nome
    if local.is_file():
        return local
    conteudo = ler(categoria, nome)
    if conteudo is None:
        return None
    _gravar_cache(categoria, nome, conteudo)
    return local if local.is_file() else None


def apagar(categoria, nome, db=None):
    try:
        nome = _nome_seguro(nome)
    except ValueError:
        return
    with _conexao(db) as db:
        db.execute("DELETE FROM arquivos WHERE categoria = ? AND nome = ?", (categoria, nome))
    (_pasta(categoria) / nome).unlink(missing_ok=True)


def apagar_por_prefixo(categoria, prefixo, exceto=None, db=None):
    """Remove arquivos da categoria cujo nome começa com o prefixo (ex: a foto
    antiga em .jpg quando o aluno ganha uma .png)."""
    with _conexao(db) as conn:
        nomes = [r["nome"] for r in conn.execute(
            "SELECT nome FROM arquivos WHERE categoria = ? AND nome LIKE ?", (categoria, prefixo + "%")
        ).fetchall() if r["nome"].startswith(prefixo)]
    for p in _pasta(categoria).glob(prefixo + "*"):
        nomes.append(p.name)
    for nome in set(nomes):
        if nome != exceto:
            apagar(categoria, nome, db=db)
