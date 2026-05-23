# PyCharm Professional — Setup do Projeto Hedge-Control

Guia complementar aos XMLs versionados em `.idea/` (gerados em 2026-05-21).
A maior parte da configuração já está pronta — este documento cobre **só o
que depende da sua máquina** (interpreter, senhas, plugins) e atalhos úteis.

> O `.idea/` deste projeto está em `.gitignore`, então alterações locais não
> vão para o repositório. Trate este setup como pessoal.

---

## 1. Interpreter Python (obrigatório)

Os XMLs em `.idea/misc.xml` e em `.idea/runConfigurations/*.xml` esperam um
SDK registrado com o nome exato:

```
Python 3.12 (Hedge-Control-New)
```

Registre uma vez:

1. `File → Settings → Project: Hedge-Control-New → Python Interpreter`
2. Engrenagem → **Add Interpreter → Add Local Interpreter**
3. Aba **Virtualenv Environment → Existing**
4. Interpreter: `D:\Projetos\Hedge-Control-New\backend\.venv\Scripts\python.exe`
5. No diálogo final, renomeie o SDK para **exatamente**
   `Python 3.12 (Hedge-Control-New)` (caso o PyCharm escolha outro nome).
6. OK / Apply. Reindexe.

> Por que `backend/.venv` e não a raiz? A `.venv` na raiz do projeto está
> quebrada (sem `pyvenv.cfg`). O ambiente válido vive em `backend/.venv` e
> usa Python 3.12.10 (CPython 3.12.10 do `pythoncore-3.12-64`).

---

## 2. Node interpreter

`File → Settings → Languages & Frameworks → Node.js`. Aponte para sua
instalação local (qualquer Node ≥ 20 LTS serve — o projeto usa Vite 7).
Marque "Coding assistance for Node.js" se quiser autocompletar de APIs do Node.

---

## 3. Postgres no Database Tool

`.idea/dataSources.xml` já contém duas conexões:

| Datasource | URL | Usuário |
|---|---|---|
| HedgeControl @ localhost (Postgres docker) | `jdbc:postgresql://localhost:5433/hedgecontrol` | `hc` |
| HedgeControl test.db (SQLite) | `jdbc:sqlite:$PROJECT_DIR$/test.db` | — |

Na primeira conexão o PyCharm vai pedir a senha. Use **`hc`** (a credencial
de dev definida no `docker-compose.yml`). Escolha "Save → In KeePass /
Windows Credential Manager" — a senha **não vai para o XML**.

> **Por que 5433 e não 5432?** O `docker-compose.yml` publica o Postgres do
> container na porta **5433** do host para não colidir com uma instalação
> nativa de Postgres no Windows (que normalmente ocupa a 5432). Dentro da
> rede do compose, o banco continua respondendo na 5432 — por isso o
> backend container usa `db:5432`. Só o **host** vê 5433.

Antes de conectar, suba o Postgres:

```sh
docker compose up -d db
```

Depois `Test Connection`. Se falhar, confirme que `localhost:5433` está
publicado (`docker ps` deve mostrar `0.0.0.0:5433->5432/tcp`).

---

## 4. Plugins recomendados (instale via Marketplace)

| Plugin | Por quê |
|---|---|
| **Ruff** (Astral Software) | Lint + format on save, casa com `backend/ruff.toml` |
| **Pydantic** (JetBrains) | Autocompletar de `BaseModel`, validators, `Field` |
| **Svelte** (JetBrains) | Sintaxe + IntelliSense de `.svelte` (essencial) |
| **Tailwind CSS** (JetBrains) | Autocomplete de classes Tailwind 4 |
| **EnvFile** ou **.env files support** | Carrega `.env` em run configs (alternativa ao bloco `<envs>`) |
| **.ignore** (JetBrains) | Edita `.gitignore` / `.dockerignore` com lint |
| **Mermaid** | Renderiza diagramas em `docs/**/*.md` (constituição, governance) |
| **Conventional Commit** (opcional) | Se você quiser disciplinar mensagens de commit |

Após instalar **Ruff**, abra `Settings → Tools → Ruff` e:

- ✅ Enable Ruff
- ✅ Use ruff format
- Ruff config path: `$PROJECT_DIR$/backend/ruff.toml`
- Ruff executable: `$PROJECT_DIR$/backend/.venv/Scripts/ruff.exe`
- Run ruff on save: **on**

---

## 5. Pytest

Já está configurado como test runner padrão (no `Hedge-Control-New.iml`).
O `pytest.ini` em `backend/pytest.ini` registra o marker `no_mock_whatsapp`.

Configurations versionadas (aparecem no dropdown do canto superior direito):

- **Tests: Pytest full suite** — roda `pytest -x -q` em `backend/tests`
- **Tests: Pytest current file** — roda o arquivo aberto no editor

Para rodar **um único teste por nome**, clique no triângulo na margem do
editor (gutter) ao lado do `def test_…`.

---

## 6. Run configurations versionadas

Ao reabrir o projeto, você terá no dropdown:

**Backend**
- Backend: Uvicorn dev (porta 8000, reload)
- Backend: Scheduler (worker separado — só rode local se for testar jobs)

**DB / Migrations**
- DB: Alembic upgrade head
- DB: Alembic revision --autogenerate (edite o `-m "CHANGE_ME"` antes de rodar)

**Lint**
- Lint: Ruff check
- Lint: Ruff format

**Tests**
- Tests: Pytest full suite
- Tests: Pytest current file

**Frontend**
- Frontend: npm dev (Vite 5173)
- Frontend: npm build
- Frontend: svelte-check
- Frontend: vitest (unit tests)
- Frontend: playwright e2e (requer docker stack ativo)
- Frontend: regen API types (regenera `schema.d.ts` do `/openapi.json`)

**Docker**
- Docker: Compose up (db + backend + frontend) — requer plugin Docker

**Compound (dispara várias)**
- Compound: Backend + Scheduler
- Compound: Full dev stack (backend + frontend) ← **use este no dia-a-dia**

> ⚠️ Antes de rodar `Compound: Backend + Scheduler` confirme que nenhum
> serviço Railway `scheduler` está apontando para o mesmo DB.
> O constitution proíbe dois schedulers concorrentes (`CLAUDE.md` §
> "Background scheduler").

---

## 7. Variáveis de ambiente

As run configs do backend já vêm com `APP_ENV=development`,
`DATABASE_URL=postgresql+psycopg://hc:hc@localhost:5433/hedgecontrol`,
`AUDIT_SIGNING_KEY=dev-only-do-not-use-in-prod-replace-me` e
`SCHEDULER_DISABLED=true` injetados. **Não rode contra produção a partir
do PyCharm** — confirme sempre a URL antes de `Alembic upgrade head`.

Para o frontend, lembre: `VITE_*` vivem em `frontend-svelte/.env`, não na
raiz (Vite `envDir`). Crie esse arquivo se ainda não tem:

```
VITE_API_BASE_URL=http://localhost:8000
VITE_CLERK_PUBLISHABLE_KEY=<sua chave dev do Clerk>
```

---

## 8. Pre-push hook (dispatch review)

O projeto tem um pre-push hook versionado em `.githooks/pre-push` que roda
um review LLM em arquivos `docs/**/*-dispatch.md`. Instale uma vez:

```sh
python scripts/install_git_hooks.py
```

Isso seta `core.hooksPath = .githooks`. O hook precisa de `ANTHROPIC_API_KEY`
em `.env`. Se quiser pular em algum push (autorização do orquestrador),
use `git push --no-verify` — mas isso é dívida institucional, não rotina.

---

## 9. Atalhos de produtividade

Os mais úteis no dia-a-dia deste projeto:

| Ação | Atalho (Windows) |
|---|---|
| Procurar em qualquer lugar | `Shift Shift` |
| Find Usages (onde algo é usado) | `Alt+F7` |
| Go to Definition | `Ctrl+B` |
| Recent Files | `Ctrl+E` |
| Reformat (ruff via plugin) | `Ctrl+Alt+L` |
| Optimize Imports | `Ctrl+Alt+O` |
| Run current config | `Shift+F10` |
| Debug current config | `Shift+F9` |
| Switch run config | `Alt+Shift+F10` |
| Database console (no datasource) | F4 |
| HTTP Client scratch | `Ctrl+Alt+Shift+Insert` → HTTP Request |
| Terminal | `Alt+F12` |
| Git log | `Alt+9` |
| TODO panel | `Alt+6` |

> Em sistema institucional financeiro, `Find Usages` em uma função de
> precision/pricing antes de mudar a assinatura **não é opcional** — veja
> a regra "Backend é authoritative para economia" em `CLAUDE.md`.

---

## 10. HTTP Client (substitui Postman)

O PyCharm Pro tem `.http` files. Crie `backend/scratches/api.http`:

```http
### Health
GET http://localhost:8000/health

### Login (Clerk JWT — copie do navegador)
GET http://localhost:8000/orders
Authorization: Bearer {{jwt}}
X-CSRF-Token: {{csrf}}
```

Defina o `{{jwt}}` em `Settings → Tools → HTTP Client → Edit Environment
Variables`. Vai render direto na aba ao lado do código.

---

## 11. File watchers (opcional)

Se você **não** instalou o plugin Ruff, dá pra fazer format-on-save com
File Watchers nativos: `Settings → Tools → File Watchers → +` →
`<custom>` apontando para `backend/.venv/Scripts/ruff.exe format $FilePath$`,
scope `Python`. Eu **recomendo o plugin** — é menos burocrático.

---

## 12. Troubleshooting comum

**"No Python interpreter configured"**
→ Você não registrou o SDK com o nome exato `Python 3.12 (Hedge-Control-New)`.
Volte para a seção 1.

**Pytest acha 0 testes**
→ Confirme `Working Directory = $PROJECT_DIR$/backend` na run config
(já está nos XMLs versionados). Se ainda assim 0, rode
`Tests: Pytest full suite` pelo menos uma vez para o PyCharm descobrir o
plugin path.

**Svelte/TS sem IntelliSense**
→ Plugin Svelte não instalado, ou o Node interpreter não está apontando
para a instalação correta. Veja seção 2.

**Database Tool não encontra driver Postgres**
→ Primeira conexão pede para baixar driver. Clique "Download" no diálogo.

**Build do frontend lento**
→ Confirme que `frontend-svelte/node_modules` está excluído da indexação
(já está no `.iml`).

---

## 13. O que **não** está no `.idea/` versionado

Coisas que você ainda precisa fazer manualmente:

- Registrar o SDK (seção 1) — PyCharm guarda em `jdk.table.xml` global, não no projeto
- Senha do Postgres no datasource (seção 3) — fica no KeePass/Credential Manager
- Plugins (seção 4) — são por instalação do IDE
- Chaves Clerk no `frontend-svelte/.env` (seção 7)
- Instalar o git hook (`scripts/install_git_hooks.py`) (seção 8)

Tudo o que **está** versionado em `.idea/`:

```
.idea/
├── Hedge-Control-New.iml            # sources/tests/excludes
├── misc.xml                         # referência ao SDK Python
├── modules.xml                      # registro do módulo
├── vcs.xml                          # mapping Git
├── dataSources.xml                  # Postgres + SQLite
├── codeStyles/
│   ├── codeStyleConfig.xml
│   └── Project.xml                  # line 100, indent 4 Py / 2 TS
├── inspectionProfiles/
│   ├── profiles_settings.xml
│   └── Project_Default.xml          # alinhado com ruff
└── runConfigurations/
    ├── Backend__Uvicorn_dev.xml
    ├── Backend__Scheduler.xml
    ├── DB__Alembic_upgrade_head.xml
    ├── DB__Alembic_revision_autogenerate.xml
    ├── Tests__Pytest_full_suite.xml
    ├── Tests__Pytest_current_file.xml
    ├── Lint__Ruff_check.xml
    ├── Lint__Ruff_format.xml
    ├── Frontend__npm_dev.xml
    ├── Frontend__npm_build.xml
    ├── Frontend__svelte_check.xml
    ├── Frontend__vitest.xml
    ├── Frontend__playwright_e2e.xml
    ├── Frontend__api_types.xml
    ├── Docker__Compose_up.xml
    ├── Compound__Backend_full_stack.xml
    └── Compound__Full_dev_stack.xml
```

---

**Última atualização:** 2026-05-21.
