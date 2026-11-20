# PHOENIX — INSTAGRAM / META INTEGRATION
**Data:** 2026-11-20
**Status:** Módulo funcional, testes validados, código limpo
**Branch:** feat/missao-028-auth-persistent-session

---

## 1. HISTÓRICO RECUPERADO

### Sessões Phoenix Restauradas
| Session ID | Foco | Tamanho | Status |
|------------|------|---------|--------|
| `0ba2376f-faa1-41e4-8019-0bfd49c6cffc` | YT+IG+TT completo | 18 MB | ✅ Restaurado |
| `067260fc-e9b2-4b59-92c5-d98b3e7c6043` | IG+TT | 5.0 MB | ✅ Restaurado |
| `94a2f9dc-544f-4186-8750-769e06bc1eb4` | IG focus | 3.7 MB | ✅ Restaurado |
| `c2a13616-087a-4996-a59b-da8e3c06d572` | Setup inicial | 2.7 MB | ✅ Restaurado |

Sessões pesadas (300MB+) permanecem no backup SSD externo (`/Volumes/SSD EXT MACBOOK/FORMATAÇÃO MACBOOK/`) para restauração sob demanda.

### Decisões Anteriores
- **Estratégia híbrida:** API Meta oficial como método principal; Browser Publisher (Playwright, Missão 019) como fallback permitido.
- **Arquitetura monolítica:** Sessões GTA-6 não são separadas por rede social; desenvolvimento integrado YT+IG+TT.
- **Credenciais:** Armazenadas em `data/credentials/{profile_id}/instagram_oauth.json`, nunca em código ou logs.

---

## 2. CONFIGURAÇÕES META COMPROVADAS

| Campo | Valor |
|-------|-------|
| Meta App Name | JHC VIRAL ENGINE |
| App ID | `1819988955893243` |
| Instagram Account | @leonidagta6flashbr |
| Instagram User ID | `17841479885114087` |
| Facebook Page | Leonida GTA VI Flash BR |
| Portfolio | Leonida GTA VI Flash BR \| GTA 6 |
| Site | `https://jhc-viral-engine.netlify.app` |
| Graph API Version | v21.0 |
| Token Type | Long-lived (~60 dias) |
| Scopes Aprovados | `instagram_business_basic`, `instagram_business_content_publish` |
| Token Expiry | ~59 dias restantes (validado 2026-11-20) |
| Refresh Token | Não disponível (token de longa duração direto) |

### Estado OAuth
- ✅ Token válido e legível
- ✅ Account ID configurado
- ✅ Scopes corretos para Content Publishing API
- ⚠️ Sem refresh_token — renovação manual necessária quando expirar
- ⚠️ Modo de desenvolvimento Meta — publicação limitada a contas de teste

---

## 3. INTEGRAÇÃO EXISTENTE

### Módulo Canônico: `src/publishing/adapters.py` → `InstagramAdapter`
- **Fluxo de 3 etapas** (Content Publishing API):
  1. `POST /{ig_user_id}/media` → cria container REELS
  2. `GET /{container_id}?fields=status_code` → poll até FINISHED
  3. `POST /{ig_user_id}/media_publish` → publica container finalizado
- **Validação de URL:** Rejeita caminhos locais; exige HTTPS público
- **Permalink:** Busca `shortcode` via `GET /{media_id}` para URL válida
- **Tratamento de erros:** PERMISSION_REQUIRED, TOKEN_EXPIRED, ERROR, PROCESSING
- **Integração:** Usado por `AutoPublishScheduler` (scheduler canônico)

### OAuth Manager: `src/publishing/oauth.py`
- Fluxo PKCE completo para Instagram, YouTube, TikTok
- Armazenamento seguro em `data/credentials/{profile_id}/`
- Auto-refresh quando refresh_token disponível
- Estados explícitos: NOT_CONFIGURED, AUTH_REQUIRED, CONNECTED, TOKEN_EXPIRED, PERMISSION_REQUIRED, ERROR

### Browser Publisher (Missão 019): `src/publishing/browser_publisher.py`
- Fallback Playwright para Instagram, YouTube, TikTok
- Sessão persistente via cookies
- Screenshots de auditoria em cada etapa
- **NÃO modificado nesta operação** — compatibilidade preservada

### Código Removido (Dead Code)
- ❌ `src/publishing/instagram_publisher.py` — removido (duplicação órfã do fluxo de 3 etapas)
- ❌ `src/publishing/auto_publisher.py` — removido (implementação síncrona legada com Graph API v18.0)
- Endpoints `/api/auto-publish/*` convertidos para stubs de depreciação (HTTP 410) apontando para `/api/autopublish/*`

---

## 4. RENOVAÇÃO AUTOMÁTICA DE TOKEN (P2)

### Implementado: `OAuthManager.refresh_instagram_token()`
- **Endpoint:** `GET https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=<token>`
- **Buffer:** Renova quando faltam ≤1 dia para expiração
- **Persistência atômica:** Preserva account_id, scopes, connected_at; atualiza apenas access_token e expires_at
- **Estados diferenciados:** `connected` (sucesso), `token_expired` (revogado/expirado → re-auth), `error` (falha temporária)
- **Endpoint API:** `POST /api/oauth/instagram/refresh` com body `{"profile_id": "..."}`
- **Testes:** 5 casos cobrindo skip, auth_required, chamada ao endpoint ig, erro de token expirado e persistência em disco

### Estado Atual do Token
- ✅ Válido, ~59 dias restantes
- ✅ Scopes: `instagram_business_basic`, `instagram_business_content_publish`
- ✅ Account ID: `17841479885114087`
- ⚠️ Sem refresh_token no arquivo (modalidade Instagram Login usa ig_refresh_token via access_token)

---

## 5. PENDÊNCIAS REAIS

| # | Pendência | Severidade | Ação Necessária |
|---|-----------|------------|-----------------|
| 1 | Align `OAUTH_CONFIGS.refresh_url` para v21.0 | Warning | Editar `oauth.py` linha 38 |
| 2 | Converter `httpx.get()` síncrono em `oauth.py:handle_callback` para async | Warning | Refatorar para `httpx.AsyncClient` |
| 3 | Wire `check_rate_limit()` antes de publicações em escala | Info | Adicionar pré-check no scheduler |
| 4 | Delegar `InstagramAdapter.check_connection` para `OAuthManager.get_connection_state()` | Info | Eliminar duplicação de parsing de credenciais |
| 5 | Integração Instagram → Browser Publisher (Missão 019) | Info | Conectar adapter ao fallback Playwright compartilhado |
| 6 | Aprovação Meta para produção (app em modo desenvolvimento) | Bloqueio externo | Submeter app review quando pronto |

---

## 5. TESTES

### Suite: `tests/test_instagram_adapter.py`
- **Total:** 19 testes
- **Resultado:** ✅ 19/19 PASSED
- **Ambiente:** Python 3.12.16 (uv-managed), venv isolado em `/tmp/jhc-ig-test-venv`
- **Tempo:** 0.16s

### Cobertura
| Categoria | Testes | Status |
|-----------|--------|--------|
| Autenticação / Conexão | 6 | ✅ Valid token, expired, corrupt, empty, legacy fallback |
| Upload (fluxo completo) | 7 | ✅ Success, permission denied, network error, URL validation, hashtags |
| Poll Status | 4 | ✅ Published unchanged, no post_id, PUBLISHED detected, ERROR detected |
| Credenciais Reais | 2 | ✅ File readable, token not expired |

### Gaps de Cobertura Identificados
- Integração end-to-end `AutoPublishScheduler → InstagramAdapter → Meta API`
- `OAuthManager.get_connection_state()` integrado ao adapter
- Rate limit pre-check
- Shortcode permalink generation (mockado no teste de sucesso)

---

## 6. COMMITS REALIZADOS

| Commit | Descrição |
|--------|-----------|
| (pendente) | feat: InstagramAdapter.upload() real com Graph API v21.0 + validação de URL + shortcode permalink |
| (pendente) | refactor: remover instagram_publisher.py e auto_publisher.py (dead code) |
| (pendente) | fix: endpoints /api/auto-publish/* retornam HTTP 410 com redirect para scheduler canônico |
| (pendente) | test: 19 testes do InstagramAdapter (auth, upload, poll, creds reais) |
| (pendente) | docs: PHOENIX-INSTAGRAM-META.md com contexto recuperado e estado atual |

---

## 7. COMPATIBILIDADE

### Missão 019 (Browser Publisher)
- ✅ **Preservada intacta** — nenhum arquivo modificado
- ✅ Estratégia híbrida mantida: API prioritária + Playwright fallback
- ✅ Scheduler canônico (`AutoPublishScheduler`) usa `adapters.py`, não toca em `browser_publisher.py`

### Recursos do MacBook M2 (8GB RAM)
- ✅ Ambiente de teste isolado em `/tmp` (não consome disco do projeto)
- ✅ Testes executam em 0.16s sem carga significativa
- ✅ Sem serviços persistentes iniciados

### Contratos Compartilhados
- ✅ `PublishJob` dataclass mantido
- ✅ `PublishState` enum inalterado
- ✅ Interface `upload(job) → PublishJob` preservada
- ✅ Credential path `data/credentials/{profile_id}/instagram_oauth.json` consistente

---

## 8. PRÓXIMA MISSÃO

**Missão Recomendada:** Alinhamento OAuth + Rate Limit Enforcement

1. Atualizar `OAUTH_CONFIGS.refresh_url` para v21.0
2. Converter `handle_callback` para async httpx
3. Wire `check_rate_limit()` no scheduler antes de publicações
4. Delegar `check_connection` para `OAuthManager`
5. Adicionar testes de integração scheduler→adapter
6. Submeter app Meta para review de produção (quando funcionalidades estiverem estáveis)

---

*Documento gerado autonomamente durante Operação Phoenix P1.*
*Nenhuma credencial exposta. Nenhuma publicação real executada.*