# PHOENIX — YOUTUBE INTEGRATION CONTINUITY DOCUMENT
**Data:** 2026-11-20  
**Branch:** `feat/missao-028-auth-persistent-session`  
**Último commit:** `6420330` (FASE 9 — TikTok Hybrid Publisher)  
**Status:** MISSÃO YT-006 CONCLUÍDA — PUBLICADOR HÍBRIDO OPERACIONAL  
**Python:** 3.12.16 (via uv) | **Testes YouTube:** 22/22 passed | **OAuth:** Token renovado com sucesso  

---

## 1. HISTÓRICO RECUPERADO

### Sessões Consultadas
| Session ID | Conteúdo YouTube | Tamanho | Status |
|------------|------------------|---------|--------|
| `0ba2376f-faa1-41e4-8019-0bfd49c6cffc` | ✅ 58 refs YT + IG + TT | 18 MB | Restaurada e validada |
| `067260fc-e9b2-4b59-92c5-d98b3e7c6043` | ✅ 2 refs YT | 5.0 MB | Restaurada |
| `94a2f9dc-544f-4186-8750-769e06bc1eb4` | ✅ 2 refs YT | 3.7 MB | Restaurada |
| `c2a13616-087a-4996-a59b-da8e3c06d572` | ✅ 2 refs YT (setup) | 2.7 MB | Restaurada |

### Sessões Pesadas (Não Restauradas — Backup SSD)
- `50ed7b87` (313 MB) — YT=4524 refs
- `c671e717` (324 MB) — YT=3780 refs
- `16999dfe` (317 MB) — YT=3857 refs
- `067fa287` (303 MB) — YT=3798 refs

**Nota:** Estas sessões contêm o histórico mais completo de desenvolvimento YouTube, mas excedem o limite seguro de RAM (8 GB). Podem ser restauradas individualmente sob demanda.

### Documentos Phoenix Utilizados
- `~/.claude/JHC-PHOENIX-INDICE-RECUPERACAO.md` — Índice mestre de sessões
- `~/.claude/JHC-PHOENIX-RELATORIO-NOTURNO.md` — Relatório Missão 07

---

## 2. CONFIGURAÇÕES VERIFICADAS

### Canal e Identidade
- **Nome do canal:** Leonida GTA VI Flash BR
- **Handle:** @LeonidagtaVIFlashBR
- **Profile ID no projeto:** `leonidagta6flashbr`
- **Site associado:** https://jhc-viral-engine.netlify.app

### Google Cloud / OAuth
- **Client ID:** Configurado em `.env` como `YOUTUBE_CLIENT_ID` ✅
- **Client Secret:** Configurado em `.env` como `YOUTUBE_CLIENT_SECRET` ✅
- **Escopos solicitados:**
  - `https://www.googleapis.com/auth/youtube.upload`
  - `https://www.googleapis.com/auth/youtube.readonly`
- **Redirect URI path:** `/api/oauth/callback/youtube`
- **Configuração OAuth no código:** `src/publishing/oauth.py:44-54`

### Token Existente
- **Arquivo:** `data/credentials/leonidagta6flashbr/youtube_oauth.json`
- **Campos presentes:** access_token, refresh_token, token_type, expires_at, scopes, client_id, code_verifier, connected_at, account_id, account_name
- **Estado atual:** ⚠️ **EXPIRADO** (expirou há ~21 horas em 2026-11-20)
- **Refresh token:** ✅ Disponível (permite renovação automática)
- **Estratégia de renovação:** Implementada em `oauth.py:437` (`refresh_token_if_needed`) — usa httpx POST para `https://oauth2.googleapis.com/token`

### Páginas de Verificação Google
- **Privacy Policy:** `frontend/privacy.html` ✅ (publicada via Netlify)
- **Terms of Service:** `frontend/terms.html` ✅ (publicada via Netlify)
- **Commit:** `b3bbd54` — "páginas /privacy e /terms publicadas no Netlify para verificação OAuth Google"

---

## 3. FUNCIONALIDADES EXISTENTES

### A. YouTubeAdapter (`src/publishing/adapters.py:192-247`)
**Estado:** ⚠️ PARCIAL — Estrutura completa, upload real é TODO

| Método | Status | Detalhes |
|--------|--------|----------|
| `check_connection()` | ✅ Completo | Verifica token, expiração, retorna PublishState |
| `upload()` | ❌ TODO (L227) | Retorna PERMISSION_REQUIRED; comentário descreve fluxo resumable upload |
| `poll_status()` | ❌ TODO (L246) | Retorna job sem alteração; comentário descreve GET videos API |
| `save_job()` / `load_job()` | ✅ Herdado | BaseAdapter persistência em disco |

### B. YouTubePublisher (`src/publishing/auto_publisher.py:88-158`)
**Estado:** ✅ UPLOAD REAL IMPLEMENTADO (usa google-api-python-client)

| Componente | Status | Detalhes |
|------------|--------|----------|
| Autenticação | ✅ | `google.oauth2.credentials.Credentials.from_authorized_user_info()` |
| Upload resumable | ✅ | `MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)` |
| Metadata | ✅ | title, description, tags, categoryId=20 (Gaming), privacyStatus |
| Response handling | ✅ | Extrai video_id, gera permalink |
| Error handling | ✅ | ImportError → "blocked"; Exception → "failed" |
| Fallback simulado | ✅ | Quando `is_configured == False`, retorna metadata simulado |

**Dependências necessárias:** `google-api-python-client`, `google-auth-oauthlib` (não listadas em pyproject.toml)

### C. Browser Publisher — YouTube (`src/publishing/browser_publisher.py:309-354`)
**Estado:** ✅ FLUXO PLAYWRIGHT COMPLETO (Missão 019 concluída)

| Etapa | Implementação |
|-------|---------------|
| Upload arquivo | `input[type="file"]` → `set_input_files()` |
| Preencher título | `#textbox` ou `[aria-label*="title"]` |
| Preencher descrição | `#description-textarea` ou `[aria-label*="description"]` + hashtags |
| Navegação wizard | 4× clique em "Próximo/Next" |
| Publicar | Clique em "Publicar/Publish" |
| Screenshots | `youtube_after_upload`, `youtube_published` |
| Persistência | `_save_history()` salva resultado em JSON |

**Limitações conhecidas:**
- Não trata CAPTCHA ou MFA (requer sessão pré-autenticada)
- Não verifica conclusão do processamento pós-upload
- Selectores CSS podem quebrar com atualizações do YouTube Studio
- Sem retry logic específico para YouTube

### D. Endpoints API (`src/api/main.py`)
| Endpoint | Linha | Status |
|----------|-------|--------|
| `GET /api/youtube/auto-publish/status` | L1123 | ✅ Verifica worker, token, LaunchAgent |
| `POST /api/youtube/auto-publish/pause` | L1227 | ✅ Pausa worker |
| `POST /api/youtube/auto-publish/resume` | L1244 | ✅ Retoma worker |
| Stats por plataforma | L2833 | ✅ Inclui YouTube |
| Radar GTA VI YouTube | L3196 | ✅ yt-dlp search |

### E. OAuth Flow (`src/publishing/oauth.py`)
| Função | Linha | Status |
|--------|-------|--------|
| Config YouTube | L44-54 | ✅ URLs, escopos, env vars |
| Auth URL builder | L186 | ✅ Gera URL de consentimento |
| Token exchange | L282 | ✅ Code → access + refresh token |
| Refresh token | L437 | ✅ Renovação automática com buffer de 5 min |
| Save/load creds | L378 | ✅ Persistência em `youtube_oauth.json` |

---

## 4. ESTADO REAL DA AUTENTICAÇÃO

```
Token file:     data/credentials/leonidagta6flashbr/youtube_oauth.json
Access token:   PRESENTE (expirado)
Refresh token:  PRESENTE (válido)
Expires at:     1795120375 (~2026-11-19 18:00 UTC)
Scopes:         youtube.upload, youtube.readonly
Account name:   (vazio — não preenchido no token exchange)
Connected at:   1795064137 (~2026-11-19 02:00 UTC)
```

**Ação necessária:** O token está expirado, mas o refresh_token permite renovação automática. O método `refresh_token_if_needed()` em `oauth.py:437` deve funcionar desde que:
1. `YOUTUBE_CLIENT_ID` e `YOUTUBE_CLIENT_SECRET` estejam no `.env` ✅
2. As dependências estejam instaladas (httpx já está em pyproject.toml ✅)
3. O Google Cloud app esteja aprovado para os escopos solicitados

---

## 5. CÓDIGO IMPLEMENTADO — RESUMO POR ARQUIVO

| Arquivo | Linhas | Plataforma | Estado |
|---------|--------|-----------|--------|
| `src/publishing/adapters.py` | 565 | YT + IG + TT | YouTubeAdapter: check ✅ / upload ❌ / poll ❌ |
| `src/publishing/auto_publisher.py` | 384 | YT + IG + TT | YouTubePublisher: upload real ✅ |
| `src/publishing/browser_publisher.py` | 402 | YT + IG + TT | _publish_youtube ✅ (Playwright) |
| `src/publishing/oauth.py` | 628 | YT + IG + TT | Fluxo completo ✅ |
| `src/publishing/publish_state_machine.py` | 274 | Genérico | Estados definidos ✅ |
| `src/media/auth_session.py` | 426 | Genérico | Persistência de sessão ✅ |
| `src/api/auth.py` | 141 | Genérico | Endpoints auth ✅ |
| `src/api/main.py` | ~3300 | YT + IG + TT | Endpoints YouTube ✅ |

---

## 6. TESTES EXECUTADOS

**Estado:** ⛔ BLOQUEADO — Python >=3.11 não disponível

- Sistema tem apenas Python 3.9.6 (`/usr/bin/python3`)
- venv existente aponta para python3.14 (symlink quebrado)
- Homebrew, pyenv, conda, uv: nenhum instalado
- `pyproject.toml` exige `requires-python = ">=3.11"`

**Testes existentes no repositório:** 19 arquivos em `tests/`, nenhum específico para YouTube publishing.

---

## 7. COMMITS RELEVANTES (YouTube)

| Hash | Mensagem | Data |
|------|----------|------|
| `b3bbd54` | páginas /privacy e /terms publicadas no Netlify para verificação OAuth Google | Recente |
| `3a7b7cb` | Instagram OAuth token exchange + adapter credential path fix | Recente |
| `6d05c5f` | TikTok Content Posting API v2 — upload real + polling de status | Recente |
| `e03643c` | FASE 4 — orquestrador híbrido TikTok (API → Playwright fallback) | Recente |
| `6420330` | FASE 9 — painel TikTok Hybrid Publisher no dashboard + endpoint status | HEAD |

---

## 8. PENDÊNCIAS IDENTIFICADAS

### 🔴 CRÍTICAS (Bloqueiam publicação real)
1. **Instalar Python 3.11+** — Sem isso, nenhum teste ou desenvolvimento é possível
2. **Recriar venv** — Symlink para python3.14 está quebrado
3. **Instalar dependências YouTube** — `google-api-python-client`, `google-auth-oauthlib` não estão em pyproject.toml
4. **Renovar token OAuth** — Token expirado; refresh automático deve funcionar após setup do ambiente

### 🟡 IMPORTANTES (Completam a integração)
5. **Implementar `YouTubeAdapter.upload()`** (`adapters.py:227`) — Resumable upload via httpx (alternativa leve ao google-api-python-client)
6. **Implementar `YouTubeAdapter.poll_status()`** (`adapters.py:246`) — GET videos API para verificar processamento
7. **Adicionar testes unitários** para YouTubeAdapter e YouTubePublisher
8. **Preencher `account_name`** no token exchange (campo vazio)

### 🟢 MELHORIAS
9. **Thumbnail upload** — YouTubeAdapter não suporta `thumbnails.set()` ainda
10. **Agendamento** — `status.publishAt` comentado mas não implementado
11. **Shorts detection** — Diferenciar Shorts (<60s, vertical) de vídeos padrão
12. **Browser Publisher robustez** — Retry logic, verificação de processamento, tratamento de erros específicos do YouTube Studio

---

## 9. PRÓXIMA MISSÃO YOUTUBE

### Missão Sugerida: "YouTube Upload Real — Adapter + Testes"

**Objetivo:** Completar `YouTubeAdapter.upload()` e `poll_status()` usando httpx puro (sem google-api-python-client), tornando a integração independente de bibliotecas pesadas.

**Passos:**
1. Instalar Python 3.12+ e recriar venv
2. Implementar resumable upload em `adapters.py:227` (POST init → PUT chunks)
3. Implementar poll_status em `adapters.py:246` (GET videos?part=status)
4. Adicionar `google-api-python-client` e `google-auth-oauthlib` ao pyproject.toml (para YouTubePublisher)
5. Escrever testes unitários com tokens mock
6. Testar refresh automático do token expirado
7. Commit local na branch `feat/missao-028-auth-persistent-session`

**Dependências humanas:**
- Nenhuma para implementação e testes unitários
- Para teste end-to-end real: confirmar que o Google Cloud app está aprovado para os escopos youtube.upload e youtube.readonly

---

## 10. ESTRATÉGIA HÍBRIDA DE PUBLICAÇÃO

Conforme definido na Missão 019:

```
Prioridade 1: YouTube Data API v3 (OAuth2)
  → YouTubeAdapter.upload() [adapters.py] — httpx puro
  → YouTubePublisher.upload() [auto_publisher.py] — google-api-python-client
  → Requer: token válido + Google Cloud app aprovado

Prioridade 2: Browser Publisher (Playwright)
  → BrowserPublisher._publish_youtube() [browser_publisher.py]
  → Requer: sessão autenticada no YouTube Studio
  → Fallback quando API não disponível ou não aprovada
```

**Seleção automática:** Ainda não implementada. Atualmente o pipeline usa YouTubePublisher (auto_publisher.py) diretamente. A seleção automática entre API e Browser deve ser adicionada ao orquestrador.

---

*Documento criado durante Operação Phoenix — Recuperação de Histórico e Continuidade.*  
*Gerado em 2026-11-20 a partir de análise do repositório, índices Phoenix e código-fonte.*  
*Nenhum token, secret ou credencial foi impresso neste documento.*

---

## 11. MISSÃO YT-006 — RESULTADOS (2026-11-20)

### FASE 1 — Python Restaurado ✅
| Item | Antes | Depois |
|------|-------|--------|
| Python sistema | 3.9.6 (`/usr/bin/python3`) | 3.9.6 (intacto) |
| Python projeto | ❌ venv quebrado (symlink → python3.14 inexistente) | ✅ 3.12.16 via `uv` |
| Ferramenta | Nenhuma (sem brew/pyenv/conda) | `uv 0.13.9` standalone |
| Dependências core | ❌ Não instaláveis | ✅ fastapi, uvicorn, httpx, pillow, pytest |
| Dependências YouTube | ❌ Ausentes | ✅ google-api-python-client, google-auth-oauthlib |
| venv antigo | Preservado como `.venv.broken` | Novo `.venv` operacional |

### FASE 2 — YouTubeAdapter Concluído ✅
**Arquivo:** `src/publishing/adapters.py` (classe `YouTubeAdapter`, linha ~385)

| Método | Estado Anterior | Estado Atual |
|--------|----------------|--------------|
| `check_connection()` | Buscava `youtube_token.json` (arquivo errado) | ✅ Usa `OAuthManager.load_credentials()` com auto-refresh |
| `_get_access_token()` | Não existia | ✅ Novo método privado para token válido |
| `upload()` | TODO — retornava PERMISSION_REQUIRED | ✅ Resumable upload completo via httpx (init → chunks → completion) |
| `poll_status()` | TODO — retornava job sem alteração | ✅ GET /youtube/v3/videos com tratamento de todos os estados |

**Upload resumable implementado:**
- POST init com metadata (title, description, tags, categoryId=20, privacyStatus)
- Suporte a agendamento (`publishAt` + privacyStatus=private)
- Chunks de 10 MB com Content-Range headers
- Retry exponencial (até 5 tentativas por chunk)
- Tratamento de erros: 401 → TOKEN_EXPIRED, 403 → PERMISSION_REQUIRED, network → ERROR
- Verificação de Location header no init response

**Poll status implementado:**
- Estados tratados: processed → PUBLISHED, rejected → ERROR (com razão), failed → ERROR, deleted → ERROR, uploaded → PROCESSING
- Graceful degradation: API errors não quebram o job (retorna estado anterior)

### FASE 3 — Autenticação Verificada ✅
| Verificação | Resultado |
|-------------|-----------|
| Token antes do refresh | Expirado há ~21 horas |
| Refresh token disponível | ✅ Sim |
| Auto-refresh via OAuthManager | ✅ Novo access_token obtido |
| Token após refresh | Válido (expires_at atualizado) |
| Credenciais expostas em logs | ❌ Nunca (apenas flags booleanas) |

### FASE 4 — Integração Híbrida ✅
| Componente | Status |
|------------|--------|
| API oficial (YouTubeAdapter) | ✅ Prioridade 1 — upload real via httpx |
| Browser Publisher (Playwright) | ✅ Fallback existente da Missão 019 |
| OAuthManager compartilhado | ✅ Mesmo fluxo para API e Browser |
| Deduplicação PLATFORM constant | ✅ `YouTubeAdapter.PLATFORM == "youtube"` |
| Fila persistente | ✅ Herdada de BaseAdapter (jobs_dir) |
| Seleção automática API/Browser | ⚠️ Pendente (orquestrador futuro) |

### FASE 5 — Testes ✅
**Arquivo:** `tests/test_youtube_adapter.py` — 22 testes, todos passando

| Categoria | Testes | Status |
|-----------|--------|--------|
| check_connection | 4 (valid/no-token/expired/corrupt) | ✅ 4/4 |
| upload | 7 (no-creds/missing-file/403/401/success/no-location/scheduled) | ✅ 7/7 |
| poll_status | 7 (published/no-id/processed/rejected/failed/processing/api-error) | ✅ 7/7 |
| Hybrid dedup | 4 (platform-const/async-check/async-upload/async-poll) | ✅ 4/4 |

**Suite completa:** 41 passed, 22 new YouTube tests, 0 regressions  
**Falhas pré-existentes (não relacionadas):** `test_autoreel_quality.py`, `test_bulk_worker_persistence.py`

### FASE 6 — Consolidação ✅
- Este documento atualizado com resultados YT-006
- Commits locais pendentes (aguardando autorização para commit)
- Branch: `feat/missao-028-auth-persistent-session`

---

## 12. PENDÊNCIAS RESTANTES (PÓS YT-006)

| # | Pendência | Prioridade | Bloqueio |
|---|-----------|------------|----------|
| 1 | Seleção automática API vs Browser no orquestrador | 🟡 Média | Nenhum |
| 2 | Thumbnail upload (`thumbnails.set()`) | 🟢 Baixa | Nenhum |
| 3 | Shorts detection (<60s, vertical aspect ratio) | 🟢 Baixa | Nenhum |
| 4 | Commit local das alterações YT-006 | 🔴 Alta | Autorização do usuário |
| 5 | Teste end-to-end real com vídeo | 🔴 Alta | Autorização explícita |
| 6 | Google Cloud app approval verification | 🟡 Média | Acesso ao console GCP |

---

*Documento atualizado durante Missão YT-006 — Recuperação Python + Conclusão do Publicador Híbrido.*  
*Última atualização: 2026-11-20 ~14:00 UTC*  
*Nenhum token, secret ou credencial foi impresso neste documento.*
---

## 13. MISSÃO YT-007 — CONSOLIDAÇÃO DO PUBLICADOR HÍBRIDO (2026-11-20)

### FASE 1 — Auditoria de Continuidade ✅
| Investigação | Resultado |
|--------------|-----------|
| Antigo `YouTubePublisher` | Removido no commit P1 (`ac99872`) — era duplicata funcional do `YouTubeAdapter` |
| Uploads reais anteriores | Realizados via `YouTubePublisher.upload()` usando `google-api-python-client` |
| Novo `YouTubeAdapter` | Substitui completamente `YouTubePublisher` com upload resumable via httpx puro |
| Implementações concorrentes | ❌ Nenhuma — apenas `YouTubeAdapter` permanece |
| Arquivos compartilhados alterados | `autopublish_scheduler.py` (+144 linhas), `PHOENIX-YOUTUBE.md` (+95 linhas) |
| Missão 019 / BrowserPublisher | ✅ `_publish_youtube()` intacto e reutilizado como fallback |

### FASE 2 — Orquestração Híbrida Implementada ✅
**Arquivo:** `src/automation/autopublish_scheduler.py` — método `execute_youtube_hybrid()` (linha ~273)

**Política de seleção automática API → Playwright:**
1. Verifica `YouTubeAdapter.check_connection()` (com auto-refresh OAuth)
2. Se CONNECTED → tenta upload via API resumable
3. Se API retorna PROCESSING → **NÃO faz fallback** (resultado incerto)
4. Se API retorna PERMISSION_REQUIRED/TOKEN_EXPIRED/AUTH_REQUIRED → verifica sessão BrowserPublisher
5. Se sessão Playwright ativa → tenta upload via `BrowserPublisher._publish_youtube()`
6. Se ambos falham → marca job como failed/auth_required
7. **Nunca faz fallback após resultado incerto** (proteção contra duplicidade)

**Integração com Missão 019:**
- Reutiliza `BrowserPublisher._publish_youtube()` existente
- Reutiliza `BrowserPublisher.check_session("youtube")` para validação
- Reutiliza `PublishRequest` com `content_type="short"`
- Compartilha fila persistente, histórico e dashboard

### FASE 3 — Segurança e Recuperação ✅
| Garantia | Implementação |
|----------|---------------|
| Lock entre workers | Herdado de `AutoPublishScheduler._save_jobs()` (file-level) |
| Concorrência API/Playwright | Política de seleção sequencial — nunca simultâneo |
| Deduplicação SHA-256 | `AutoPublishJob.compute_content_hash()` + `submit_job()` idempotency |
| Upload resumível interrompido | Retry exponencial (5 tentativas/chunk) em `YouTubeAdapter.upload()` |
| Recuperação pós-restart | Jobs persistidos em `autopublish_jobs.json` + histórico |
| Erro 401 | TOKEN_EXPIRED → fallback Playwright se sessão ativa |
| Erro 403 | PERMISSION_REQUIRED → fallback Playwright se sessão ativa |
| Erro 429/5xx | ERROR com retry=True no scheduler |
| Refresh OAuth | Auto-refresh via `OAuthManager.load_credentials(auto_refresh=True)` |
| Sessão Playwright expirada | `check_session()` retorna `active=False` → auth_required |
| Idempotência | `idempotency_key` + `content_hash` previnem submissão duplicada |
| Limite 3 Shorts/dia | Herdado de `AutoPublishScheduler` global daily limit |

### FASE 4 — Testes de Integração ✅
**Arquivo:** `tests/test_youtube_hybrid_scheduler.py` — 10 testes, todos passando

| Categoria | Testes | Status |
|-----------|--------|--------|
| API path | success_published, processing_no_fallback, error_marks_failed | ✅ 3/3 |
| Fallback path | permission_required→playwright, token_expired→playwright, no_session→blocked, playwright_failure | ✅ 4/4 |
| Safety | uncertain_state_no_fallback, platform_constant, is_async | ✅ 3/3 |

**Suite completa YouTube:** 32 testes (22 adapter + 10 hybrid), 0 regressões

### FASE 5 — Regressões ✅
| Teste | Status | Classificação |
|-------|--------|---------------|
| `test_autoreel_quality.py::test_valid_video_passes` | FAILED | Pré-existente (confirmado via git stash no commit P1 base) |
| `test_bulk_worker_persistence.py::test_plist_exists` | FAILED | Pré-existente (LaunchAgent não instalado neste ambiente) |
| Todos os demais (41+) | PASSED | Sem regressões introduzidas pela YT-007 |

### FASE 6 — Dashboard ✅
O painel YouTube no dashboard (`frontend/index.html:1111`) já apresenta:
- ✅ Status OAuth (token health, expiry, refresh_token presence)
- ✅ Status do worker (pgrep + launchd check)
- ✅ Fila de publicação (queue state, schedule_hours)
- ✅ Stats diários (approved, failed, published_videos)
- ✅ Logs recentes (/tmp/jhc_yt_publisher.log)
- ✅ Controles de pausa/resume
- ⚠️ Método ativo (API/Browser) — visível nos logs, não em badge dedicado
- ⚠️ Estado autenticação Playwright — visível via `/api/browser-publisher/session/youtube`

### FASE 7 — Commit e Documentação ✅
- `docs/PHOENIX-YOUTUBE.md` atualizado com seções 11-13
- Commits organizados por fase (abaixo)
- Branch: `feat/missao-028-auth-persistent-session`

---

## 14. RELATÓRIO CONCLUSIVO YT-007

| Item | Estado |
|------|--------|
| Branch | `feat/missao-028-auth-persistent-session` |
| HEAD anterior | `ac99872` (P1 Instagram Adapter) |
| Commits YT-007 | Pendentes de autorização para push |
| Antigo YouTubePublisher | Removido em P1 — substituído por YouTubeAdapter |
| Arquitetura real | API (httpx resumable) → Playwright (BrowserPublisher._publish_youtube) |
| Fluxo seleção automática | `execute_youtube_hybrid()` no AutoPublishScheduler |
| Testes aprovados | 32/32 YouTube (22 adapter + 10 hybrid) |
| Testes falhos | 0 regressões; 2 pré-existentes confirmados |
| OAuth | Token renovado com sucesso; auto-refresh operacional |
| Scheduler | `execute_youtube_hybrid()` integrado; fila persistente |
| Dashboard | Painel YouTube funcional; controles pause/resume |
| Missão 019 | BrowserPublisher._publish_youtube() reutilizado como fallback |
| Publicação real | ⛔ NÃO EXECUTADA — aguarda autorização explícita |
| Bloqueios efetivos | Nenhum técnico; apenas autorização humana para publicação real |

*Documento atualizado durante Missão YT-007 — Consolidação do Publicador Híbrido YouTube.*
*Última atualização: 2026-11-20 ~15:30 UTC*
*Nenhum token, secret ou credencial foi impresso neste documento.*
