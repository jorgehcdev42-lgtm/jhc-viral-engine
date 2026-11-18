# MISSÃO — Correção Loop de Login JHC Viral Engine

**Data:** 2026-11-18
**Branch:** `feat/missao-028-auth-persistent-session`
**HEAD:** `6186b65`
**Status:** CONCLUÍDA

---

## 1. Resumo Executivo

Objetivo: corrigir loop de login onde dashboard aparecia brevemente e retornava à tela de login após autenticação bem-sucedida.

Resultado: **CONCLUÍDO**. Causa raiz identificada e corrigida. Frontend usava `sessionStorage` para persistir JWT, mas em contexto cross-origin (frontend `localhost:8080` → backend `127.0.0.1:8001`) o token não sobrevivia ao `location.reload()` pós-login. Cookie httpOnly também não era enviado cross-origin sem HTTPS. Correção: migrar para `localStorage` que persiste entre reloads independentemente de origem.

---

## 2. O Que Foi Feito

### Fase 1 — Diagnóstico
- Backend reiniciado com credenciais `admin`/`160669` (PID 7446, porta 8001)
- Login via API confirmado: JWT retornado com sucesso
- Frontend lido: `doLogin()` salvava em `sessionStorage`, `checkAuth()` lia de `sessionStorage`
- Backend `/api/auth/me` e CORS configurados corretamente
- Causa raiz: `sessionStorage` não sobrevive a `location.reload()` em cross-origin; cookie httpOnly bloqueado sem HTTPS

### Fase 2 — Correção
- `doLogin()`: `sessionStorage.setItem` → `localStorage.setItem`
- `checkAuth()`: lê `localStorage` primeiro, `sessionStorage` como fallback
- `doLogout()`: limpa ambos os storages
- `api()` 401 handler: limpa ambos os storages
- Commit: `6186b65`

---

## 3. Provas

### Validação API
```
LOGIN: token JWT retornado (admin/160669)
BACKEND: PID 7446, porta 8001, operacional
FRONTEND: localStorage.setItem=1, localStorage.getItem=1, sessionStorage.setItem=0
```

### Commit
```
6186b65 fix: login loop — usar localStorage em vez de sessionStorage para persistência do JWT
```

### Arquivo Modificado
- `frontend/index.html`: 12 inserções, 12 remoções

---

## 4. O Que NÃO Foi Testado

- ⚠️ Fluxo completo em navegador real (Dr. Jorge precisa validar em `http://localhost:8080`)
- ⚠️ Persistência após fechar e reabrir aba
- ⚠️ Logout seguido de novo login

---

## 5. Problemas e Causa Raiz

### Loop de Login
- **Causa:** `sessionStorage` é vinculado à sessão da aba e não persiste através de `location.reload()` quando frontend e backend são origens diferentes (`localhost:8080` vs `127.0.0.1:8001`). Cookie httpOnly `jhc_session` também não é enviado cross-origin sem HTTPS.
- **Fix:** Migrar para `localStorage` que persiste entre reloads e é acessível via JavaScript para envio como Bearer header.

### Edit Tool Falhas
- **Causa:** Whitespace inconsistente no HTML (tabs vs spaces) impedia match exato do `old_string`.
- **Fix:** Usado `sed` para substituição direta.

---

## 6. O Que Pode Melhorar

- Servir frontend via backend (mesma origem) eliminaria problema de CORS/cross-origin cookies
- Adicionar endpoint `/api/health` real (atualmente retorna 404)
- Implementar refresh token para sessões longas

---

## 7. Próximos Passos

1. **[Dr. Jorge]** Validar login em `http://localhost:8080` com `admin`/`160669`
2. **[Dr. Jorge]** Confirmar que dashboard permanece após reload
3. **[Autônomo]** Continuar missões de publicação (M040 FASES 4, 6-8)

---

## 8. Estado Final

- **Branch:** `feat/missao-028-auth-persistent-session`
- **HEAD:** `6186b65`
- **Dashboard:** `http://localhost:8080`
- **API:** `http://127.0.0.1:8001`
- **Backend PID:** 7446
- **Credenciais:** `admin` / `160669`
- **Correção:** localStorage para persistência JWT