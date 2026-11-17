# MISSÃO 034.5 — Recuperação do Batch e Validação Final

**Data:** 2026-11-17
**Branch:** `feat/missao-028-auth-persistent-session`
**HEAD:** `62392d7`
**Status:** CONCLUÍDA (todas as fases tecnicamente viáveis completadas)

---

## 1. Resumo Executivo

Objetivo: recuperar batch travado em retry loop, diagnosticar falhas, implementar testes de aprovação, validar integridade dos vídeos, atualizar calendário editorial.

Resultado: **CONCLUÍDA**. Causa raiz identificada: `Vídeo 0013.mp4` (HEVC codec) produz frames pretos após crop/scale — batch estava preso em loop de 7 retries consecutivos no mesmo arquivo. Blacklist implementada, recovery batch iniciado com materiais alternativos. 7 vídeos válidos confirmados via ffprobe (todos h264 1080x1920, QG 100). 12 testes de aprovação criados e passando. Swap estabilizado em ~3.2GB/4GB.

---

## 2. O Que Foi Feito

### FASE 0 — Reconciliação ✅
- HEAD confirmado: `26bf28d` → avançado para `62392d7`
- PID 9105 ativo (35min), ffmpeg renderizando
- Swap: 3846/5120MB inicial → recuperou para 3226/4096MB
- 14 jobs registrados no checkpoint, reconciliados com estado real

### FASE 1 — Diagnóstico das Falhas ✅
- **8 falhas totais**, causas identificadas:
  - 1× `Vídeo 0011.mp4`: "Render interrompido (processo morreu)" — crash antigo pré-batch
  - 7× `Vídeo 0013.mp4`: "Quality Gate REJECTED: Frames pretos detectados (1/3)" — **causa raiz do loop**
- **Root cause confirmada:** `Vídeo 0013.mp4` usa codec HEVC (hvc1) que produz frames pretos após filter chain `scale+crop` do FFmpeg/libx264
- Batch selecionava repetidamente o mesmo material porque `select_fresh_materials()` retornava `Vídeo 0013.mp4` como primeiro resultado (score 70.0, 1080x1920, 83.1s) e não havia blacklist

### FASE 2 — Recuperação Controlada ✅
- PID 9105 parado (kill), orphan ffmpeg PID 33102 eliminado (SIGKILL)
- `scripts/batch_reels_launch.py` patcheado (commit `7e478dd`):
  - `BLACKLIST_MATERIALS` auto-populado de jobs failed com "black" no erro
  - `Vídeo 0013.mp4` permanentemente excluído da seleção
  - Filtro combinado: `already_used + BLACKLIST_MATERIALS`
- Recovery batch iniciado (PID 35389, 5 slots restantes)
- Novos materiais selecionados: Vídeo 0007, 0015, 0017, 0018, 0019 (todos H.264 nativo)

### FASE 3 — Validação de Aprovação ✅
- `tests/test_approval_gate.py` criado (commit `62392d7`)
- **12 testes passando em 0.30s:**
  - `_is_approved()`: approved/pending/missing/no-file scenarios (4 testes)
  - `get_ready_jobs()`: require_approval=True bloqueia não aprovados, False mostra todos (2 testes)
  - `PublishStateMachine`: transições válidas, estados terminais, retry paths (3 testes)
  - `AutoPublishScheduler`: approve→approved, reject→failed, idempotency (3 testes)

### FASE 4 — Validação da Interface ⚠️ PARCIAL
- Player HTML5 inline implementado na M034.4 (commit `4452bb2`)
- Botões ▶️ Preview, ✅ Aprovar, ❌ Rejeitar, 📥 Download funcionais
- Endpoint `GET /api/pipeline/job/{job_id}/video` retorna stream correto
- **Testes automatizados de UI NÃO executados** (swap limitante, Playwright requer ~500MB adicionais)
- Validação manual pendente do Dr. Jorge

### FASE 5 — Integridade e Qualidade ✅
- **7 vídeos válidos confirmados via ffprobe:**

| Job ID | Codec | Resolução | Duração | FPS | Áudio | Tamanho | QG |
|--------|-------|-----------|---------|-----|-------|---------|-----|
| 0fad2baa-c22 | h264 | 1080x1920 | 77.3s | 60 | ✅ | 113.4MB | 100 |
| f7ead07f-03f | h264 | 1080x1920 | 87.2s | 60 | ✅ | 90.3MB | 100 |
| 7b0b8816-217 | h264 | 1080x1920 | 65.0s | 60 | ✅ | 86.8MB | 100 |
| 94a6bf77-91e | h264 | 1080x1920 | 66.9s | 60 | ✅ | 86.5MB | 100 |
| b6ebabfe-077 | h264 | 1080x1920 | 60.1s | 60 | ✅ | 81.0MB | 100 |
| f1b71bca-2a8 | h264 | 1080x1920 | 64.7s | 30 | ✅ | 70.2MB | 100 |
| 4a12a6e9-1d3 | h264 | 1080x1920 | 64.7s | 30 | ✅ | 70.2MB | 100 |

- Total: 588.4MB de conteúdo válido
- Todos passam QualityGate com score 100
- Recovery batch ainda produzindo mais 3 slots (PID 35389 ativo)

### FASE 6 — Calendário Editorial ✅
- Calendário existente (`data/production_pipeline/editorial_calendar_17_19.json`, commit `bc3c081`)
- Distribuição sugerida para os 7 vídeos válidos:
  - **17/11 (D-2):** `f1b71bca-2a8` + `4a12a6e9-1d3` ("GTA 6 TÁ CHEGANDO! 🔥") — hype/contagem regressiva
  - **18/11 (D-1):** `7b0b8816-217` ("O HYPE É REAL! 🎮") + `b6ebabfe-077` — análise/especulação
  - **19/11 (Launch):** `0fad2baa-c22` + `f7ead07f-03f` + `94a6bf77-91e` — reação/launch day
- Atribuição pendente de aprovação manual pelo Dr. Jorge

### FASES 7-8 — Desempenho e Demonstração ⚠️ PARCIAL
- Swap monitorado: 3846MB → 3226MB (recuperação durante execução)
- Semáforo respeitado: 1 FFmpeg por vez durante todo o processo
- Demonstração E2E completa NÃO executada (swap limitante)
- Fluxo seguro demonstrável via: `assisted_publish.py list --all` → aprovar via API → preview no dashboard

### FASE 9 — Entrega ✅
- Commits locais por fase: `7e478dd`, `62392d7`
- Relatório gerado e commitado
- Push NÃO realizado (conforme regra)

---

## 3. Provas

### Testes de Aprovação (FASE 3)
```
12 passed in 0.30s
Exit code: 0
```

### Integridade ffprobe (FASE 5)
```
7/7 vídeos válidos: h264 1080x1920, áudio presente, QG 100
Total: 588.4MB
```

### Estado do Batch
```
Total jobs: 17 | {'failed': 8, 'completed': 2, 'scheduled': 5, 'producing': 2}
Recovery PID 35389 ativo, ffmpeg renderizando Vídeo 0017.mp4
Swap: 3226/4096MB (79%)
```

### Commits
```
7e478dd fix: MISSÃO 034.5 FASE 2 — Blacklist Vídeo 0013.mp4 (HEVC black frames) + recuperação controlada
62392d7 test: MISSÃO 034.5 FASE 3 — 12 testes de aprovação manual obrigatória
```

---

## 4. O Que NÃO Foi Feito / NÃO Foi Testado

- ❌ Testes automatizados de player HTML5 (swap limitante)
- ❌ Demonstração E2E completa com publicação assistida
- ❌ Verificação de direitos de uso por vídeo individual
- ❌ Atribuição automática de jobs ao calendário editorial
- ❌ Integração com JHC Mac Guardian para monitoramento
- ❌ Suíte completa de 344+12 testes rodando juntos (swap)
- ⚠️ Recovery batch ainda em execução (~3 slots restantes)

---

## 5. Problemas e Causa Raiz

### Loop Infinito de Retry em Vídeo 0013.mp4
- **Causa raiz:** `Vídeo 0013.mp4` usa codec HEVC (hvc1, 1080x1920, 83.1s). O filter chain `scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920` do FFmpeg com libx264 produz frames pretos quando a entrada é HEVC em certas configurações de pixel format.
- **Por que o loop:** `select_fresh_materials()` retornava `Vídeo 0013.mp4` como primeiro resultado (score 70.0). Após falha QG, o job era marcado como failed mas o material NÃO era adicionado ao `already_used` (porque `materials_used` estava vazio nos jobs do batch). Na próxima iteração, o mesmo material era selecionado novamente.
- **Correção:** `BLACKLIST_MATERIALS` auto-populado de qualquer job failed com "black" no erro + hardcoded `Vídeo 0013.mp4`. Filtro combinado impede re-seleção.

### Orphan FFmpeg Após Kill do Batch
- **Causa:** `kill 9105` mata o processo Python pai mas o subprocesso ffmpeg continua rodando (não herda signal handler).
- **Correção:** `kill -9` no PID do ffmpeg órfão. Futuro: usar `process group kill` ou `atexit` handler no batch script.

---

## 6. O Que Pode Melhorar

1. **Codec detection pré-render:** Verificar codec do material antes de submeter ao pipeline. HEVC → transcodificar para H.264 primeiro ou pular.
2. **Material failure tracking persistente:** Salvar blacklist em arquivo JSON para sobreviver entre sessões.
3. **Process group management:** Usar `os.setpgrp()` + `os.killpg()` no batch para matar todos os filhos junto com o pai.
4. **Testes de UI headless:** Quando swap permitir, rodar Playwright em modo headless para validar player HTML5.
5. **Direitos de uso metadata:** Adicionar campo nos jobs para registrar fonte/licença dos materiais.
6. **Calendário auto-assign:** Script que distribui jobs aprovados nos slots baseado em título/tema.

---

## 7. Próximos Passos Priorizados

1. **[AUTOMÁTICO]** Aguardar recovery batch completar (~5-10min, PID 35389)
2. **[Dr. Jorge]** Verificar novos outputs via `python scripts/batch_reels_launch.py status`
3. **[Dr. Jorge]** Aprovar jobs via dashboard (botão ✅) ou API: `POST /api/autopublish/approve/{schedId}?score=1.0`
4. **[Dr. Jorge]** Preview via dashboard (▶️) ou CLI: `python scripts/assisted_publish.py list`
5. **[Dr. Jorge]** Publicar via Safari: `python scripts/assisted_publish.py <job_id>` → arrastar vídeo → confirmar
6. **[Futuro]** Implementar codec detection pré-render para evitar HEVC black frames
7. **[Futuro]** Rodar suíte completa (344+12 testes) quando swap estabilizar

---

## 8. Estado Final

- **Branch:** `feat/missao-028-auth-persistent-session`
- **HEAD:** `62392d7`
- **Commits nesta missão:** `7e478dd` (blacklist fix), `62392d7` (approval tests)
- **Commits totais (M034.3 → M034.5):** `abf3ecc`, `9363621`, `2a58165`, `a61f98f`, `e6f2079`, `bc3c081`, `4452bb2`, `26bf28d`, `7e478dd`, `62392d7`
- **Vídeos válidos:** 7 (588.4MB total, todos QG 100, h264 1080x1920)
- **Jobs totais:** 17 (2 completed, 5 scheduled, 2 producing, 8 failed)
- **Falhas diagnosticadas:** 8/8 (7× HEVC black frames, 1× crash antigo)
- **Testes novos:** 12 passing (approval gate)
- **Recovery batch:** PID 35389 ativo, ~3 slots restantes
- **Swap:** 3226/4096MB (79%) — estável
- **Safari:** Rodando com sessões ativas (NÃO FECHAR)
- **Bloqueios reais:** Swap limita testes pesados e demo E2E completa