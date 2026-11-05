# Comparação: sem LLM × com LLM

Modelo `claude-opus-5-5` (effort `low`): 272 chamadas, 529296 tokens de entrada, 130820 de saída, custo estimado US$ 4.7336.

Valores: média ± desvio padrão sobre as sementes válidas em todos os modos; Δ = média das diferenças pareadas por semente.

## Marketplace (arXiv:2307.06187, com normas)

| métrica | offline | llm | Δ llm − offline |
|---|---|---|---|
| vendas | 1.00 ± 0.00 | 2.00 ± 0.00 | 1.00 ± 0.00 |
| preço médio | 21.00 ± 1.00 | 31.67 ± 1.44 | 10.67 ± 1.76 |
| vendedores sem venda | 2.00 ± 0.00 | 1.00 ± 0.00 | -1.00 ± 0.00 |
| compradores sem livro | 1.00 ± 0.00 | 0.00 ± 0.00 | -1.00 ± 0.00 |
| mensagens | 27.00 ± 0.00 | 37.67 ± 1.53 | 10.67 ± 1.53 |
| mensagens para si mesmo | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| falhas do LLM (usou a política offline) | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| violações MKT-NO-SELF | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| violações MKT-NO-IMPERSONATION | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| violações MKT-CONFIRM-NEEDS-ORDER | 0.00 ± 0.00 | 0.33 ± 0.58 | 0.33 ± 0.58 |

Sementes pareadas: [0, 1, 2] (n = 3).

## UTI (ANA-ML 2.0)

Recomendador: heurístico × LLM. Validador LLM: não; agente de decisão LLM: sim.

Modos: `static` (normas fixas); `adaptive-oracle` (recomendador heurístico + decisão com rótulos perfeitos, só referência); `adaptive-heuristic` (recomendador heurístico + decisão NEWS2); `adaptive-llm` (recomendador LLM + decisão NEWS2); `adaptive-llm-decision` (recomendador heurístico + decisão LLM). Δ em relação a `adaptive-heuristic`.

| métrica | static | adaptive-oracle | adaptive-heuristic | adaptive-llm | adaptive-llm-decision | Δ adaptive-llm − adaptive-heuristic | Δ adaptive-llm-decision − adaptive-heuristic |
|---|---|---|---|---|---|---|---|
| alarmes falsos | 217.33 ± 12.66 | 55.33 ± 8.02 | 74.00 ± 4.00 | 101.00 ± 8.54 | 73.67 ± 3.51 | 27.00 ± 12.53 | -0.33 ± 3.51 |
| taxa de alarmes falsos | 0.90 ± 0.01 | 0.69 ± 0.04 | 0.75 ± 0.03 | 0.80 ± 0.01 | 0.74 ± 0.03 | 0.05 ± 0.01 | -0.00 ± 0.01 |
| sensibilidade (alarme soou) | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| especificidade | 0.84 ± 0.01 | 0.96 ± 0.01 | 0.95 ± 0.00 | 0.93 ± 0.01 | 0.95 ± 0.00 | -0.02 ± 0.01 | 0.00 ± 0.00 |
| latência do alarme (it.) | 1.79 ± 0.22 | 2.16 ± 0.91 | 2.16 ± 0.91 | 1.79 ± 0.54 | 2.16 ± 0.91 | -0.37 ± 0.50 | 0.00 ± 0.00 |
| episódios reconhecidos pela decisão | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| latência do reconhecimento (it.) | 1.79 ± 0.22 | 2.16 ± 0.91 | 2.16 ± 0.91 | 1.79 ± 0.54 | 2.50 ± 0.44 | -0.37 ± 0.50 | 0.33 ± 0.58 |
| acurácia dos vereditos | 0.82 ± 0.02 | 1.00 ± 0.00 | 0.80 ± 0.02 | 0.80 ± 0.01 | 0.81 ± 0.00 | -0.00 ± 0.02 | 0.01 ± 0.02 |
| sensibilidade dos vereditos | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.96 ± 0.08 | 0.00 ± 0.00 | -0.04 ± 0.08 |
| especificidade dos vereditos | 0.80 ± 0.02 | 1.00 ± 0.00 | 0.73 ± 0.03 | 0.75 ± 0.01 | 0.76 ± 0.03 | 0.02 ± 0.03 | 0.03 ± 0.04 |
| ref.: acurácia NEWS2 nos mesmos alarmes | 0.82 ± 0.02 | 0.84 ± 0.03 | 0.80 ± 0.02 | 0.80 ± 0.01 | 0.81 ± 0.03 | -0.00 ± 0.02 | 0.01 ± 0.01 |
| ref.: acurácia do classificador ótimo | 0.99 ± 0.01 | 0.98 ± 0.01 | 0.98 ± 0.01 | 0.98 ± 0.01 | 0.99 ± 0.01 | 0.00 ± 0.01 | 0.00 ± 0.01 |
| rótulos errados usados nas revisões | 0.00 ± 0.00 | 0.00 ± 0.00 | 34.33 ± 7.57 | 38.67 ± 7.57 | 33.33 ± 2.52 | 4.33 ± 7.57 | -1.00 ± 5.20 |
| adaptações aplicadas | 0.00 ± 0.00 | 17.33 ± 0.58 | 16.33 ± 1.15 | 12.67 ± 3.06 | 16.33 ± 1.15 | -3.67 ± 2.31 | 0.00 ± 0.00 |
| rejeitadas pelo validador | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| vereditos assumidos por padrão | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| falhas do LLM (usou a política offline) | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| violações de normas | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |

Sementes pareadas: [0, 1, 2] (n = 3).

### Relatório do LLM-NormAuditor (semente 0)

# Relatório de Auditoria Normativa (LLM-NormAuditor)

## 1. Resumo executivo

O sistema detectou todos os episódios reais (5 de 5, sensibilidade 1,0, latência média 2,4), mas gera alarmes falsos em excesso: 102 de 128 alarmes são falsos (taxa 0,797). As adaptações automáticas foram conservadoras e respeitaram os limites de segurança. Ainda assim, elas se basearam em vereditos que, em grande parte, não estavam confirmados, e há 42 rótulos errados identificados na revisão. Os pontos marcados abaixo pedem verificação humana antes de novas adaptações.

## 2. Eficácia das normas

- **Nenhuma norma registra violação.** Todas as 14 normas têm 0 violações. A estatística por norma mede apenas o disparo (*fulfillment*), não se o disparo foi correto. Por isso ela **não permite avaliar a eficácia individual** de cada norma.
- **Volume de disparos:**
  - ICU-SPO2-LOW (global) domina, com 66 disparos.
  - Seguem ICU-SBP-LOW (19), ICU-RR-HIGH (10), ICU-HR-HIGH (9) e ICU-CRITICAL (6).
  - As normas específicas por paciente somam poucos disparos cada, entre 1 e 8.
- **Soma não bate com o total.** Os disparos somam 137, mas o sistema registra 128 alarmes. A diferença pode vir de alarmes simultâneos de mais de uma norma (por exemplo, ICU-CRITICAL junto com uma norma específica). Convém confirmar como cada contagem é feita.
- **Sensibilidade com amostra pequena.** O valor de 1,0 vem de apenas 5 episódios, o que dá pouca confiança estatística.
- **Especificidade divergente.** A especificidade do sistema é 0,927, mas a dos vereditos é 0,745. Há discrepância entre o que o detector considera correto e o que o classificador de vereditos considera.

## 3. Desalinhamentos encontrados

1. **Adaptações sobre rótulos não confirmados.** Quase todas as justificativas citam vereditos "ainda não confirmados pelo desfecho". Com 42 rótulos errados na revisão, parte dos "alarmes falsos" que motivaram ajustes pode ter sido mal rotulada.

2. **Possível problema no cálculo das métricas.** `verdict_accuracy`, `news_accuracy` e `false_alarm_rate` são todos exatamente 0,797, enquanto `bayes_accuracy` é 0,992. A coincidência dos três valores sugere uma das seguintes causas:
   - erro de cálculo ou de definição das métricas; ou
   - classificadores NEWS e de vereditos degenerados, por exemplo rotulando quase tudo como falso.

   Isso precisa ser verificado, pois os vereditos alimentam as adaptações.

3. **Incoerência na norma global de SpO2.** Nas iterações 60 e 75, alarmes de SpO2 de pacientes com basal normal (P1, P4, P5, P8, P9, P11, P12) estavam rotulados como **falsos**. O auditor automático decidiu tratá-los como **desvios reais** e não ajustou nada. Há duas leituras possíveis:
   - ou os rótulos estão errados, o que reforça o item 1;
   - ou a norma global está gerando falsos que ninguém trata.

   Como essa norma tem o maior volume de disparos (66), é provavelmente a principal fonte da taxa de falsos.

4. **Ajustes de limiar insuficientes, com troca para persistência.** Várias reduções ou aumentos de limiar não eliminaram os falsos: P2, P6 e P10 (SpO2), P7 (FC), P4, P8 e P12 (PAS). A estratégia passou então a ser exigir 2 leituras consecutivas, já adotada em P4, P7, P8, P11 e P12. Essa mudança reduz falsos, mas pode aumentar a latência de detecção nesses pacientes. A latência por paciente não aparece nos dados.

5. **Alegações de sucesso não verificáveis.** As justificativas afirmam, por exemplo, que um ajuste "zerou os alarmes falsos". Os dados agregados fornecidos não permitem confirmar isso.

6. **Norma sem tratamento.** ICU-RR-HIGH tem 10 disparos e nenhuma adaptação. Seus falsos foram considerados isolados, mas não há análise agregada dessa norma.

## 4. Pontos positivos

- Todos os ajustes ficaram dentro dos intervalos de segurança declarados: SpO2 [86, 94], PAS [82, 100], FC [100, 140] e persistência [1, 3].
- ICU-CRITICAL permaneceu ativo com persistência 1 em todos os casos.
- Os ajustes foram graduais, de 1 a 2 pontos.
- Pacientes com alarmes reais receberam tratamento mais conservador.
- Não houve falhas do LLM (`llm_failures` = 0) nem decisões por padrão (`decision_defaults` = 0).

## 5. Recomendações

1. **Validar as métricas:** investigar por que três métricas valem exatamente 0,797 e conferir a soma de disparos (137) contra o total de alarmes (128).
2. **Revisar os 42 rótulos errados** e reavaliar os ajustes que dependeram deles. Considerar a suspensão de novas adaptações até que os vereditos sejam confirmados pelo desfecho.
3. **Atacar a norma global ICU-SPO2-LOW:**
   - decidir, com revisão clínica, se os alarmes em pacientes com basal normal são reais ou falsos;
   - se forem falsos, considerar um critério relativo ao basal ou alguma persistência.
4. **Monitorar a latência por paciente** onde a persistência foi elevada para 2 (P4, P7, P8, P11, P12) e confirmar que eventos reais continuam sendo detectados a tempo.
5. **Ampliar a avaliação da sensibilidade.** Com apenas 5 episódios, ela deve ser revalidada com mais eventos antes de qualquer flexibilização adicional.
6. **Incluir métricas de acerto por norma** (verdadeiros e falsos positivos) nas estatísticas, já que a contagem de violações atual não discrimina eficácia.

## Gestão de projetos (Tema 2)

| métrica | offline | llm | Δ llm − offline |
|---|---|---|---|
| concluiu o projeto (fração) | 1.00 ± 0.00 | 1.00 ± 0.00 | 0.00 ± 0.00 |
| iteração de conclusão (censurada no limite) | 33.00 ± 2.65 | 35.00 ± 1.00 | 2.00 ± 2.00 |
| tarefas concluídas | 25.00 ± 0.00 | 25.00 ± 0.00 | 0.00 ± 0.00 |
| esforço restante | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| falhas do LLM (usou a política offline) | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| violações PM-ASSIGN-BACKLOG | 0.00 ± 0.00 | 0.00 ± 0.00 | 0.00 ± 0.00 |
| violações PM-WIP-LIMIT | 2.00 ± 0.00 | 2.00 ± 0.00 | 0.00 ± 0.00 |

Sementes pareadas: [0, 1, 2] (n = 3).
