# PHOENIX-TIKTOK — Relatório de Recuperação e Continuidade

**Data:** 2026-11-20
**Operação:** Phoenix — Recuperação Pós-Formatação MacBook
**Branch Atual:** `feat/missao-028-auth-persistent-session`
**Repositório:** `/Volumes/SSD EXT MACBOOK/JHC-PROJETOS/JHC VIRAL ENGINE/GTA 6`

---

## 1. HISTÓRICO RECUPERADO

### Sessões Utilizadas para Recuperação
| Session ID | Foco | Tamanho | Status |
|-----------|------|---------|--------|
| `0ba2376f-faa1-41e4-8019-0bfd49c6cffc` | YT+IG+TT (completa) | 18 MB | ✅ Restaurada |
| `067260fc-e9b2-4b59-92c5-d98b3e7c6043` | IG+TT | 5.0 MB | ✅ Restaurada |
| `94a2f9dc-544f-4186-8750-769e06bc1eb4` | IG focus | 3.7 MB | ✅ Restaurada |
| `c2a13616-087a-4996-a59b-da8e3c06d572` | Setup inicial | 2.7 MB | ✅ Restaurada |

### Sessões Pesadas (Não Restauradas — Backup SSD)
- `50ed7b87` (313 MB), `c671e717` (324 MB), `16999dfe` (317 MB), `067fa287` (303 MB)
- Contêm milhares de referências TikTok; restaurar sob demanda individualmente.

---

## 2. CONFIGURAÇÕES VERIFICADAS

### Aplicativo TikTok Developer Portal
- **Client Key:** Configurado em `.env` como `TIKTOK_CLIENT_KEY` ✅
- **Client Secret:** Configurado em `.env` como `TIKTOK_CLIENT_SECRET` ✅
- **Redirect URI:** `/api/oauth/callback/tiktok` (via proxy Netlify → Render backend)
- **Domínio de Verificação:** Arquivo de verificação adicionado ao site (`commit 3397c7e`)
- **Páginas Legais:** `/privacy` e `/terms` publicadas no Netlify (`commit b3bbd54`, `275e6bf`)

### OAuth 2.0 PKCE
- **Implementação:** `src/publishing/oauth.py` — classe `OAuthManager`
- **Geração PKCE:** `generate_pkce()` usa `secrets.token_urlsafe(64)` + SHA-256 + base64url ✅
- **code_verifier:** Persistido em `_oauth_states/{state}.json` durante fluxo, limpo após troca ✅
- **code_challenge_method:** `S256` ✅
- **Parâmetros de Autorização TikTok:**
  - `client_key` (não `client_id`) ✅
  - `scope`: `user.info.basic,video.publish,video.upload` ✅
  - `response_type`: `code` ✅
  - `code_challenge` + `code_challenge_method=S256` ✅

### Troca de Código por Token
- **Endpoint:** `https://open.tiktokapis.com/v2/oauth/token/` ✅
- **Parâmetros:** `client_key`, `client_secret`, `grant_type=authorization_code`, `redirect_uri`, `code`, `code_verifier` ✅
- **Refresh Token:** Implementado em `refresh_token_if_needed()` com `client_key` específico para TikTok ✅
- **Expiração:** 86400s (24h) padrão TikTok; auto-refresh 5 min antes do vencimento ✅

### Permissões e Aprovações
- **Escopos Solicitados:** `user.info.basic`, `video.publish`, `video.upload`
- **Status da Aprovação:** ⚠️ PENDENTE — O app retorna `PERMISSION_REQUIRED` quando tenta Direct Post via API
- **Fallback:** Quando API não aprovada, orquestrador híbrido tenta Playwright automaticamente

---

## 3. ESTADO DA IMPLEMENTAÇÃO

### Módulos Existentes

| Arquivo | Função | Status |
|---------|--------|--------|
| `src/publishing/adapters.py:250-443` | `TikTokAdapter` — Content Posting API v2 | ✅ Upload real + polling |
| `src/publishing/oauth.py:56-64` | Config OAuth TikTok + PKCE | ✅ Completo |
| `src/publishing/oauth.py:291-299` | Token exchange com `client_key` | ✅ Correto |
| `src/publishing/oauth.py:474-477` | Refresh token com `client_key` | ✅ Correto |
| `src/publishing/browser_publisher.py:356-387` | `_publish_tiktok()` via Playwright | ✅ Implementado |
| `src/automation/autopublish_scheduler.py:149-271` | `execute_tiktok_hybrid()` | ✅ Orquestrador API→Playwright |
| `src/api/main.py:1260-1314` | `/api/tiktok/auto-publish/status` | ✅ Endpoint dashboard |

### Fluxo Híbrido TikTok (Implementado)
```
1. TikTokAdapter.check_connection() → CONNECTED?
   ├─ SIM → upload() via Content Posting API v2
   │         ├─ PROCESSING → poll_status() → PUBLISHED/FAILED
   │         ├─ PERMISSION_REQUIRED → fallback para passo 2
   │         └─ FAILED → mark_failed(retry=True)
   └─ NÃO → passo 2

2. BrowserPublisher.check_session("tiktok") → ativa?
   ├─ SIM → _publish_tiktok() via Playwright
   │         ├─ success → mark_published()
   │         └─ fail → mark_failed(retry=True)
   └─ NÃO → auth_required (login manual necessário)
```

### Credenciais e Sessões Persistentes
| Arquivo | Conteúdo | Status |
|---------|----------|--------|
| `data/browser_sessions/tiktok_cookies.json` | Cookies de sessão TikTok | ✅ Existe |
| `data/browser_sessions/tiktok_state.json` | localStorage + origem TikTok | ✅ Existe (dados de analytics/telemetria) |
| `data/credentials/leonidagta6flashbr/tiktok_token.json` | Token OAuth API | ❌ NÃO EXISTE |
| `.env` | `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` | ✅ Configurado |

### Vídeos Prontos para Publicação
- 27 vídeos em `data/autoreel/output/*_br_tiktok.mp4` ✅
- 2 vídeos em `data/exports/*_br_reels_tiktok.mp4` ✅

---

## 4. COMMITS RELEVANTES (TikTok)

| Commit | Descrição |
|--------|-----------|
| `6420330` | FASE 9 — painel TikTok Hybrid Publisher no dashboard + endpoint status |
| `e03643c` | FASE 4 — orquestrador híbrido TikTok (API → Playwright fallback) |
| `6d05c5f` | TikTok Content Posting API v2 — upload real + polling de status |
| `3397c7e` | chore: add TikTok developer site verification file |
| `275e6bf` | feat: páginas Termos de Uso e Política de Privacidade para TikTok Developer Portal |

---

## 5. BLOQUEIOS REAIS

| # | Bloqueio | Impacto | Resolução Necessária |
|---|----------|---------|---------------------|
| 1 | **App TikTok não aprovado para Direct Post** | API retorna `PERMISSION_REQUIRED`; upload via API falha | Aguardar aprovação do TikTok Developer Portal OU usar Playwright como caminho principal |
| 2 | **Sem token OAuth persistido** | `tiktok_token.json` não existe; adapter sempre retorna `AUTH_REQUIRED` | Completar fluxo OAuth uma vez via dashboard ou CLI |
| 3 | **Sessão Playwright pode estar expirada** | Cookies existem mas podem ter sido invalidados pelo TikTok | Validar sessão com `BrowserPublisher.check_session("tiktok")`; se inválida, login manual |
| 4 | **Python 3.14 no .venv** | Ambiente usa Python 3.14; compatibilidade com httpx/playwright deve ser verificada | Rodar testes para confirmar |

---

## 6. PRÓXIMA MISSÃO TIKTOK

### Prioridade Imediata (FASE 4)
1. **Validar sessão Playwright** — executar `check_session("tiktok")` para confirmar se cookies são válidos
2. **Testar fluxo OAuth completo** — gerar auth URL via dashboard, completar autorização, verificar token persistido
3. **Corrigir bug no adapter** — `adapters.py:300` referencia `PublishState.FAILED` mas o enum define `ERROR` (não `FAILED`)
4. **Corrigir campo inexistente** — `adapters.py:313` usa `job.tags` mas `PublishJob` define `hashtags`; `autopublish_scheduler.py:181` usa `job.tags` mas `AutoPublishJob` também define `hashtags`
5. **Teste end-to-end com vídeo real** — usar um dos 27 vídeos em `data/autoreel/output/` para validar upload via Playwright

### Pendente de Autorização Externa
- Aprovação do app TikTok para escopo `video.publish` (Direct Post)
- Validação de domínio no TikTok Developer Portal (arquivo já adicionado, status desconhecido)

### Desenvolvimento Local Possível Sem Aprovação
- Testes unitários do OAuth PKCE flow
- Testes do orquestrador híbrido com mock
- Melhoria do `_publish_tiktok()` no BrowserPublisher (selectors mais robustos)
- Dashboard status panel refinements
- Documentação e logs

---

## 7. ERROS ANTERIORES E SOLUÇÕES TESTADAS

| Erro | Causa | Solução Aplicada |
|------|-------|-----------------|
| `code_challenge` rejeitado | Formato incorreto do hash | Corrigido para SHA-256 + base64url sem padding (`rstrip(b"=")`) |
| `client_key` vs `client_id` | TikTok usa `client_key` no token exchange, não `client_id` | Corrigido em `oauth.py:293` e `oauth.py:475-477` |
| Redirect URI mismatch | URI registrada no portal ≠ URI usada no código | Padronizado para `/api/oauth/callback/tiktok` |
| Token expirado sem refresh | Refresh token não era rotacionado corretamente | Implementado `refresh_token_if_needed()` com buffer de 5 min |

---

*Documento criado na Operação Phoenix — Recuperação Pós-Formatação.*
*Última atualização: 2026-11-20 ~06:30 UTC*