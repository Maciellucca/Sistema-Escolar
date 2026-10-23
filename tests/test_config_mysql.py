"""MYSQL_URL / DATABASE_URL (como os provedores na nuvem mostram) e SSL."""
import importlib


def _config(monkeypatch, **env):
    for k in ("MYSQL_URL", "DATABASE_URL", "MYSQL_SSL", "MYSQL_SSL_CA", "DB_BACKEND"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import config
    return importlib.reload(config)


def test_url_completa_com_ssl(monkeypatch):
    c = _config(monkeypatch, MYSQL_URL="mysql://avnadmin:s%40nha%3A1@meu-host.aivencloud.com:12345/defaultdb?ssl-mode=REQUIRED")
    assert (c.DB_BACKEND, c.MYSQL_HOST, c.MYSQL_PORT, c.MYSQL_USER, c.MYSQL_PASSWORD, c.MYSQL_DATABASE, c.MYSQL_SSL) == (
        "mysql", "meu-host.aivencloud.com", 12345, "avnadmin", "s@nha:1", "defaultdb", "required")
    c = _config(monkeypatch, DATABASE_URL="mysql://u:p@h:4000/test?ssl_mode=VERIFY_IDENTITY")
    assert c.DB_BACKEND == "mysql" and c.MYSQL_SSL == "verify" and c.MYSQL_PORT == 4000


def test_sem_url_continua_sqlite(monkeypatch):
    c = _config(monkeypatch, DATABASE_URL="postgres://x")
    assert c.DB_BACKEND == "sqlite" and c.MYSQL_SSL == ""


def test_contexto_ssl(monkeypatch):
    import ssl
    import models
    c = _config(monkeypatch, MYSQL_SSL="required")
    ctx = models._ssl_mysql()
    assert ctx.verify_mode == ssl.CERT_NONE
    c = _config(monkeypatch, MYSQL_SSL="verify")
    ctx = models._ssl_mysql()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    _config(monkeypatch)
    assert models._ssl_mysql() is None
