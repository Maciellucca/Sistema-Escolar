# Projeto Sistema Escolar — versão de apresentação

Recorte do Sistema Escolar completo, feito para o Projeto Integrador da
Univesp. Mantém só o fluxo de dados que o relatório descreve: **Início**
(painel de turmas), **Importar alunos**, **Importar notas** e **Arquivo
Morto**, mais o **Portal do responsável** (consulta do boletim por código).

Feito com **Python + Flask** e banco **SQLite ou MySQL** (a escolha é por
variável de ambiente, veja [docs/MYSQL.md](docs/MYSQL.md)). O front-end é
HTML/CSS renderizado pelo servidor, com um pouco de JavaScript para a busca
ao vivo, o painel de estatísticas e a tela de conferência das notas.

Todos os dados de exemplo são **fictícios**: a escola, os alunos e as Atas
Bimestrais geradas por `scripts/gerar_ata_ficticia.py` não correspondem a
pessoas reais.

Para colocar no ar, siga o [INICIO_RAPIDO.md](INICIO_RAPIDO.md).

## Dados pessoais de crianças

O sistema foi desenhado para dados que a LGPD protege com atenção especial
(menores de idade e, no caso do AEE, dado de saúde). Mesmo com base fictícia,
as proteções ficam ativas por padrão:

- `data/raw/` (arquivos originais) e `instance/` (banco SQLite) estão no
  `.gitignore` e não vão para o Git, nem em repositório privado.
- As fotos ficam no banco (tabela `arquivos`), não em pasta pública.
- O detalhe do laudo AEE só aparece para os perfis `admin` e `aee`; os
  demais veem apenas o selo "AEE".
- O responsável só enxerga o boletim do próprio filho, e o acesso é limitado
  a 10 tentativas por IP a cada 15 minutos.

Leia [docs/LGPD_PRIVACIDADE.md](docs/LGPD_PRIVACIDADE.md) antes de publicar.

## As quatro guias

- **Início**: busca de aluno, totais gerais e as turmas por turno
  (Manhã, Integral, Tarde), separadas por série. Cada turma abre a lista de
  alunos, a busca ao vivo e o painel de estatísticas.
- **Importar notas**: envio da Ata Bimestral em PDF (ou de um `.json` já
  processado). A leitura roda em segundo plano e os dados caem numa tela de
  conferência; nada chega ao boletim antes de "Confirmar e gravar".
- **Importar alunos**: planilha em três formatos aceitos (PILOTO,
  simplificado e AEE separado) e envio de fotos em lote.
- **Arquivo Morto**: registro permanente de quem já passou pela escola, em
  ordem decrescente por letra e número, com inserção manual e alerta de
  nome duplicado. O aluno marcado como transferido entra aqui sozinho.

## Portal do responsável

1. Na ficha do aluno, a equipe vê o **código de 6 números** do responsável
   (gerado na primeira consulta) e pode trocá-lo quando quiser.
2. O responsável acessa `/responsavel/`, digita o código e vê o boletim
   (conceitos P, S e NS, faltas e frequência, com destaque abaixo de 75%).
3. A tela oferece o boletim em PDF no formato do SGP.

O responsável nunca vê RA, filiação, laudo AEE nem dados de outros alunos.

## Estrutura

```
projeto-sistema-escolar-apresentacao/
├── app.py                  # Flask: registra os blueprints, segurança e cabeçalhos
├── config.py               # configuração por variáveis de ambiente
├── models.py               # esquema SQLite/MySQL e get_db() (abstrai o banco)
├── auth.py, csrf.py        # login, papéis, código do responsável, token CSRF
├── arquivos.py             # fotos guardadas no banco
├── menu_lateral.py         # itens do menu e ordem configurável
├── routes/
│   ├── staff.py            # login, painel, turma, ficha do aluno, usuários
│   ├── importacao.py       # importar notas (PDF/JSON) e alunos, conferência
│   ├── arquivo_morto.py    # guia Arquivo Morto
│   ├── guardian.py         # portal do responsável
│   ├── cursos.py           # só o ciclo de ensino, usado pelo portal
│   └── api.py              # API JSON (busca ao vivo e estatísticas)
├── templates/, static/     # HTML (Jinja2), CSS e JavaScript
├── scripts/                # importadores, gerador de Ata fictícia, migração para MySQL
├── tests/                  # suíte pytest (sempre contra SQLite isolado)
├── docs/                   # LGPD_PRIVACIDADE.md e MYSQL.md
└── render.yaml, Procfile   # deploy no Render
```

## Instalação e uso

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # troque SECRET_KEY e ADMIN_SETUP_KEY
python app.py                      # http://127.0.0.1:5000
```

Não existe cadastro público. O primeiro administrador é criado em
`/login/criar-admin` (com a `ADMIN_SETUP_KEY` do `.env`) ou pelo terminal:
`python scripts/criar_usuario.py admin "Seu Nome" admin --setor "Direção"`.
Perfis: `admin`, `direcao`, `secretaria`, `professor`, `pot` e `aee`.

Para testar sem dados reais, gere uma Ata fictícia (veja o passo 7 do
[INICIO_RAPIDO.md](INICIO_RAPIDO.md)) e envie pela guia **Importar notas**.

## Requisitos do Projeto Integrador

| Requisito | Onde está |
|---|---|
| Framework web | Flask (`app.py`, `routes/`) |
| Banco de dados | SQLite ou MySQL (`models.py`, `docs/MYSQL.md`) |
| JavaScript | `static/js/` (busca ao vivo, estatísticas, conferência das notas) |
| Nuvem | `render.yaml` e `Procfile`; MySQL gratuito na nuvem (Aiven) |
| API | `routes/api.py`, consumida por `fetch` |
| Acessibilidade | seção abaixo |
| Controle de versão | este repositório no GitHub |
| Testes | `tests/` (pytest) |
| Análise de dados (opcional) | `GET /api/turma/<turma>/estatisticas`: frequência média por bimestre e distribuição de conceitos |

## API interna

A tela da turma consulta `GET /api/turma/<turma>/alunos?q=<termo>` enquanto
se digita e mostra o painel de `GET /api/turma/<turma>/estatisticas`. A busca
da página inicial usa `GET /api/alunos?q=`. Todos exigem login da equipe.

## Acessibilidade

- Link "pular para o conteúdo" no topo de cada página.
- Avisos do sistema (`flash`) com `aria-live`, para leitores de tela.
- Foco visível no teclado (`:focus-visible`) em links, botões e campos.
- Cabeçalhos de tabela com `scope="col"`, `lang="pt-br"` e `alt`/`aria-label`
  nas fotos e nos círculos de iniciais.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Cada teste usa um banco isolado, sem tocar nos seus dados.

## Licença

Uso acadêmico e interno da unidade escolar. Adapte conforme a necessidade,
respeitando a seção de privacidade acima.
