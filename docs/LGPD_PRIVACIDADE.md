# Privacidade e LGPD — leia antes de publicar ou colocar em produção

Este sistema processa dados pessoais de crianças e, para alunos AEE, dado
sensível de saúde (laudo/diagnóstico). Sob a LGPD (Lei 13.709/2018), isso
exige cuidados redobrados. Este documento resume o que já foi feito no
projeto e o que fica sob sua responsabilidade como operador do sistema.

## Colocando isso na internet (hospedagem pública)

Rodar localmente/na rede da escola é um risco controlado. Publicar na
internet muda o jogo — qualquer pessoa no mundo pode tentar acessar o
sistema. Antes de fazer isso com dados reais:

- **HTTPS é obrigatório** — configure `ESCOLA_FORCE_HTTPS=1` só depois de
  confirmar que o domínio já serve HTTPS (a maioria das hospedagens gerencia
  isso automaticamente). Sem HTTPS, login e código trafegam legíveis na rede.
- **Escolha uma hospedagem com disco persistente** — várias plataformas
  apagam o sistema de arquivos a cada novo deploy/reinício. Se isso
  acontecer, você perde o banco de dados e as fotos. Configure
  `ESCOLA_DATA_DIR` apontando para um disco/volume persistente (veja
  `render.yaml` e o `INICIO_RAPIDO.md`).
- **Nunca rode com `debug=True`** exposto à internet — em produção o
  servidor real é o gunicorn (`Procfile`/`render.yaml`), que não usa esse
  modo.
- **Faça backup do banco regularmente** — um disco persistente na nuvem
  ainda pode falhar. Baixe uma cópia do `sistema_escolar.db` periodicamente e guarde
  com o mesmo cuidado que os arquivos originais do SGP.
- **Restrinja quem sabe a URL** enquanto o sistema estiver em fase de teste
  — evite indexação por buscadores (isso já é padrão em serviços com URL
  aleatória/subdomínio, mas confirme).

## O que já está tratado no código

1. **Dados reais nunca vão para o Git.** `data/raw/`, `instance/` (banco
   SQLite) e `static/photos/` estão no `.gitignore`. Só o *código* deve ser
   versionado — os dados ficam apenas na máquina/servidor onde o sistema
   roda.
2. **Minimização no portal do responsável.** A tela `/responsavel` mostra
   somente o boletim (disciplina, faltas, frequência, conceito) — nunca RA,
   filiação, data de nascimento, laudo AEE ou dados de outros alunos.
3. **Controle de acesso ao dado de saúde (AEE).** O selo "AEE" é visível a
   qualquer profissional logado (útil para identificação em sala), mas o
   *detalhe* do laudo/diagnóstico só é exibido para os perfis `admin` e
   `aee` (ver `config.PAPEIS_COM_ACESSO_AEE_DETALHE`).
4. **Acesso do responsável por código de 6 números**, ligado a um único
   aluno. A tela limita as tentativas por IP (10 a cada 15 minutos) e a
   equipe pode trocar o código de um aluno, ou de todos, a qualquer momento.
5. **Log de acesso.** A tabela `access_log` registra logins de staff e de
   responsáveis (sem conteúdo sensível, só quem acessou o quê e quando) —
   use para auditoria em caso de suspeita de uso indevido.
6. **Proteção contra força bruta.** Login de staff e acesso do responsável
   bloqueiam temporariamente após várias tentativas erradas seguidas.
7. **Proteção CSRF** em todos os formulários que alteram dados.
8. **Fotos não ficam em uma pasta pública fixa** — são servidas por uma
   rota que exige login da equipe, ou sessão do responsável (e, nesse caso,
   só a foto do próprio filho/tutelado).
9. **Páginas não ficam em cache do navegador.** Todo o sistema envia
    `Cache-Control: no-store`, `Pragma: no-cache` e `Expires: 0` em
    qualquer página dinâmica — assim, depois de sair (equipe ou
    responsável), apertar "voltar" no navegador não mostra uma cópia em
    cache da tela anterior, mesmo que a sessão já tenha sido encerrada
    no servidor. Arquivos estáticos (CSS/JS/imagens) ficam de fora dessa
    regra, já que não têm dado de ninguém.

## O que é responsabilidade de quem opera o sistema

- **Nunca** publique o repositório em um GitHub **público** com a pasta
  `data/` preenchida — confira o `.gitignore` antes do primeiro `git add`.
  Mesmo em repositório **privado**, evite: acessos privados ainda podem ser
  compartilhados/vazados.
- **Troque a `SECRET_KEY`** do `.env` antes de usar de verdade — a padrão do
  `.env.example` é só um placeholder.
- **Backups do `instance/sistema_escolar.db`** devem ser tratados com o mesmo
  cuidado que o arquivo original do SGP (dado sensível, acesso restrito).
- **Entrega do código ao responsável**: prefira entregar em mãos, por
  documento assinado, ou por um canal que a escola já usa oficialmente.
  Evite deixar códigos anotados em locais visíveis.
- **Fotos dos alunos**: trate como qualquer outro dado sensível — acesso
  restrito à equipe autorizada, sem redistribuição.
- **Base legal do tratamento**: como escola pública, o tratamento desses
  dados normalmente se apoia no cumprimento de obrigação legal/execução de
  políticas públicas (Art. 7º, II e 23 da LGPD) — confirme com a assessoria
  jurídica/DPO da sua rede de ensino qual a base aplicável na sua rede antes
  de operar com alunos reais.
- **Retenção de dados**: defina por quanto tempo os dados de um aluno
  transferido ou formado ficam no sistema, e um processo para removê-los
  quando não forem mais necessários.
- **Direitos dos titulares**: pais/responsáveis podem solicitar acesso,
  correção ou exclusão dos dados do menor — tenha um processo (mesmo que
  manual, junto à secretaria) para atender esses pedidos.

## Em caso de incidente

Se um código, o banco de dados ou fotos vazarem, siga o plano de resposta a
incidentes da sua rede de ensino (ou da Secretaria de Educação) e, se
aplicável, notifique a ANPD e os titulares conforme Art. 48 da LGPD.
