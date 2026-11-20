# JHC VIRAL ENGINE — CENTRAL DE COMANDO (OPERAÇÃO PHOENIX)

**Data de Recuperação:** 2026-11-20
**Branch Ativa:** `feat/missao-028-auth-persistent-session`
**HEAD:** `64203306739d272b84edeefe3f28b0edd86c6c48`
**Status:** CONTEXTO RECUPERADO — PRONTO PARA CONTINUIDADE

---

## 1. HISTÓRICO ORIGINAL DA CENTRAL DE COMANDO

O JHC VIRAL ENGINE é uma plataforma de automação de conteúdo multi-perfil focada em Instagram Reels, expandida para YouTube Shorts e TikTok. O projeto opera sob o canal **Leonida GTA VI Flash BR** (`@LeonidagtaVIFlashBR` no YouTube, `@leonidagta6flashbr` no Instagram).

### Objetivos Originais
- Automação completa do fluxo: pesquisa → roteiro → produção → publicação
- Publicação multiplataforma (YouTube, Instagram, TikTok) a partir de um único pipeline
- Operação 24/7 via workers persistentes (launchd no macOS)
- Estratégia híbrida: API oficial como primária, Playwright como fallback
- Custo zero: preferência por soluções gratuitas e open-source
- Acervo inteligente: importação, deduplicação e seleção automática de vídeos

### Sessões Utilizadas na Recuperação
| Sessão | ID | Conteúdo |
|--------|-----|----------|
| Principal Viral Engine | `b8a6d591-a3d8-4edf-bc6e-1545e3133138` | Engine core, arquitetura geral |
| GTA-6 YT+IG+TT | `0ba2376f-faa1-41e4-8019-0bfd49c6cffc` | Integração completa 3 plataformas |
| GTA-6 IG+TT | `067260fc-e9b2-4b59-92c5-d98b3e7c6043` | Foco Instagram + TikTok |
| GTA-6 IG focus | `94a2f9dc-544f-4186-8750-769e06bc1eb4` | Foco Instagram |
| GTA-6 setup | `c2a13616-087a-4996-a59b-da8e3c06d572` | Setup inicial / YouTube |

### Documentos de Referência
- Índice Phoenix: `~/.claude/JHC-PHOENIX-INDICE-RECUPERACAO.md`
- Relatório Noturno: `~/.claude/JHC-PHOENIX-RELATORIO-NOTURNO.md`
- Relatórios de Missão: `docs/relatorios/` (49 relatórios)

---

## 2. ESTADO REAL DO REPOSITÓRIO

### Git
- **Branch:** `feat/missao-028-auth-persistent-session`
- **HEAD:** `6420330` — feat: FASE 9 — painel TikTok Hybrid Publisher no dashboard + endpoint status
- **Commits recentes:** 10 commits desde `3397c7e` até `6420330`
- **Arquivos modificados (working tree):**
  - `data/gta6/research/news_store.json` (dados)
  - `data/scheduler/daily_stats.json` (dados)
  - `data/scheduler/publish_queue.json` (dados)
  - `pyproject.toml` (dependências — pillow adicionado)
- **Arquivos não rastreados relevantes:**
  - `data/publishing/` (dados de publicação)
  - `docs/relatorios/MISSAO-2026-11-19-*.md` (3 relatórios recentes)
  - `uv.lock` (lockfile do uv)
  - `.claude/settings.json`, `.claude/proven-config.json` (config local)

### Ambiente Python
- **Requisito:** `requires-python = ">=3.11"` no pyproject.toml
- **Sistema:** macOS tem apenas Python 3.9.6 (`/usr/bin/python3`)
- **Python 3.11+:** NÃO INSTALADO no sistema
- **Venv:** NÃO EXISTE no diretório do projeto
- **Gerenciador:** `uv` (detectado via pyproject.toml e uv.lock)
- **Última suíte conhecida:** 367 passed, 1 skipped, 0 failed (via `uv run pytest`)

⚠️ **BLOQUEIO CRÍTICO:** Python 3.11+ precisa ser instalado para executar testes e desenvolver.

---

## 3. ARQUITETURA E MÓDULOS EXISTENTES

### Estrutura de Diretórios (`src/`)
```
src/
├── analytics/          # Métricas e analytics
│   └── metrics.py
├── api/                # Backend FastAPI
│   ├── auth.py         # Autenticação JWT
│   └── main.py         # Endpoints API + dashboard proxy
├── automation/         # Automação e scheduling
│   ├── autopublish_scheduler.py  # Orquestrador híbrido TikTok
│   ├── media_director.py         # Diretor de mídia
│   └── scheduler.py              # Scheduler geral
├── core/               # Core engine
│   ├── engine.py       # Motor principal
│   ├── profile_config.py  # Configuração de perfis
│   └── storage.py      # Armazenamento persistente
├── editorial/          # Seleção editorial
│   └── topic_selector.py
├── media/              # Gestão de mídias
│   ├── auth_session.py      # Sessões autenticadas
│   ├── catalog_bridge.py    # Ponte catálogo
│   ├── library.py           # Biblioteca de mídias
│   ├── pack_bulk_importer.py # Importação em lote
│   ├── smart_clipper.py     # Cortes inteligentes
│   ├── social_importer.py   # Importador social
│   ├── ssd_library.py       # Biblioteca SSD
│   ├── url_importer.py      # Importador URL
│   └── video_selector.py    # Seletor de vídeos
├── production/         # Produção de conteúdo (19 módulos)
│   ├── auto_reel.py, reel_templates.py, story_studio.py
│   ├── scene_composer.py, dynamic_scene_engine.py
│   ├── scriptwriter.py, narrator.py, subtitle_generator.py
│   ├── thumbnail_engine.py, thumbnail_factory.py, thumbnail_generator.py
│   ├── quality_gate.py, quality_gate_v2.py
│   ├── renderer.py, multiformat_exporter.py
│   ├── visual_identity.py, watermark.py
│   └── pipeline.py, smart_catalog.py, dual_market.py
├── publishing/         # Publicação multiplataforma
│   ├── adapters.py            # Adapters YT/IG/TikTok (API)
│   ├── auto_publisher.py      # Auto-publisher YouTube
│   ├── browser_publisher.py   # Playwright fallback (Missão 019)
│   ├── instagram_publisher.py # Publisher Instagram
│   ├── oauth.py               # OAuth flows (YT/IG/TikTok)
│   └── publish_state_machine.py # Máquina de estados
├── research/           # Pesquisa e tendências
│   ├── advanced_analyzer.py, trend_hunter.py
│   ├── instagram_radar.py, youtube_radar.py
│   ├── reference_lab.py, rss_source.py
└── skills/             # Skills reutilizáveis
```

### Testes (`tests/`)
19 arquivos de teste cobrindo: approval gate, auth session, autoreel quality, branding e2e, bulk worker persistence, dynamic scene engine, e2e missions, HEVC transcode, media director, pipeline, quality gate v2, reel templates, research integration, scene composer, scriptwriter, smart media library, topic selector, video selector.

### Frontend
- **Netlify:** Site ID `a7d67a60...`, deployado
- **Backend Proxy:** `/api/*` → Render via netlify.toml redirects
- **Dashboard HTML:** `frontend/index.html` com painéis YouTube, TikTok, Contas Conectadas

---

## 4. MISSÕES CONCLUÍDAS (COMPROVADAS)

| Missão | Data | Status | Evidência |
|--------|------|--------|-----------|
| 002 — Op Vice City Launch | 2026-11-13 | ✅ Concluída | Relatório + commits |
| 003 — Operação Viral Prime | 2026-11-13 | ✅ Concluída | Relatório + commits |
| 004 — Visual Revolution | 2026-11-13 | ✅ Concluída | Relatório + commits |
| 006 — Ultimate Launch | 2026-11-14 | ✅ Concluída | Relatório + commits |
| 007 — Dual Market Delivery | 2026-11-14 | ✅ Concluída | Relatório + commits |
| 019 — Browser Publisher | 2026-11-18 | ✅ Concluída | Base reutilizada na Missão 020; `browser_publisher.py` funcional |
| 020 — TikTok Hybrid Publisher | 2026-11-19 | ⚠️ Parcial | FASE 0-4, 7, 9 completas; FASE 10-11 pendentes autorização |
| 024 — AutoReel Dual Market | 2026-11-15 | ✅ Concluída | 3 relatórios |
| 025 — Cinematic Quality | 2026-11-15 | ✅ Concluída | Relatório |
| 026 — Operação Acervo Infinito | 2026-11-15 | ✅ Concluída | Relatório |
| 028 — Importação Real AutoReel | 2026-11-16 | ✅ Concluída | 2 relatórios |
| 029 — Proteção Acervo Automação | 2026-11-16 | ✅ Concluída | Relatório |
| 030 — Homologação Industrial Importação | 2026-11-16 | ✅ Concluída | Relatório |
| 031 — Importação Autônoma Acervo | 2026-11-16 | ✅ Concluída | Relatório |
| 032 — Acervo Inteligente | 2026-11-16 | ✅ Concluída | Relatório + estabilização |
| 033 — Fábrica AutoReels | 2026-11-16 | ✅ Concluída | Relatório |
| 034 — Fábrica Autônoma (8 fases) | 2026-11-17 | ✅ Concluída | 8 relatórios |
| 040 — Fases 1-3 | 2026-11-17 | ✅ Concluída | Relatório |
| 041 — Operação Leonida Final | 2026-11-18 | ✅ Concluída | 2 relatórios |
| YT-002 — YouTube 24/7 | 2026-11-19 | ⚠️ Parcial | Worker launchd ativo, 2 vídeos publicados; OAuth modo Teste |
| Auth Auditoria + Testes | 2026-11-19 | ✅ Concluída | 367/367 testes verdes |

---

## 5. MISSÕES PENDENTES

| Prioridade | Missão / Tarefa | Bloqueio | Ação Necessária |
|------------|-----------------|----------|-----------------|
| 🔴 CRÍTICA | Instalar Python 3.11+ | Sistema tem 3.9.6 | Instalar via .pkg oficial ou brew |
| 🔴 CRÍTICA | Recriar venv do projeto | Sem Python 3.11+ | `uv sync --extra dev` após instalação |
| 🟡 ALTA | TikTok OAuth Token | Sem token válido | Completar fluxo OAuth no dashboard |
| 🟡 ALTA | TikTok App Review | App não aprovado | Verificar/submeter no Developer Portal |
| 🟡 ALTA | YouTube OAuth → Produção | Modo Teste (expira 7 dias) | Promover app no Google Cloud Console |
| 🟢 MÉDIA | Instagram API calls reais | TODOs em adapters.py:170,189 | Implementar chamadas Graph API |
| 🟢 MÉDIA | YouTube resumable upload real | TODO em adapters.py:227 | Implementar upload resumable |
| 🟢 MÉDIA | Painel YouTube no frontend HTML | Endpoint pronto, HTML pendente | Adicionar componente ao index.html |
| 🟢 BAIXA | Corrigir warnings depreciação | Pillow getdata, FastAPI on_event | Higiene de código |
| 🟢 BAIXA | Integrar YT worker ao AutoPublishScheduler | Worker independente | Unificar filas |

---

## 6. SITUAÇÃO DA MISSÃO 019 — BROWSER PUBLISHER

**Estado:** ✅ CONCLUÍDA

- `src/publishing/browser_publisher.py` implementado e funcional
- Método `_publish_tiktok()` reutilizado como fallback na Missão 020
- Cookies e state do TikTok preservados em `data/browser_sessions/`
- Contrato `PublishRequest`/`PublishResult` compartilhado entre adapters e browser publisher
- Playwright instalado no venv (chromium-1255)
- Sessão browser existente: 9 cookies em `tiktok_cookies.json`

**Integração com Missão 020:** O orquestrador híbrido (`execute_tiktok_hybrid`) usa `BrowserPublisher._publish_tiktok()` como fallback quando a API retorna `PERMISSION_REQUIRED` ou quando não há token OAuth.

---

## 7. ESTADO DAS INTEGRAÇÕES

### YouTube
| Item | Estado | Detalhe |
|------|--------|---------|
| Canal | ✅ Ativo | `UCQZkEbFYWN2ReXeH-ZZvQEA` (Leonida GTA VI Flash BR) |
| OAuth | ⚠️ Modo Teste | Token válido, refresh funcional; expira em 7 dias sem promoção |
| Auto-Publisher Worker | ✅ Ativo | launchd PID 72583, single instance |
| Vídeos Publicados | ✅ 2 verificados | `ETZhPqKoCYc`, `orqNYcbvSuE` (ambos public/processed) |
| Fila Pendente | ✅ 19 vídeos | Elegíveis para Shorts |
| Dashboard API | ✅ Funcional | `/api/youtube/auto-publish/status`, pause, resume |
| Resumable Upload Real | ❌ TODO | `adapters.py:227` — stub apenas |

### Instagram / Meta
| Item | Estado | Detalhe |
|------|--------|---------|
| OAuth Token Exchange | ✅ Implementado | `oauth.py` funcional |
| Adapter Credential Path | ✅ Corrigido | Commit `3a7b7cb` |
| API Calls Reais | ❌ TODO | `adapters.py:170` (publish), `adapters.py:189` (status check) |
| Instagram Publisher | ⚠️ Stub | `instagram_publisher.py` existe mas depende de API real |
| Página Facebook | ✅ Configurada | Leonida GTA VI Flash BR |
| App Meta JHC VIRAL ENGINE | ✅ Criado | Permissões pendentes de verificação |

### TikTok
| Item | Estado | Detalhe |
|------|--------|---------|
| Content Posting API v2 | ✅ Implementado | Upload real + polling em `adapters.py` |
| Orquestrador Híbrido | ✅ Implementado | `execute_tiktok_hybrid()` em `autopublish_scheduler.py` |
| OAuth PKCE | ✅ Configurado | `oauth.py` com auth_url, token_url, scopes |
| Client Key/Secret | ✅ No .env | Valor mascarado, requer verificação contra Developer Portal |
| Token OAuth | ❌ Ausente | Sem `tiktok_token.json` em `data/credentials/` |
| App Review | ❌ Não submetido | Pendente ação no Developer Portal |
| Playwright Fallback | ✅ Integrado | `BrowserPublisher._publish_tiktok()` + cookies existentes |
| Dashboard Painel | ✅ Funcional | Border #00f2ea, endpoint `/api/tiktok/auto-publish/status` |
| Vídeos Elegíveis | ✅ 27 | 1080x1920 vertical, h264, AAC, 60-90s |

---

## 8. COORDENAÇÃO DOS QUATRO CHATS

### Responsabilidades
| Chat | Escopo | Arquivos Principais |
|------|--------|-------------------|
| **CENTRAL DE COMANDO** (este) | Arquitetura, pipeline, dashboard, gestão de projetos, coordenação | `src/core/`, `src/api/main.py`, `frontend/`, `docs/` |
| **YOUTUBE** | Canal, OAuth Google, Data API, Studio, Auto-Publisher Worker | `src/publishing/auto_publisher.py`, `src/api/auth.py`, launchd plist |
| **INSTAGRAM / META** | Instagram, Facebook, App Meta, Graph API, Reels | `src/publishing/instagram_publisher.py`, `src/publishing/oauth.py` |
| **TIKTOK** | OAuth PKCE, Content Posting API, Playwright, Hybrid Publisher | `src/publishing/adapters.py`, `src/automation/autopublish_scheduler.py`, `src/publishing/browser_publisher.py` |

### Interfaces Compartilhadas
- `src/publishing/adapters.py` — Contrato `PublishRequest`/`PublishResult` usado por todos
- `src/publishing/oauth.py` — Fluxos OAuth compartilhados
- `data/credentials/` — Tokens e credenciais (gitignorado)
- `data/browser_sessions/` — Cookies e state do Playwright
- `data/scheduler/` — Filas e stats compartilhados
- `frontend/index.html` — Dashboard unificado

### Riscos de Edição Concorrente
- `src/publishing/adapters.py` — Usado por YT, IG e TT simultaneamente
- `src/api/main.py` — Endpoints de todas as plataformas
- `frontend/index.html` — Painéis de todas as plataformas
- `data/scheduler/publish_queue.json` — Fila compartilhada

### Estratégia de Sincronização
1. Cada chat trabalha em sua branch específica quando possível
2. Commits atômicos por funcionalidade
3. Documentar mudanças em `docs/relatorios/`
4. Este chat (Central) resolve conflitos de integração
5. Nunca sobrescrever mudanças de outro chat sem verificar

---

## 9. BLOQUEIOS QUE EXIGEM INTERVENÇÃO HUMANA

| # | Bloqueio | Impacto | Ação do Dr. Jorge |
|---|----------|---------|-------------------|
| 1 | Python 3.11+ não instalado | Testes e desenvolvimento bloqueados | Autorizar instalação via .pkg ou brew |
| 2 | TikTok OAuth token ausente | API não funciona | Completar fluxo OAuth no dashboard |
| 3 | TikTok App não aprovado | API rejeita requisições | Verificar/submeter App Review |
| 4 | YouTube OAuth modo Teste | Token expira em 7 dias | Promover app para Produção no Google Cloud |
| 5 | Instagram API calls não implementadas | Publicação IG não funciona | Autorizar implementação (chat especializado) |
| 6 | Publicação real TikTok não autorizada | Não pode testar upload real | Autorizar explicitamente teste |
| 7 | Playwright cookies possivelmente expirados | Fallback browser pode falhar | Login manual via Playwright se necessário |

---

## 10. PRÓXIMA MISSÃO RECOMENDADA

### Missão 042 — Desbloqueio do Ambiente de Desenvolvimento

**Objetivo:** Restaurar capacidade plena de execução de testes e desenvolvimento.

**Passos:**
1. Instalar Python 3.12 via installer oficial ou brew
2. Recriar venv com `uv sync --extra dev`
3. Executar suíte completa (`uv run pytest tests/ -v`)
4. Verificar se todos os 367+ testes ainda passam
5. Commit de validação do ambiente

**Depois:** Prosseguir com implementação dos TODOs em `adapters.py` (Instagram API real e YouTube resumable upload) nos chats especializados.

---

## 11. REGRAS ABSOLUTAS (PRESERVADAS)

- ⛔ **JARVIS PERMANECE DESATIVADO** — nenhum serviço, agente ou automação
- ⛔ Não apagar históricos, backups ou arquivos originais
- ⛔ Não alterar credenciais funcionais da 8Token
- ⛔ Não criar novos agentes permanentes sem autorização
- ⛔ Não contratar APIs, GPUs ou serviços pagos
- ⛔ Não fazer push ou force-push sem autorização
- ⛔ Não restaurar LaunchAgents antigos automaticamente
- ⛔ Não executar vários builds/servidores simultaneamente (8GB RAM)

---

*Documento gerado pela Operação Phoenix — Recuperação Integral do Contexto.*
*Este chat substitui operacionalmente a antiga conversa da Central de Comando.*
*Última atualização: 2026-11-20*