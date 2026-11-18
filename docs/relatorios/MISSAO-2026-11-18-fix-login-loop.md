# MISSÃO — Correção Loop de Login JHC Viral Engine

**Data:** 2026-11-18
**Branch:** `feat/missao-028-auth-persistent-session`
**HEAD:** `a215ea4`
**Status:** CONCLUÍDA

---

## 1. Resumo Executivo

Objetivo: corrigir loop de login onde dashboard aparecia brevemente e retornava à tela de login após autenticação bem-sucedida.

Resultado: **CONCLUÍDO**. Duas causas raiz identificadas e corrigidas:
1. Frontend usava `sessionStorage` (não sobrevive a reload cross-origin) → migrado para `localStorage`.
2. Backend gerava JWT secret efêmero a cada restart (`secrets.token_hex`) → tokens antigos invalidados. Fixado secret estável em dev.

---

## 2. O Que Foi Feito

### Fase 1 — Diagnóstico
- Backend reiniciado com credenciais `admin`/`160669` (PID 34434, porta 8001)
- Login via API confirmado: JWT retornado com sucesso
- Frontend lido: `doLogin()` salvava em `sessionStorage`, `checkAuth()` lia de `sessionStorage`
- Backend `/api/auth/me` e CORS configurados corretamente
- `get_jwt_secret()` gerava secret efêmero quando `JHC_JWT_SECRET` não definido

### Fase 2 — Correção Frontend
- `doLogin()`: `sessionStorage.setItem` → `localStorage.setItem`
- `checkAuth()`: lê `localStorage` primeiro, `sessionStorage` como fallback
- `doLogout()`: limpa ambos os storages
- `api()` 401 handler: limpa ambos os storages
- Commit: `6186b65`

### Fase 3 — Correção Backend JWT Secret
- `get_jwt_secret()`: fallback para secret fixo `jhc-viral-engine-dev-secret-key-2026-fixed` em dev
- Em production, `JHC_JWT_SECRET` deve ser definido via env var
- Backend reiniciado com secret fixo
- Commit: `a215ea4`

### Fase 4 — Validação
- Login OK, token_len=167
- `/api/auth/me` OK, user=admin, role=owner
- `/api/profiles` OK, count=9 (API autenticada funciona)
- Simulação de reload: mesmo token valida corretamente

---

## 3. Provas

### Validação API
```
LOGIN: OK token_len=167
ME: OK user=admin role=owner
PROFILES: OK count=9
RELOAD_SIM: OK user=admin
```

### Commits
```
a215ea4 fix: JWT secret estável em dev — tokens sobrevivem a restart do backend
6186b65 fix: login loop — usar localStorage em vez de sessionStorage para persistência do JWT
b2e6a37 docs: relatório missão fix login loop — localStorage persistência JWT
```

### Arquivos Modificados
- `frontend/index.html`: 12 inserções, 12 remoções (localStorage)
- `src/api/auth.py`: 8 inserções, 3 remoções (JWT secret fixo)

---

## 4. O Que NÃO Foi Testado

- ⚠️ Fluxo completo em navegador real (Dr. Jorge precisa validar em `http://localhost:8080`)
- ⚠️ Persistência após fechar e reabrir aba
- ⚠️ Logout seguido de novo login
- ⚠️ Token expiry (24h)

---

## 5. Problemas e Causa Raiz

### Loop de Login — Causa 1: sessionStorage
- **Causa:** `sessionStorage` é vinculado à sessão da aba e não persiste através de `location.reload()` quando frontend e backend são origens diferentes (`localhost:8080` vs `127.0.0.1:8001`). Cookie httpOnly `jhc_session` também não é enviado cross-origin sem HTTPS.
- **Fix:** Migrar para `localStorage` que persiste entre reloads e é acessível via JavaScript para envio como Bearer header.

### Loop de Login — Causa 2: JWT Secret Efêmero
- **Causa:** `get_jwt_secret()` gerava `secrets.token_hex(32)` quando `JHC_JWT_SECRET` e `JHC_API_KEY` não definidos. Cada restart do backend invalidava todos os tokens existentes no localStorage.
- **Fix:** Fallback para secret fixo em dev. Em production, `JHC_JWT_SECRET` deve ser definido via env var.

### Edit Tool Falhas
- **Causa:** Whitespace inconsistente no HTML (tabs vs spaces) impedia match exato do `old_string`.
- **Fix:** Usado `sed` para substituição direta.

---

## 6. O Que Pode Melhorar

- Servir frontend via backend (mesma origem) eliminaria problema de CORS/cross-origin cookies
- Adicionar endpoint `/api/health` real (atualmente retorna 404)
- Implementar refresh token para sessões longas
- Mover JWT secret para arquivo `.env` versionado como `.env.example`

---

## 7. Próximos Passos

1. **[Dr. Jorge]** Validar login em `http://localhost:8080` com `admin`/`160669`
2. **[Dr. Jorge]** Confirmar que dashboard permanece após reload
3. **[Autônomo]** Continuar missões de publicação (M040 FASES 4, 6-8)

---

## 8. Estado Final

- **Branch:** `feat/missao-028-auth-persistent-session`
- **HEAD:** `a215ea4`
- **Dashboard:** `http://localhost:8080`
- **API:** `http://127.0.0.1:8001`
- **Backend PID:** 34434
- **Credenciais:** `admin` / `160669`
- **JWT Secret:** fixo em dev (`jhc-viral-engine-dev-secret-key-2026-fixed`)
- **Correções:** localStorage para persistência JWT + JWT secret estável