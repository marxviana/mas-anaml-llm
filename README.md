# mas-anaml-llm — Sistemas Multiagentes normativos com LLMs

Pacote Python `llm-mas` (comando `llm-mas`).

Implementação em Python do projeto **"Engenharia de Software de Sistemas Multiagentes
para Tecnologias Emergentes"** (LES/PUC-Rio × Computer Systems Group/University of
Waterloo — Chamada MCTI/CNPq nº 14/2023).

| Fonte | O que vira código |
|---|---|
| Nascimento, Alencar & Cowan, *Self-Adaptive LLM-Based Multiagent Systems* (arXiv:2307.06187) | `core/` — agente com laço MAPE-K em que o LLM encapsula Analyze/Plan/Knowledge; formato `\begin{action}…\end{action}`; memória local (trabalho futuro do artigo); cenário `marketplace` |
| Viana et al., *ANA-ML 2.0* (rascunho IEEE Access) | `norms/` — Norm Knowledge Base, LLM-NormProcessor, LLM-NormValidator, LLM-NormRecommender, LLM-NormAuditor, Norm Adaptation Engine, supervisão humana; cenário `icu` |
| Proposta CNPq, Tema 1 (seções 6.1 e 10.1) | interpretação de normas em linguagem natural, adaptação, monitoramento/execução, sanções |
| Proposta CNPq, Tema 2 (seções 6.2 e 10.2) | cenário `project` — geração de cenários, contextos dinâmicos, apoio à decisão do gerente |

## Arquitetura

```
src/llm_mas/
├── core/            Agent (MAPE-K), LLMAgent, Knowledge, Environment, Simulation
├── llm/             LLM-Interface: ClaudeLLM (API do Claude), FunctionLLM (testes), parser de ações
├── norms/
│   ├── condition.py       linguagem de condições serializável ($parâmetro, @campo)
│   ├── norm.py            Norm (obrigação/proibição/permissão, escopo, persistência, sanção)
│   ├── knowledge_base.py  Norm Knowledge Base versionada + histórico de mudanças
│   ├── monitor.py         execução: proibições, obrigações com prazo, sanções/recompensas
│   ├── llm_components.py  Recommender, Validator, Auditor, NormProcessor
│   └── adaptation.py      Norm Adaptation Engine + supervisores humanos
├── scenarios/
│   ├── marketplace.py     compra e venda de livros (arXiv:2307.06187) com normas
│   ├── icu.py             monitoramento de UTI com normas adaptativas (ANA-ML 2.0)
│   └── project.py         gestão de projetos com contextos dinâmicos (Tema 2)
└── cli.py
```

Ciclo de cada iteração: o ambiente evolui → mensagens da iteração anterior são entregues →
todos os agentes executam Monitor → Analyze/Plan (LLM) sobre o mesmo estado (em paralelo
quando usam LLM) → as ações são aplicadas juntas (Execute) → o monitor verifica proibições e
obrigações e aplica sanções (que entram na memória do agente) → o motor de adaptação pode
refinar normas: **Recommender → Validator → supervisor humano → base de normas**.

Três decisões de projeto importantes:

* **O resultado não depende da ordem de registro dos agentes** (verificado em
  `tests/test_order_invariance.py`). As rodadas são síncronas, mensagens da mesma rodada chegam
  em ordem canônica embaralhada pela semente (a posição na caixa de entrada — e no prompt do
  LLM — não favorece nenhum remetente), cada agente tem seu próprio gerador aleatório, e
  disputas por recursos seguem regra explícita (marketplace: vale o pedido `Buy_Book` mais
  antigo; empates por sorteio da semente).

* **As restrições de segurança são determinísticas.** O LLM-NormValidator pode reprovar uma
  proposta, mas nunca aprovar uma que viole um limite; normas marcadas como não adaptáveis
  (ex.: `ICU-CRITICAL`, SpO2 < 85%) não mudam.
* **Todo componente LLM tem um equivalente offline** (política heurística ou regra), o que
  permite rodar sem API, testar de forma determinística e comparar *com* × *sem* LLM.

## Instalação

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,llm]'
```

Para usar o Claude, crie uma chave em <https://platform.claude.com> (Settings → API Keys) e
grave-a no arquivo `.env` da pasta do projeto (lido automaticamente; está no `.gitignore`):

```bash
cp .env.example .env    # depois edite: ANTHROPIC_API_KEY=sk-ant-...
chmod 600 .env
```

## Comparação sem LLM × com LLM

Antes de gastar, simule o experimento inteiro e veja chamadas e custo estimados
(nenhuma chamada à API):

```bash
.venv/bin/llm-mas compare-llm --llm claude --llm-decision --effort low --dry-run
```

Falhas pontuais da API não descartam a execução: o componente usa a política offline
naquela iteração e a falha é contada no relatório (`falhas do LLM`). Só o fim do orçamento
(`--max-cost`) ou dos créditos interrompe tudo, preservando os resultados parciais.

```bash
.venv/bin/llm-mas compare-llm --llm claude --max-cost 10
.venv/bin/llm-mas compare-llm --llm claude --scenarios marketplace --reps 1   # teste barato
```

Roda os três cenários nas mesmas sementes com e sem LLM e grava em `results/<data-hora>/`:
`report.md` (tabelas com média ± desvio), `results.json` (dados completos, salvos a cada
cenário) e `transcripts.jsonl` (todos os prompts e respostas do LLM, para auditoria e
reprodutibilidade). `--max-cost` interrompe a execução quando o custo estimado atinge o
limite, preservando os resultados parciais. Na UTI, o LLM atua só nos componentes
normativos (a variável em estudo); `--llm-decision` também o coloca no agente de decisão,
o que aumenta muito o número de chamadas.

## Uso

```bash
# Marketplace do artigo (3 vendedores, 2 compradores, 3 iterações)
.venv/bin/llm-mas marketplace
.venv/bin/llm-mas marketplace --llm claude --no-norms     # como no experimento original

# UTI: normas estáticas × adaptativas nas mesmas sementes (teste t pareado)
.venv/bin/llm-mas icu --compare --seeds 0 1 2 3 4
.venv/bin/llm-mas icu --human                            # especialista aprova cada adaptação
.venv/bin/llm-mas icu --llm claude --effort low --iterations 60

# Gestão de projetos: gerente adaptativo × plano estático
.venv/bin/llm-mas project
.venv/bin/llm-mas project --static
.venv/bin/llm-mas project --llm claude --brief "App mobile, equipe de 5, prazo de 3 meses"

# Interpretar uma norma em linguagem natural (LLM-NormProcessor)
.venv/bin/llm-mas interpret "Vendedores não podem confirmar vendas acima de 100 reais" \
    --llm claude --vocabulary "ações: send(command, price, receiver); papéis: seller, buyer"

.venv/bin/pytest
```

`--json arquivo.json` salva métricas e normas finais em qualquer comando.

**Custo com `--llm claude`:** cada agente LLM chama a API a cada iteração (no marketplace,
5 agentes × 3 iterações = 15 chamadas; na UTI, o agente de decisão chama a cada iteração com
alarmes e o recomendador a cada `--adapt-every` iterações). O modelo padrão é
`claude-opus-5-5`; `--effort low` reduz custo e latência. O *fallback* no servidor fica
habilitado: se o modelo recusar uma solicitação, a API a repete em outro modelo.

## Resultados do modo offline (para referência, não para publicação)

`llm-mas icu --compare --seeds 0 1 2 3 4` (12 pacientes, 120 iterações, dados sintéticos):

| semente | alarmes falsos (estático → adaptativo) | sensibilidade | latência média (it.) |
|---|---|---|---|
| 0 | 231 → 74 | 1.0 → 1.0 | 2.0 → 3.0 |
| 1 | 206 → 70 | 1.0 → 1.0 | 1.57 → 2.29 |
| 2 | 215 → 78 | 1.0 → 1.0 | 1.8 → 1.2 |
| 3 | 187 → 57 | 1.0 → 1.0 | 1.0 → 1.5 |
| 4 | 212 → 68 | 1.0 → 1.0 | 1.14 → 2.14 |

Agente de decisão com o escore NEWS2 modificado (padrão). Redução média de 140,8 alarmes
falsos (t pareado = 30,48; gl = 4), sem perda de sensibilidade; com rótulos perfeitos
(`--decision oracle`, só referência) a redução seria de 157,2 — a diferença é o custo dos
vereditos errados que chegam à adaptação. A latência (iteração da primeira leitura que
gerou alarme − início do episódio) **aumenta em 4 de 5 sementes** (média 1,50 → 2,03), consequência da
persistência de 2 leituras e dos limiares por paciente. Esse custo precisa constar de
qualquer análise: o rascunho do ANA-ML 2.0 afirma melhoria de 15–20% no tempo de
resposta, e esta simulação não reproduz essa afirmação. Os números acima vêm da política heurística offline; os
experimentos do artigo devem ser refeitos com `--llm claude`.

### Evidências imperfeitas na decisão sobre alarmes (`scenarios/icu_evidence.py`)

O agente de decisão não vê o estado oculto do paciente. Recebe a leitura que disparou o
alarme, a tendência das últimas leituras, o diagnóstico de base e achados à beira-leito
sorteados com sensibilidade e especificidade parciais (dispneia, sudorese, consciência,
perfusão, queixa, qualidade do sinal do oxímetro), incluindo achados basais de doenças
crônicas. O desfecho real só é confirmado `confirm_delay` (30) iterações depois; até lá, a
adaptação das normas usa o veredito do agente, com seus erros.

* **Linha de base offline:** escore NEWS2 (com a escala 2 de SpO2 para DPOC) + 1 ponto por
  achado − 2 com indício de artefato; alarme real se ≥ 5. Não conhece o modelo gerador.
* **Teto:** classificador bayesiano que conhece o modelo gerador, avaliado nos mesmos
  alarmes (≈ 0,98 de acurácia, contra ≈ 0,80 do NEWS2) — referência, nunca política.
* **Métricas da decisão:** acurácia, sensibilidade e especificidade dos vereditos;
  episódios reconhecidos (alarme real julgado real) e sua latência; rótulos errados usados
  nas revisões de normas.

> **Aviso:** o cenário de UTI usa dados sintéticos e limiares ilustrativos. É um
> instrumento de pesquisa em engenharia de SMA, não um sistema de apoio clínico.

## Fase 2: cumprir ou violar normas (`llm-mas deliberation`)

O agente de alarmes da UTI decide, a cada obrigação, se cumpre ou viola a norma (processo
normativo do ANA: Collect → Analyze → Decision → Effector), com fiscalização imperfeita
(probabilidade de detecção p ∈ {0,3; 0,7; 1,0}) e escala de sanção. Estratégias do JSAN
(social, rebellious, selfish, pressured, opportunistic) e deliberação por LLM são
implementações intercambiáveis do mesmo *hotspot* NormDeliberation. A norma `ICU-CRITICAL`
é regimentada (não pode ser violada).

```bash
.venv/bin/llm-mas deliberation --out results/phase2-offline                     # sem custo
.venv/bin/llm-mas deliberation --llm claude --effort low --dry-run              # estimativa
.venv/bin/llm-mas deliberation --llm claude --effort low --out results/phase2-llm --max-cost 16
```

## Artigo (`paper/`)

Os resultados usados no artigo estão versionados: `results/v3` (Estudo 1),
`results/phase2-offline`, `results/phase2-llm` e `results/phase2-llm-s2p1` (Estudo 2, com as
transcrições completas do LLM). Tudo abaixo roda sem chamar a API:

```bash
.venv/bin/pip install matplotlib reportlab
.venv/bin/python paper/build_paper.py     # prévia em PDF → paper/paper.pdf
.venv/bin/python paper/build_tex.py       # LaTeX IEEE Access → paper/latex/ e ieee-access-latex.zip
.venv/bin/python paper/justifications.py  # análise das justificativas do LLM
```

`paper/justifications.py` reexecuta cada simulação respondendo aos prompts com as saídas
gravadas (replay) e confere que as métricas coincidem com as registradas. O `main.tex` é
gerado: edite `paper/build_paper.py`, não o `.tex`. Para compilar, use a classe
`ieeeaccess` do template da revista (não incluída aqui).

## Como estender

* **Novo cenário:** subclasse de `Environment` (sobrescreva `update`, `apply`, `facts`,
  `metrics` e, se houver adaptação, `adaptation_evidence`) + agentes (`Agent` ou `LLMAgent`
  com `heuristic` para o modo offline).
* **Novas normas:** `Norm(..., target=Condition.all(...), activation=..., parameters=...)`;
  ou gere a partir de texto com `LLMNormProcessor.interpret`.
* **Outro provedor de LLM:** qualquer classe com `generate(system, prompt)` e
  `generate_json(system, prompt, schema)` satisfaz `LLMClient`.
