# Relatório GitHub Intelligence — JHC Viral Engine

**Data:** 2026-11-13
**Status:** PESQUISA CONCLUÍDA / INTEGRAÇÃO PARCIAL
**Autor:** Claude Fable 5.2

---

## 1. Resumo Executivo

Pesquisa técnica aprofundada no ecossistema open source para identificar ferramentas que acelerem o desenvolvimento do JHC Viral Engine. Foco em: legendas automáticas, detecção de cenas, edição de vídeo, publicação Instagram e trend analysis.

**Resultado principal:** Nenhuma ferramenta substitui o pipeline customizado já construído, mas **faster-whisper + PySceneDetect** são integrações TIER S que eliminam os dois maiores gaps técnicos do MVP (legendas proporcionais e smart clipping).

---

## 2. Matriz Comparativa de Ferramentas

### TIER S — ESSENCIAIS (integração imediata recomendada)

| Ferramenta | Repositório | Funcionalidade | Licença | Compatibilidade M2 | Benefício Concreto |
|-----------|-------------|----------------|---------|-------------------|-------------------|
| **faster-whisper** | [Infinity242/faster-whisper](https://github.com/Infinity242/faster-whisper) | ASR com CTranslate2, 4x mais rápido que Whisper original, word-level timestamps | MIT | ✅ Apple Silicon via CTranslate2 | Substitui timing proporcional por legendas precisas sincronizadas com áudio real |
| **WhisperX** | [m-bain/whisperX](https://github.com/m-bain/whisperX) | Forced-alignment para word-level timestamps + speaker diarization | BSD-4 | ✅ Suporta MPS | Legendas com precisão de palavra individual + identificação de falantes |
| **SubsAI** | [GHLuckM4n/SubsAI](https://github.com/GHLuckM4n/SubsAI) | Wrapper unificado: faster-whisper + whisper-timestamped + WhisperX via Web-UI/CLI/API | GPL-3.0 | ✅ Python puro + backends | Abstração que permite trocar backend ASR sem mudar código |
| **PySceneDetect** | [breakthrough/pyscenedetect](https://github.com/breakthrough/pyscenedetect) | Detecção de cortes (ContentDetector, AdaptiveDetector, ThresholdDetector), splitting automático | BSD-3 | ✅ FFmpeg backend | Smart clipper para identificar melhores trechos de vídeos longos automaticamente |

### TIER A — RECOMENDADAS (próxima fase)

| Ferramenta | Repositório | Funcionalidade | Licença | Notas |
|-----------|-------------|----------------|---------|-------|
| **MoviePy** | [Zulko/moviepy](https://github.com/Zulko/moviepy) | Edição programática de vídeo em Python (cortes, concatenação, efeitos) | MIT | Complemento ao FFmpeg wrapper; API mais pythonica para manipulação não-linear |
| **Remotion** | [remotion-dev/remotion](https://github.com/remotion-dev/remotion) | Renderização de vídeo via React components | BSL-1.1 | Templates visuais ricos para Reels; requer Node.js; bom para overlays animados |
| **OpenMontage** | N/A (referenciado em searches) | Sistema agentic de produção de vídeo com 12 pipelines e 100+ tools | Open Source | Candidato a orquestrador complementar; avaliar maturidade antes de adotar |
| **whisper-timestamped** | [linto-ai/whisper-timestamped](https://github.com/linto-ai/whisper-timestamped) | Dynamic Time Warping em cross-attention weights para timestamps sem modelo extra | AGPL-3.0 | Alternativa leve ao WhisperX quando diarização não é necessária |
| **pytrends** | [GeneralMills/pytrends](https://github.com/GeneralMills/pytrends) | Google Trends unofficial API | Apache-2.0 | Trend discovery automatizado; risco de rate limit/bloqueio |

### TIER B — EXPERIMENTAIS (validação futura)

| Ferramenta | Categoria | Notas |
|-----------|-----------|-------|
| **Windrecorder** | Screen recording + OCR search | Útil para capturar gameplay próprio; não aplicável a conteúdo de terceiros |
| **OmniShorts** | RAG-powered short-form content search | Busca semântica em vídeos curtos; interessante para análise competitiva |
| **VidiVideo / VideoQ** | Semantic video access (acadêmico) | Pesquisa acadêmica; não production-ready |

### DESCARTADAS

| Ferramenta | Motivo |
|-----------|--------|
| SDKs Instagram third-party | Nenhum SDK open source confiável encontrado; API Graph v27.0 direta via httpx é mais segura e mantida |
| OpenShot Video Editor | Editor interativo GUI; não aplicável a pipeline automatizado headless |
| Instagram Search Scraper | Apenas scraping de metadados públicos; não publica conteúdo |
| laive-sdk / python-kraken-sdk / dropbox-sdk | Irrelevantes para o escopo |

---

## 3. Análise Técnica Detalhada

### 3.1 Legendas Automáticas (Gap Crítico #1)

**Problema atual:** `SubtitleGenerator` usa timing proporcional (chars/sec estimado). Dessincroniza em textos longos, pausas naturais, variações de velocidade de fala.

**Solução recomendada:** faster-whisper → WhisperX pipeline

```python
# Integração proposta (pseudocódigo)
from faster_whisper import WhisperModel
import whisperx

model = WhisperModel("large-v3", device="cpu", compute_type="int8")  # M2 friendly
segments, info = model.transcribe(audio_path, language="pt", word_timestamps=True)

# Alinhamento forçado para precisão de palavra
align_model, metadata = whisperx.load_align_model(language_code="pt", device="cpu")
result = whisperx.align(segments, align_model, metadata, audio_path, device="cpu")

# Output: word-level timestamps precisos → SRT/VTT sincronizado
```

**Consumo estimado M2 8GB:** Modelo `large-v3` int8 ~4GB RAM. Modelo `medium` ~2GB. Recomendado iniciar com `medium` para validar, migrar para `large-v3` se qualidade insuficiente.

**Licença:** faster-whisper (MIT) + WhisperX (BSD-4) = compatível com uso comercial.

### 3.2 Smart Clipping (Gap Crítico #2)

**Problema atual:** Sem detecção automática de cenas. Pipeline assume clips pré-cortados ou usa vídeo inteiro.

**Solução recomendada:** PySceneDetect ContentDetector

```python
from scenedetect import detect, ContentDetector

scene_list = detect(video_path, ContentDetector(threshold=27.0))
# Retorna lista de (start_timecode, end_timecode) para cada cena detectada
# Usar para extrair melhores trechos via FFmpeg -ss/-to
```

**Integração com pipeline:** Adicionar estágio `SMART_CLIP` entre `MEDIA_PREP` e `EDITING`. PySceneDetect identifica cortes → seleciona N melhores cenas por duração/relevância → passa clips cortados para transições.

### 3.3 Publicação Instagram

**Conclusão da pesquisa:** Não existe SDK Python open source maduro e mantido para Instagram Content Publishing API em 2025. Todos os resultados foram scrapers, SDKs irrelevantes ou projetos abandonados.

**Decisão correta mantida:** Implementação HTTP direta via httpx em `src/publishing/instagram_publisher.py` usando Graph API v27.0. Mais segura, sem dependência de terceiros, alinhada com docs oficiais Meta.

### 3.4 Trend Analysis

**Conclusão da pesquisa:** Ferramentas específicas para trend analysis de redes sociais são escassas no ecossistema open source. A maioria é SaaS pago (Brandwatch, Sprout Social, Hootsuite).

**Recomendação pragmática:** Construir motor próprio com:
1. RSS parser (`feedparser`) para Rockstar Newswire + blogs de games
2. YouTube Data API v3 (free tier: 10k units/dia) para trending videos
3. `pytrends` para Google Trends correlacionado (com fallback se bloqueado)
4. Reddit API (via `praw`) para r/GTAVI, r/GrandTheftAuto

Custo: zero (APIs gratuitas dentro dos limites). Complexidade: média. Valor: alto (dados reais vs placeholder).

---

## 4. Skills Recomendadas para Claude Code

Baseado nas responsabilidades identificadas na missão GitHub Intelligence:

| Skill Proposta | Prioridade | Justificativa | Implementação |
|---------------|-----------|---------------|---------------|
| `subtitle-specialist` | P0 | Integra faster-whisper + WhisperX no pipeline | Adapter em `src/production/subtitle_generator.py` |
| `smart-video-editor` | P1 | Integra PySceneDetect para auto-clipping | Novo módulo `src/production/smart_clipper.py` |
| `gta6-trend-hunter` | P1 | Motor de pesquisa real com RSS + YouTube + Reddit | Expansão de `src/research/trend_hunter.py` |
| `reels-scriptwriter` | P2 | LLM integration para roteiros originais | Adapter para Claude API / Ollama local |
| `instagram-publisher` | P2 | Já implementado; skill documentaria fluxo OAuth | Documentação + testes de integração |
| `fact-checking-agent` | P3 | Verificação factual automatizada | Futuro; depende de knowledge base |
| `voiceover-director` | P3 | Seleção inteligente de voz/TTS params | Expansão do Narrator |
| `social-media-analytics` | P4 | Coleta métricas pós-publicação | Depende de Instagram credentials |
| `viral-content-strategist` | P4 | Análise de padrões virais | Futuro; depende de dataset histórico |
| `copyright-asset-auditor` | P5 | Verificação de licença de mídia | Futuro; complexo e baixo ROI inicial |
| `marvel-news-researcher` | P5 | Variação do trend hunter para Marvel/DC | Configuração de perfil, não skill nova |
| `content-quality-reviewer` | P5 | Quality gate automatizado | Futuro; heurísticas de vídeo/áudio |

**Nota:** Skills devem ser leves e sob demanda. Nenhuma deve criar agente residente permanente sem autorização explícita.

---

## 5. Arquitetura de Integração

```
JHC VIRAL ENGINE
├── src/core/              ← Motor central compartilhado (existente)
│   ├── engine.py          ← Orquestrador 12 estágios
│   └── profile_config.py  ← Config multiperfil
├── src/research/          ← Motor de pesquisa
│   ├── trend_hunter.py    ← Expandir com feedparser + yt-dlp + praw
│   └── sources/           ← NOVO: adapters por fonte (RSS, YouTube, Reddit)
├── src/production/        ← Fábrica de Reels
│   ├── scriptwriter.py    ← Integrar LLM (Claude/Ollama)
│   ├── narrator.py        ← macOS say (atual) → ElevenLabs/Azure (futuro)
│   ├── subtitle_generator.py ← SUBSTITUIR por faster-whisper adapter
│   ├── smart_clipper.py   ← NOVO: PySceneDetect integration
│   └── renderer.py        ← FFmpeg (existente) + MoviePy (futuro)
├── src/publishing/        ← Publicação
│   └── instagram_publisher.py ← HTTP direto (existente, correto)
└── src/analytics/         ← Métricas (futuro)
```

**Princípio:** Cada ferramenta externa entra como adapter isolado. Core engine nunca importa diretamente faster-whisper/PySceneDetect/etc. Isso permite trocar backend sem quebrar pipeline.

---

## 6. Ferramentas Efetivamente Integradas

| Ferramenta | Status | Commit | Testes |
|-----------|--------|--------|--------|
| FFmpeg (via subprocess) | ✅ Integrado | `ea04fed` | Renderer cria MP4 válido |
| macOS TTS `say` | ✅ Integrado | `ea04fed` | Narrator gera WAV |
| httpx (Instagram API) | ✅ Integrado | `ea04fed` | Publisher tem estrutura completa |
| faster-whisper | ❌ Pendente | — | Requer instalação + adapter |
| PySceneDetect | ❌ Pendente | — | Requer instalação + módulo novo |
| feedparser | ❌ Pendente | — | Requer instalação + source adapter |
| LLM (Claude/Ollama) | ❌ Pendente | — | Requer credencial ou setup local |

---

## 7. Dependências Externas Pendentes

| Dependência | Tipo | Bloqueia | Ação Necessária |
|------------|------|----------|----------------|
| faster-whisper | pip package | Legendas precisas | `pip install faster-whisper` + adapter |
| PySceneDetect | pip package | Smart clipping | `pip install scenedetect[opencv]` + módulo |
| YouTube Data API key | Credencial | Trend discovery real | Criar projeto Google Cloud → habilitar API |
| Instagram Business Account | Credencial | Publicação automática | Configurar via Meta Business Suite |
| Claude API key ou Ollama | Credencial/Setup | Roteiros originais | Obter key ou instalar Ollama local |
| feedparser | pip package | RSS parsing | `pip install feedparser` |
| praw | pip package | Reddit integration | `pip install praw` + criar app Reddit |

---

## 8. Commits Locais

| Hash | Descrição | Arquivos |
|------|-----------|----------|
| `20a521a` | Init project | README.md |
| `ea04fed` | Multi-profile MVP with GTA 6 pipeline | 19 files, 1424 lines |
| `051508f` | Mission report | docs/relatorios/MISSAO-2026-11-13-viral-engine-mvp.md |

---

## 9. Documentação de Manutenção

### Adicionando nova ferramenta ao pipeline

1. Criar adapter em `src/production/` ou `src/research/` isolando a dependência externa
2. Adapter deve implementar protocolo/interface definida pelo core (não expor API da lib diretamente)
3. Adicionar testes unitários mockando a dependência externa
4. Atualizar `pyproject.toml` com nova dependência
5. Documentar neste relatório seção 6
6. Commit separado com prefixo `feat:` ou `refactor:`

### Trocando backend ASR

1. Implementar novo adapter seguindo mesma interface de `SubtitleGenerator`
2. Adicionar config em `ProfileConfig` para selecionar backend (`proportional`, `whisper`, `whisperx`)
3. Engine seleciona adapter baseado na config do perfil
4. Manter adapter antigo como fallback

### Monitorando saúde das dependências

- Verificar mensalmente se faster-whisper/PySceneDetect têm releases novos
- Monitorar se YouTube Data API quota mudou
- Validar se Instagram Graph API versionou (atual: v27.0)

---

## 10. Conclusão e Recomendações Imediatas

1. **Instalar faster-whisper HOJE** — elimina maior gap técnico do MVP com esforço mínimo
2. **Instalar PySceneDetect SEMANA QUE VEM** — habilita smart clipping para Reels mais dinâmicos
3. **Criar YouTube API key ANTES DE PRODUZIR CONTEÚDO REAL** — sem isso, TrendHunter é placeholder
4. **Manter implementação HTTP direta para Instagram** — nenhum SDK third-party vale o risco
5. **Não adotar Remotion agora** — overkill para MVP; considerar apenas se templates visuais complexos forem necessários
6. **Documentar skills como wrappers leves** — não criar 12 agentes residentes; skills sob demanda via Claude Code

**Prioridade absoluta permanece:** entregar primeiro Reel funcional do GTA 6 com legendas precisas. Tudo o resto é otimização incremental.