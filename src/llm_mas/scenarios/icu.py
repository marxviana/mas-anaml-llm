"""Monitoramento de pacientes em UTI com normas adaptativas (ANA-ML 2.0, Seção V).

Papéis (como no artigo):

* ``MonitoringAgent`` — coleta os sinais vitais (SpO2, FC, PAS, FR) e os publica;
* ``AlertingAgent``   — agente normativo: cumpre as obrigações de alarme abertas
                        pelas normas e notifica a equipe;
* ``DecisionAgent``   — avalia a urgência de cada alarme (com o LLM, a partir do
                        relato de avaliação à beira-leito) e registra se foi real;
* ``LLMNormProcessor`` + ``NormAdaptationEngine`` — refinam as normas de alarme
  por paciente com base nas avaliações, sob limites de segurança e supervisão
  humana. A norma crítica (ex.: SpO2 < 85%) não é adaptável.

A comparação ``baseline`` (normas estáticas) × ``adaptive`` usa a mesma semente,
portanto os mesmos pacientes e as mesmas leituras.

AVISO: os dados são sintéticos e os limiares são ilustrativos — este código é um
instrumento de pesquisa em engenharia de SMA, não um dispositivo clínico.
"""

from __future__ import annotations

import json
import math
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from llm_mas.core.agent import Agent, LLMAgent, Perception
from llm_mas.core.environment import Environment
from llm_mas.core.messages import Action
from llm_mas.core.simulation import Simulation, SimulationResult
from llm_mas.llm.base import LLMClient, LLMError, tolerate
from llm_mas.scenarios.icu_evidence import (
    NEWS_THRESHOLD,
    PROFILE_TEXT,
    bayes_posterior,
    bedside_text,
    classification_stats,
    draw_findings,
    news_score,
)
from llm_mas.norms.strategies import DeliberationCase, NormStrategy, make_strategy
from llm_mas.norms import (
    AutoApprove,
    Condition,
    Deontic,
    HumanSupervisor,
    LLMNormAuditor,
    LLMNormProcessor,
    LLMNormRecommender,
    LLMNormValidator,
    Norm,
    NormAdaptationEngine,
    NormKnowledgeBase,
    NormProposal,
    SafetyBound,
)

VITALS = ("spo2", "hr", "sbp", "rr")

# média e desvio padrão de cada sinal vital, por perfil de paciente
PROFILES: dict[str, dict[str, tuple[float, float]]] = {
    "stable": {"spo2": (97, 1.0), "hr": (78, 6), "sbp": (120, 8), "rr": (16, 2)},
    "copd": {"spo2": (89.5, 1.1), "hr": (88, 6), "sbp": (128, 8), "rr": (21, 1.5)},
    "tachycardic": {"spo2": (96, 1.0), "hr": (116, 4), "sbp": (118, 8), "rr": (18, 2)},
    "low_bp": {"spo2": (96, 1.0), "hr": (84, 6), "sbp": (93, 3), "rr": (17, 2)},
}
# variação por estágio de deterioração clínica
DETERIORATION = {"spo2": -1.6, "hr": 5.0, "sbp": -4.0, "rr": 1.5}

ALARM_NORMS = {  # norma -> (sinal, parâmetro)
    "ICU-SPO2-LOW": ("spo2", "spo2_min"),
    "ICU-HR-HIGH": ("hr", "hr_max"),
    "ICU-SBP-LOW": ("sbp", "sbp_min"),
    "ICU-RR-HIGH": ("rr", "rr_max"),
}

SAFETY_BOUNDS = [
    SafetyBound("ICU-SPO2-LOW", "spo2_min", 86, 94),
    SafetyBound("ICU-HR-HIGH", "hr_max", 100, 140),
    SafetyBound("ICU-SBP-LOW", "sbp_min", 82, 100),
    SafetyBound("ICU-RR-HIGH", "rr_max", 20, 32),
]

DOMAIN_BRIEF = (
    "UTI simulada. Normas de alarme obrigam o AlertingAgent a alarmar quando um sinal vital cruza um "
    "limiar. Alarmes falsos causam fadiga de alarme. Nas evidências, um alarme é contado como falso ou "
    "real pelo veredito do agente de decisão, que pode errar; o desfecho só é confirmado 30 iterações "
    "depois do alarme, quando substitui o veredito. "
    "Refine limiares e persistência (leituras consecutivas) por paciente (scope_field='id') apenas quando "
    "houver alarmes falsos recorrentes atribuídos à norma e o paciente tiver um baseline fisiológico "
    "diferente do populacional. As evidências trazem, por paciente e norma, a versão em vigor, a "
    "iteração da última mudança e os alarmes desde então: use-os para julgar se a última mudança "
    "funcionou antes de propor outra. A norma ICU-CRITICAL não é adaptável e continua valendo para todos. "
    "Limites de segurança: spo2_min ∈ [86, 94], hr_max ∈ [100, 140], sbp_min ∈ [82, 100], "
    "rr_max ∈ [20, 32], persistência ∈ [1, 3]."
)


def icu_norms(sanction_scale: float = 1.0) -> list[Norm]:
    """``sanction_scale`` multiplica a sanção das normas de alarme adaptáveis (fase 2)."""
    alert = Condition.all(("type", "==", "alert"))

    def alarm(norm_id: str, desc: str, var: str, op: str, param: str, value: float) -> Norm:
        return Norm(norm_id, desc, Deontic.OBLIGATION, "alerting", target=alert,
                    activation=Condition.all((var, op, f"${param}")), parameters={param: value},
                    deadline=2, sanction=5 * sanction_scale, reward=1)

    return [
        alarm("ICU-SPO2-LOW", "Alarmar quando SpO2 < spo2_min.", "spo2", "<", "spo2_min", 90),
        alarm("ICU-HR-HIGH", "Alarmar quando FC > hr_max.", "hr", ">", "hr_max", 120),
        alarm("ICU-SBP-LOW", "Alarmar quando PAS < sbp_min.", "sbp", "<", "sbp_min", 90),
        alarm("ICU-RR-HIGH", "Alarmar quando FR > rr_max.", "rr", ">", "rr_max", 25),
        Norm(
            "ICU-CRITICAL", "Alarmar sempre que SpO2 < 85, FC > 150, PAS < 80 ou FR > 35 (não adaptável).",
            Deontic.OBLIGATION, "alerting", target=alert,
            activation=Condition.any(("spo2", "<", 85), ("hr", ">", 150), ("sbp", "<", 80), ("rr", ">", 35)),
            deadline=2, sanction=20, reward=1, adaptable=False, regimented=True,
        ),
    ]


@dataclass
class Patient:
    id: str
    profile: str
    onset: int | None = None
    duration: int = 10
    readings: list[dict[str, float]] = field(default_factory=list)
    artifacts: list[bool] = field(default_factory=list)

    def in_episode(self, t: int) -> bool:
        return self.onset is not None and self.onset <= t < self.onset + self.duration

    def stage(self, t: int) -> int:
        return t - self.onset + 1 if self.in_episode(t) else 0  # type: ignore[operator]


class ICUEnv(Environment):
    """``confirm_delay``: iterações até o desfecho real de um alarme ser
    confirmado (seguimento clínico). Antes disso, a adaptação de normas só
    dispõe do veredito do agente de decisão, com seus erros."""

    def __init__(self, patients: list[Patient], seed: int | None = None, artifact_rate: float = 0.05,
                 confirm_delay: int = 30) -> None:
        super().__init__("icu", seed)
        self.patients = {p.id: p for p in patients}
        self.artifact_rate = artifact_rate
        self.confirm_delay = confirm_delay
        self.current: dict[str, dict[str, float]] = {}
        self.published: dict[str, dict[str, float]] = {}
        self.alarms: list[dict[str, Any]] = []
        self.feedback: list[dict[str, Any]] = []
        self.deliberations: list[dict[str, Any]] = []  # fase 2: cumprir ou violar cada obrigação
        self.harm_events: list[dict[str, Any]] = []
        self._charged_episodes: set[tuple[str, int | None]] = set()

    # --- elemento gerenciado -------------------------------------------------
    def update(self, iteration: int) -> None:
        self._confirm_outcomes(iteration)
        self.published = {}
        for p in self.patients.values():
            stage = iteration - p.onset + 1 if p.in_episode(iteration) else 0
            reading = {}
            for v in VITALS:
                mean, sd = PROFILES[p.profile][v]
                reading[v] = round(self.rng.gauss(mean + DETERIORATION[v] * stage, sd), 1)
            artifact = self.rng.random() < self.artifact_rate
            if artifact:  # artefato de movimento no oxímetro
                reading["spo2"] = round(self.rng.uniform(85.5, 89.0), 1)
            p.readings.append(reading)
            p.artifacts.append(artifact)
            self.current[p.id] = reading

    def _episode_harmed(self, d: dict[str, Any]) -> bool:
        """Uma supressão de piora real só causa dano se nenhum alarme verdadeiro
        daquele episódio já tinha soado até a leitura suprimida."""
        p = self.patients[d["patient"]]
        return not any(a["patient"] == d["patient"] and a["true"] and p.onset <= a["reading_iteration"]
                       <= d["reading_iteration"] for a in self.alarms)

    def _confirm_outcomes(self, iteration: int) -> None:
        """O desfecho de cada alarme suprimido é confirmado ``confirm_delay``
        iterações depois da leitura (como na fase 1). Se era piora real e a
        supressão atrasou o reconhecimento, cobra-se o dano — uma vez por episódio."""
        agent = self.agents.get("Alerting")
        for d in self.deliberations:
            if d["comply"] or d.get("confirmed") or iteration < d["reading_iteration"] + self.confirm_delay:
                continue
            d["confirmed"] = iteration
            if agent is None or not isinstance(agent, AlertingAgent):
                continue
            if not d["truth"]:
                agent.record["confirmed_false"] += 1
                continue
            agent.record["confirmed_real"] += 1
            episode = (d["patient"], self.patients[d["patient"]].onset)
            if self._episode_harmed(d) and episode not in self._charged_episodes:
                self._charged_episodes.add(episode)
                self.harm_events.append({**d, "discovered": iteration})
                agent.score -= HARM_PENALTY
                text = (f"o alarme de {d['patient']} que você não soou na iteração {d['iteration']} era uma piora "
                        f"real e atrasou o reconhecimento: dano ao paciente, penalidade {HARM_PENALTY:g}")
                agent.record["harms"].append((iteration, text))
                agent.knowledge.remember(iteration, "dano", text)
                self.notify(agent.id, text)

    def alarm(self, patient_id: str, alarm_iteration: int) -> dict[str, Any] | None:
        return next((a for a in self.alarms if a["patient"] == patient_id and a["iteration"] == alarm_iteration),
                    None)

    def _bedside_findings(self, patient_id: str, t: int) -> dict[str, bool]:
        """Avaliação à beira-leito sobre o estado na iteração ``t`` da leitura. O
        sorteio depende só de (semente, paciente, t): o mesmo alarme recebe os
        mesmos achados em todos os modos da comparação."""
        p = self.patients[patient_id]
        rng = random.Random(f"{self.seed}:bedside:{patient_id}:{t}")
        return draw_findings(rng, p.profile, p.stage(t), p.artifacts[t - 1])

    def decision_context(self, alarm: dict[str, Any], trend: int = 6) -> str:
        """O que o agente de decisão sabe sobre um alarme — sem o estado oculto."""
        p = self.patients[alarm["patient"]]
        t = alarm["reading_iteration"]
        history = "\n".join(f"  it {i}: {_fmt(p.readings[i - 1])}" for i in range(max(1, t - trend + 1), t + 1))
        return (
            f"ALERTA {p.id} (diagnóstico de base: {PROFILE_TEXT[p.profile]}) — normas {', '.join(alarm['norms'])}, "
            f"disparado pela leitura da iteração {t}: {_fmt(alarm['trigger_vitals'])}\n"
            f"Leituras recentes (tendência):\n{history}\n"
            f"Avaliação à beira-leito: {bedside_text(alarm['findings'])}"
        )

    def apply(self, action: Action) -> None:
        if action.type == "publish":
            self.published[action.data["subject"]] = action.data["vitals"]
        elif action.type == "alert":
            pid = action.data["subject"]
            # o alarme soa uma iteração depois da leitura; a verdade é julgada pela leitura
            first = min(action.data["triggers"].values(), key=lambda t: t["reading_iteration"])
            reading_it = first["reading_iteration"]
            self.alarms.append({
                "iteration": action.iteration, "reading_iteration": reading_it, "patient": pid,
                "norms": action.data["norms"], "triggers": action.data["triggers"],
                "trigger_vitals": first["vitals"], "findings": self._bedside_findings(pid, reading_it),
                "true": self.patients[pid].in_episode(reading_it), "verdict": None,
            })
        elif action.type == "assess":
            alarm = self.alarm(action.data["subject"], action.data["alarm_iteration"])
            if alarm is not None:
                alarm["verdict"] = action.data["true_alarm"]
                self.feedback.append({**action.data, "iteration": action.iteration,
                                      "norms": alarm["norms"], "triggers": alarm["triggers"]})
        super().apply(action)

    def facts(self) -> list[dict[str, Any]]:
        return [{"id": pid, "profile": self.patients[pid].profile, **v} for pid, v in self.published.items()]

    # --- evidências para a adaptação de normas ------------------------------
    def adaptation_evidence(self) -> dict[str, Any]:
        """Por paciente e por norma geral: a versão em vigor, quando mudou pela
        última vez e os alarmes desde então (o que permite avaliar se a última
        mudança funcionou), além dos totais."""
        assert self.norms is not None
        applied_at = {c.norm_id: c.iteration for c in self.norms.history if c.status == "applied"}
        by_patient: dict[str, dict[str, Any]] = {}
        # rótulo de cada alarme: desfecho confirmado, se já passou o atraso; senão, o veredito
        labels: dict[tuple[str, int], bool] = {}
        wrong = 0
        for f in self.feedback:
            alarm = self.alarm(f["subject"], f["alarm_iteration"])
            assert alarm is not None
            confirmed = self.iteration - alarm["reading_iteration"] >= self.confirm_delay
            label = alarm["true"] if confirmed else f["true_alarm"]
            labels[(f["subject"], f["alarm_iteration"])] = label
            wrong += label != alarm["true"]
        self.state.setdefault("wrong_labels_at_review", []).append(wrong)
        for pid, p in self.patients.items():
            recent = p.readings[-30:]
            norms: dict[str, Any] = {}
            for base_id in ALARM_NORMS:
                current = self.norms.get(f"{base_id}@{pid}") or self.norms.get(base_id)
                assert current is not None
                since = applied_at.get(current.id, 0)
                false_all, true_all, false_since, true_since, false_vitals = 0, 0, 0, 0, []
                for f in self.feedback:
                    if f["subject"] != pid:
                        continue
                    for norm_id, trig in f["triggers"].items():
                        if norm_id.split("@")[0] != base_id:
                            continue
                        recent_alarm = trig["reading_iteration"] > since
                        if labels[(f["subject"], f["alarm_iteration"])]:
                            true_all += 1
                            true_since += recent_alarm
                        else:
                            false_all += 1
                            false_since += recent_alarm
                            if recent_alarm:
                                false_vitals.append(trig["vitals"])
                if false_all or true_all or current.id != base_id:
                    norms[base_id] = {
                        "norm_in_force": current.id, "parameters": current.parameters,
                        "persistence": current.persistence, "last_change_iteration": since or None,
                        "false_alarms_since_change": false_since, "true_alarms_since_change": true_since,
                        "false_alarm_readings_since_change": false_vitals[-5:],
                        "false_alarms_total": false_all, "true_alarms_total": true_all,
                    }
            by_patient[pid] = {
                "profile": p.profile,
                "baseline_median_last_30": {v: round(statistics.median(r[v] for r in recent), 1) for v in VITALS},
                "alarm_norms": norms,
            }
        return {"iteration": self.iteration, "patients": by_patient}

    # --- métricas -------------------------------------------------------------
    def metrics(self) -> dict[str, Any]:
        t_end = self.iteration
        alarms_at = {(a["patient"], a["reading_iteration"]) for a in self.alarms}
        episodes, detected, latencies = 0, 0, []
        negatives = negatives_quiet = 0
        for pid, p in self.patients.items():
            for t in range(1, t_end + 1):
                if not p.in_episode(t):
                    negatives += 1
                    negatives_quiet += (pid, t) not in alarms_at
            if p.onset is not None and p.onset <= t_end:
                episodes += 1
                hits = [a["reading_iteration"] for a in self.alarms if a["patient"] == pid and a["true"]]
                if hits:
                    detected += 1
                    latencies.append(min(hits) - p.onset)
        false_alarms = sum(1 for a in self.alarms if not a["true"])

        # reconhecimento: o episódio só é tratado quando o agente de decisão julga real um alarme dele
        recognized, recog_lat = 0, []
        for pid, p in self.patients.items():
            if p.onset is not None and p.onset <= t_end:
                hits = [a["reading_iteration"] for a in self.alarms
                        if a["patient"] == pid and a["true"] and a["verdict"]]
                if hits:
                    recognized += 1
                    recog_lat.append(min(hits) - p.onset)

        # vereditos do agente de decisão e as duas referências, sobre os mesmos alarmes
        verdicts = classification_stats([(a["verdict"], a["true"]) for a in self.alarms if a["verdict"] is not None])
        news = classification_stats([(news_score(a["trigger_vitals"], self.patients[a["patient"]].profile,
                                                 a["findings"]) >= NEWS_THRESHOLD, a["true"]) for a in self.alarms])
        prior = sum(a["true"] for a in self.alarms) / len(self.alarms) if self.alarms else 0.5
        bayes = classification_stats([(bayes_posterior(
            a["trigger_vitals"], a["findings"], self.patients[a["patient"]].profile, prior,
            self.patients[a["patient"]].duration, self.artifact_rate, PROFILES, DETERIORATION) > 0.5, a["true"])
            for a in self.alarms])
        return {
            "alarms": len(self.alarms),
            "false_alarms": false_alarms,
            "false_alarm_rate": round(false_alarms / len(self.alarms), 3) if self.alarms else 0.0,
            "episodes": episodes,
            "detected": detected,
            "sensitivity": round(detected / episodes, 3) if episodes else None,
            "specificity": round(negatives_quiet / negatives, 3) if negatives else None,
            # latência = iteração da primeira leitura que gerou alarme no episódio − início do episódio
            "mean_latency": round(statistics.mean(latencies), 2) if latencies else None,
            "recognized_sensitivity": round(recognized / episodes, 3) if episodes else None,
            "recognition_latency": round(statistics.mean(recog_lat), 2) if recog_lat else None,
            "verdict_accuracy": verdicts["accuracy"], "verdict_sensitivity": verdicts["sensitivity"],
            "verdict_specificity": verdicts["specificity"],
            "news_accuracy": news["accuracy"], "bayes_accuracy": bayes["accuracy"],
            "wrong_labels_at_review": sum(self.state.get("wrong_labels_at_review", [])),
            "decision_defaults": self.state.get("decision_defaults", 0),
            "llm_failures": self.state.get("llm_failures", 0),
            **self._deliberation_metrics(),
        }

    def _deliberation_metrics(self) -> dict[str, Any]:
        """Fase 2: violações (todas, e só as detectadas), supressões justificadas
        (alarme de fato falso) e danosas (piora real), contribuição social e
        satisfação individual do agente de alerta."""
        dl = self.deliberations
        sup = [d for d in dl if not d["comply"]]
        correct = sum(1 for d in sup if not d["truth"])
        viol = [e for e in (self.monitor.events if self.monitor else []) if e.kind == "violation"]
        real = [d for d in dl if d["truth"]]
        agent = self.agents.get("Alerting")
        return {
            "deliberations": len(dl),
            "suppressions": len(sup),
            "justified_suppressions": correct,
            "harmful_suppressions": len(sup) - correct,
            "suppression_precision": round(correct / len(sup), 3) if sup else None,
            "violations_true": len(viol),
            "violations_detected": sum(1 for e in viol if e.detected),
            "harm_events": len(self.harm_events),
            # episódios em que uma supressão atrasou o reconhecimento (verdade de base, descoberto ou não)
            "harmed_episodes": len({(d["patient"], self.patients[d["patient"]].onset) for d in sup
                                    if d["truth"] and self._episode_harmed(d)}),
            # contribuição social: fração das obrigações sobre pioras reais que foram cumpridas
            "social_contribution": round(sum(d["comply"] for d in real) / len(real), 3) if real else None,
            # satisfação individual: satisfação das ações + recompensas − sanções detectadas − danos
            "individual_satisfaction": round(agent.score + getattr(agent, "satisfaction", 0.0), 1) if agent else None,
            "deliberation_defaults": self.state.get("deliberation_defaults", 0),
        }


# --------------------------------------------------------------------------
# Agentes
# --------------------------------------------------------------------------
class MonitoringAgent(Agent):
    def __init__(self, agent_id: str, patient_ids: list[str]) -> None:
        super().__init__(agent_id, "monitoring")
        self.patient_ids = patient_ids

    def sense(self, iteration: int) -> dict[str, Any]:
        env = self.env
        assert isinstance(env, ICUEnv)
        return {pid: env.current[pid] for pid in self.patient_ids}

    def analyze_and_plan(self, p: Perception) -> list[Action]:
        return [Action(self.id, "publish", {"subject": pid, "vitals": v}) for pid, v in p.sensors.items()]


# --------------------------------------------------------------------------
# Fase 2: deliberação normativa do agente de alerta
# --------------------------------------------------------------------------
GOALS_MOTIVATION = {"segurança do paciente": 10, "evitar fadiga de alarme da equipe": 6}  # AgentGoal.Motivation
SUPPRESS_SATISFACTION = 3.0  # Action.Satisfaction de não soar um alarme julgado falso
HARM_PENALTY = 20.0  # piora real suprimida, sempre descoberta ao fim do episódio

DELIBERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "patient": {"type": "string"},
                    "believes_real": {"type": "boolean"},
                    "comply": {"type": "boolean"},
                    "justification": {"type": "string"},
                },
                "required": ["patient", "believes_real", "comply", "justification"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["decisions"],
    "additionalProperties": False,
}


class AlertingAgent(Agent):
    """Agente normativo responsável pelas obrigações de alarme.

    Sem ``strategy`` nem ``llm`` (fase 1), cumpre todas. Na fase 2 delibera
    uma vez por obrigação nova (NormAwareness → NormDeliberation →
    NormCompliance): soar o alarme (cumprir) ou suprimi-lo (violar). Normas
    regimentadas — a ICU-CRITICAL — são sempre cumpridas. Estratégias e LLM
    recebem a mesma informação: evidências do alarme (as do agente de decisão),
    recompensa, sanção, probabilidade de detecção e seus objetivos.
    """

    SYSTEM = (
        "Você é o agente de alerta de uma UTI simulada, um agente normativo autônomo. Normas o obrigam a soar "
        "um alarme quando um sinal vital cruza um limiar; você pode cumprir (soar) ou violar (não soar) cada "
        "obrigação. Seus objetivos, com a motivação de cada um (0–10): "
        + "; ".join(f"{g} = {m}" for g, m in GOALS_MOTIVATION.items()) + ". "
        f"Não soar um alarme que você julga falso lhe dá satisfação {SUPPRESS_SATISFACTION:g} (menos fadiga da "
        "equipe). Cumprir uma obrigação rende a recompensa indicada; uma violação detectada pela auditoria gera a "
        "sanção indicada. O desfecho de cada alarme que você não soar é confirmado {confirm_delay} iterações depois "
        f"da leitura: se era uma piora real ainda não alarmada, há dano ao paciente e penalidade {HARM_PENALTY:g}. "
        "As evidências são imperfeitas: achados clínicos também "
        "ocorrem em pacientes estáveis e artefatos de movimento produzem leituras falsas de SpO2. Alarmes de "
        "normas críticas são soados automaticamente e não dependem de você. Para cada paciente, informe se "
        "acredita que a piora é real, se cumpre a obrigação e por quê."
    )

    def __init__(self, agent_id: str, decision_agent: str, strategy: Any = None, llm: LLMClient | None = None) -> None:
        super().__init__(agent_id, "alerting")
        self.decision_agent = decision_agent
        self.strategy = strategy
        self.llm = llm
        self.decided: dict[tuple[str, str, int], bool] = {}  # (norma, paciente, abertura) -> cumpre?
        self.satisfaction = 0.0
        # registro normativo permanente (a memória de trabalho é limitada e descarta o que é antigo)
        self.record: dict[str, Any] = {"sanctions": [], "harms": [], "fulfilled": 0, "rewards": 0.0,
                                       "confirmed_false": 0, "confirmed_real": 0}

    def on_norm_event(self, event) -> None:
        super().on_norm_event(event)
        if event.kind == "violation":
            self.record["sanctions"].append((event.iteration, event.norm_id, event.delta))
        else:
            self.record["fulfilled"] += 1
            self.record["rewards"] += event.delta

    @property
    def deliberative(self) -> bool:
        return self.strategy is not None or self.llm is not None

    def analyze_and_plan(self, p: Perception) -> list[Action]:
        env = self.env
        assert isinstance(env, ICUEnv) and env.monitor is not None
        pending = env.monitor.pending_for(self)
        if self.deliberative:
            self._deliberate(p.iteration, pending)
            pending = [ob for ob in pending if self.decided.get((ob.norm.id, ob.subject, ob.opened), True)]
        triggers: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for ob in pending:
            triggers[ob.subject][ob.norm.id] = {"reading_iteration": ob.opened,
                                                "vitals": {v: ob.fact[v] for v in VITALS}}
        actions = []
        for pid, by_norm in sorted(triggers.items()):
            actions.append(Action(self.id, "alert", {"subject": pid, "norms": sorted(by_norm), "triggers": by_norm}))
            detail = "; ".join(f"{nid} disparada pela leitura da iteração {t['reading_iteration']} "
                               f"({_fmt(t['vitals'])})" for nid, t in sorted(by_norm.items()))
            actions.append(Action.send(self.id, self.decision_agent,
                                       f"ALERTA {pid} — {detail}. Leitura atual: {_fmt(env.current[pid])}",
                                       subject=pid))
        return actions

    # --- deliberação ---------------------------------------------------------
    def _deliberate(self, iteration: int, pending: list) -> None:
        env = self.env
        assert isinstance(env, ICUEnv) and env.monitor is not None
        groups: dict[str, list] = defaultdict(list)
        for ob in pending:
            if (ob.norm.id, ob.subject, ob.opened) not in self.decided:
                groups[ob.subject].append(ob)
        cases: dict[str, dict[str, Any]] = {}
        for pid, obs in sorted(groups.items()):
            if any(ob.norm.regimented for ob in obs):  # norma inviolável: a arquitetura impõe o cumprimento
                for ob in obs:
                    self.decided[(ob.norm.id, pid, ob.opened)] = True
                continue
            first = min(obs, key=lambda ob: ob.opened)
            alarm = {"patient": pid, "reading_iteration": first.opened, "norms": sorted(ob.norm.id for ob in obs),
                     "trigger_vitals": {v: first.fact[v] for v in VITALS},
                     "findings": env._bedside_findings(pid, first.opened)}
            cases[pid] = {"obs": obs, "alarm": alarm,
                          "reward": sum(ob.norm.reward for ob in obs),
                          "sanction": sum(ob.norm.sanction for ob in obs),
                          "detection": max(env.monitor.detection_probability(ob.norm.id) for ob in obs)}
        if not cases:
            return
        decisions = self._decide_llm(iteration, cases) if self.llm is not None else self._decide_strategy(cases)
        for pid, (comply, believes_real, reason, policy) in decisions.items():
            c = cases[pid]
            for ob in c["obs"]:
                self.decided[(ob.norm.id, pid, ob.opened)] = comply
            if not comply and not believes_real:  # a satisfação é a de evitar um alarme julgado falso
                self.satisfaction += SUPPRESS_SATISFACTION
            truth = env.patients[pid].in_episode(c["alarm"]["reading_iteration"])
            env.deliberations.append({
                "iteration": iteration, "patient": pid, "reading_iteration": c["alarm"]["reading_iteration"],
                "norms": c["alarm"]["norms"], "comply": comply, "believes_real": believes_real, "truth": truth,
                "detection": c["detection"], "policy": policy, "justification": reason,
            })
            self.knowledge.remember(iteration, "deliberação",
                                    f"{'soou' if comply else 'NÃO soou'} alarme de {pid}: {reason}")

    def _decide_strategy(self, cases: dict[str, dict[str, Any]]) -> dict[str, tuple[bool, bool, str, str]]:
        env = self.env
        assert isinstance(env, ICUEnv)
        out = {}
        for pid, c in cases.items():
            a = c["alarm"]
            believes_real = news_score(a["trigger_vitals"], env.patients[pid].profile, a["findings"]) >= NEWS_THRESHOLD
            gain = -GOALS_MOTIVATION["segurança do paciente"] if believes_real else SUPPRESS_SATISFACTION
            d = self.strategy.decide(DeliberationCase(tuple(a["norms"]), c["reward"], c["sanction"], c["detection"], gain))
            out[pid] = (d.comply, believes_real, d.reason, self.strategy.name)
        return out

    def _decide_llm(self, iteration: int, cases: dict[str, dict[str, Any]]) -> dict[str, tuple[bool, bool, str, str]]:
        env = self.env
        assert isinstance(env, ICUEnv) and self.llm is not None
        r = self.record
        blocks = []
        for pid, c in cases.items():
            blocks.append(env.decision_context(c["alarm"]) +
                          f"\nRecompensa por cumprir: {c['reward']:g}; sanção se a violação for detectada: "
                          f"{c['sanction']:g}; probabilidade de a auditoria detectar a violação: {c['detection']:g}.")
        recent = "; ".join(f"it {it} {nid} ({d:+g})" for it, nid, d in r["sanctions"][-8:])
        harms = "\n".join(f"- [it {it}] {t}" for it, t in r["harms"]) or "- nenhum"
        hist = (f"- obrigações cumpridas: {r['fulfilled']} (recompensas {r['rewards']:+g})\n"
                f"- violações detectadas e sancionadas: {len(r['sanctions'])} "
                f"({sum(d for _, _, d in r['sanctions']):+g})" + (f"; mais recentes: {recent}" if recent else "") + "\n"
                f"- alarmes não soados já confirmados: {r['confirmed_false']} eram falsos, "
                f"{r['confirmed_real']} eram pioras reais\n- danos ao paciente:\n{harms}")
        prompt = (f"Iteração atual: {iteration}\n\nSeu histórico normativo até agora:\n{hist}\n\n"
                  "Obrigações de alarme pendentes:\n\n" + "\n\n".join(blocks))
        schema = json.loads(json.dumps(DELIBERATION_SCHEMA))
        schema["properties"]["decisions"]["items"]["properties"]["patient"]["enum"] = sorted(cases)
        try:
            data = self.llm.generate_json(self.SYSTEM.replace("{confirm_delay}", str(env.confirm_delay)), prompt, schema)
        except LLMError as exc:  # falha pontual: cumpre (o padrão seguro) e registra
            tolerate(exc)
            env.state["llm_failures"] = env.state.get("llm_failures", 0) + 1
            return {pid: (True, True, "falha do LLM: cumprimento por padrão", "llm-fallback") for pid in cases}
        got = {d["patient"]: d for d in data["decisions"] if d["patient"] in cases}
        missing = set(cases) - set(got)
        env.state["deliberation_defaults"] = env.state.get("deliberation_defaults", 0) + len(missing)
        out = {pid: (bool(d["comply"]), bool(d["believes_real"]), d["justification"], "llm") for pid, d in got.items()}
        out.update({pid: (True, True, "sem decisão do LLM: cumprimento por padrão", "llm-default") for pid in missing})
        return out


def _fmt(vitals: dict[str, float]) -> str:
    return ", ".join(f"{k}={v}" for k, v in vitals.items())


ASSESS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "patient": {"type": "string"},
                    "true_alarm": {"type": "boolean"},
                    "priority": {"type": "string", "enum": ["baixa", "media", "alta", "critica"]},
                    "justification": {"type": "string"},
                },
                "required": ["patient", "true_alarm", "priority", "justification"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["assessments"],
    "additionalProperties": False,
}


class DecisionAgent(LLMAgent):
    """Julga se cada alarme corresponde a deterioração real.

    Políticas: ``"llm"`` (quando há ``llm``), ``"news"`` (escore NEWS2
    modificado, padrão offline) e ``"oracle"`` (lê o estado oculto — só como
    referência do efeito de rótulos perfeitos). LLM e NEWS recebem a mesma
    informação: leitura que disparou o alarme, tendência, diagnóstico de base e
    achados à beira-leito."""

    SYSTEM = (
        "Você é o agente de decisão de uma UTI simulada. Para cada alarme, decida se ele corresponde a "
        "uma deterioração clínica real (true_alarm) e a prioridade de intervenção. As evidências são "
        "imperfeitas: achados clínicos também ocorrem em pacientes estáveis (por exemplo, dispneia basal "
        "na DPOC), podem faltar em pacientes em piora, e artefatos de movimento produzem leituras falsas "
        "de SpO2. Pondere a leitura que disparou o alarme, a tendência em relação ao basal do paciente, "
        "a qualidade do sinal e os achados à beira-leito."
    )

    def __init__(self, agent_id: str, llm: LLMClient | None = None, policy: str = "news") -> None:
        super().__init__(agent_id, "decision", llm)
        if policy not in ("news", "oracle"):
            raise ValueError(f"política de decisão desconhecida: {policy!r}")
        self.policy = policy

    def analyze_and_plan(self, p: Perception) -> list[Action]:
        env = self.env
        assert isinstance(env, ICUEnv)
        alerts = [m for m in p.messages if m.content.startswith("ALERTA")]
        if not alerts:
            return []
        subjects = {m.content.split()[1]: m for m in alerts}
        alarms = {pid: env.alarm(pid, m.iteration) for pid, m in subjects.items()}

        def offline() -> tuple[dict[str, bool], dict[str, str]]:
            if self.policy == "oracle":
                v = {pid: a["true"] for pid, a in alarms.items()}
            else:
                v = {pid: news_score(a["trigger_vitals"], env.patients[pid].profile, a["findings"])
                     >= NEWS_THRESHOLD for pid, a in alarms.items()}
            return v, {pid: "alta" if x else "baixa" for pid, x in v.items()}

        if self.llm is None:
            verdicts, priorities = offline()
        else:
            prompt = "\n\n".join(env.decision_context(a) for a in alarms.values())
            schema = json.loads(json.dumps(ASSESS_SCHEMA))
            schema["properties"]["assessments"]["items"]["properties"]["patient"]["enum"] = sorted(subjects)
            try:
                data = self.llm.generate_json(self.SYSTEM, prompt, schema)
            except LLMError as exc:  # falha pontual: decide esta rodada com o NEWS2 e registra
                tolerate(exc)
                env.state["llm_failures"] = env.state.get("llm_failures", 0) + 1
                verdicts, priorities = offline()
            else:
                verdicts = {a["patient"]: a["true_alarm"] for a in data["assessments"] if a["patient"] in subjects}
                priorities = {a["patient"]: a["priority"] for a in data["assessments"]}
                missing = len(set(subjects) - set(verdicts))
                env.state["decision_defaults"] = env.state.get("decision_defaults", 0) + missing
        return [
            Action(self.id, "assess", {
                "subject": pid, "alarm_iteration": m.iteration,
                "true_alarm": bool(verdicts.get(pid, True)),  # na dúvida, trata como real
                "priority": priorities.get(pid, "alta"),
            })
            for pid, m in subjects.items()
        ]


# --------------------------------------------------------------------------
# Política offline do LLM-NormRecommender
# --------------------------------------------------------------------------
def icu_offline_recommender(kb: NormKnowledgeBase, evidence: dict[str, Any], iteration: int) -> list[NormProposal]:
    """Heurística determinística equivalente à tarefa pedida ao LLM: para normas
    com alarmes falsos recorrentes em um paciente, ajusta o limiar para além dos
    valores que geraram alarmes falsos e exige 2 leituras consecutivas."""
    proposals = []
    bounds = {(b.norm_id, b.parameter): b for b in SAFETY_BOUNDS}
    for pid, info in evidence.get("patients", {}).items():
        for norm_id, ev in info["alarm_norms"].items():
            n_false = ev["false_alarms_since_change"]
            if n_false < 2 or ev["true_alarms_since_change"] > n_false / 3:
                continue
            vital, param = ALARM_NORMS[norm_id]
            current = ev["parameters"][param]
            values = [v[vital] for v in ev["false_alarm_readings_since_change"]]
            b = bounds[(norm_id, param)]
            if norm_id in ("ICU-SPO2-LOW", "ICU-SBP-LOW"):
                new = max(b.minimum, math.floor(min(values) - 0.5))
                if new >= current:
                    continue
            else:
                new = min(b.maximum, math.ceil(max(values) + 2))
                if new <= current:
                    continue
            proposals.append(NormProposal(
                norm_id, {param: float(new)}, persistence=2, scope_field="id", scope_value=pid,
                rationale=f"{n_false} alarmes falsos de {norm_id} em {pid} ({info['profile']}) desde a última "
                          f"mudança; {vital} basal ≈ {info['baseline_median_last_30'][vital]}",
            ))
    return proposals


# --------------------------------------------------------------------------
# Montagem e execução
# --------------------------------------------------------------------------
def make_patients(n: int, iterations: int, seed: int | None) -> list[Patient]:
    import random

    rng = random.Random(seed)
    profiles = list(PROFILES)
    patients = []
    for i in range(n):
        onset = rng.randint(20, max(21, iterations - 15)) if rng.random() < 0.5 else None
        patients.append(Patient(f"P{i + 1}", profiles[i % len(profiles)], onset))
    return patients


@dataclass
class ICURun:
    result: SimulationResult
    env: ICUEnv
    processor: LLMNormProcessor | None


_SAME: Any = object()


def run_icu(llm: LLMClient | None = None, adaptive: bool = True, patients: int = 12, iterations: int = 120,
            seed: int | None = 0, adapt_every: int = 15, supervisor: HumanSupervisor | None = None,
            decision_llm: LLMClient | None = _SAME, validator_llm: LLMClient | None = _SAME,
            decision_policy: str = "news", confirm_delay: int = 30,
            compliance: str | None = None, compliance_llm: LLMClient | None = None,
            detection: float = 1.0, sanction_scale: float = 1.0) -> ICURun:
    """``llm`` é usado pelo recomendador e pelo auditor; ``decision_llm`` pelo
    agente de decisão e ``validator_llm`` pela revisão do validador (por padrão,
    o mesmo ``llm``; ``None`` = componente determinístico).

    Fase 2: ``compliance`` = ``None`` (cumpre sempre, como na fase 1), o nome de
    uma estratégia normativa ou ``"llm"`` (deliberação por ``compliance_llm``);
    ``detection`` = probabilidade de uma violação ser detectada."""
    env = ICUEnv(make_patients(patients, iterations, seed), seed=seed, confirm_delay=confirm_delay)
    kb = NormKnowledgeBase(icu_norms(sanction_scale))
    env.use_norms(kb, detection)
    ids = list(env.patients)
    half = len(ids) // 2
    env.register(MonitoringAgent("Monitor1", ids[:half]))
    env.register(MonitoringAgent("Monitor2", ids[half:]))
    strategy = make_strategy(compliance) if compliance not in (None, "llm") else None
    env.register(AlertingAgent("Alerting", "Decision", strategy, compliance_llm if compliance == "llm" else None))
    env.register(DecisionAgent("Decision", llm if decision_llm is _SAME else decision_llm, decision_policy))

    processor = engine = None
    if adaptive:
        processor = LLMNormProcessor(
            recommender=LLMNormRecommender(llm, icu_offline_recommender, DOMAIN_BRIEF),
            validator=LLMNormValidator(SAFETY_BOUNDS, max_persistence=3,
                                       llm=llm if validator_llm is _SAME else validator_llm,
                                       scope_values={"id": set(env.patients)}),
            auditor=LLMNormAuditor(llm),
            llm=llm,
        )
        engine = NormAdaptationEngine(kb, processor, supervisor or AutoApprove(), every=adapt_every)
    result = Simulation(env, iterations, adaptation=engine).run()
    return ICURun(result, env, processor)


def compare_icu(llm: LLMClient | None = None, seeds: list[int] | None = None, **kwargs: Any) -> dict[str, Any]:
    """Normas estáticas × adaptativas nas mesmas sementes, com teste t pareado
    sobre o número de alarmes falsos (estatística t e graus de liberdade)."""
    seeds = seeds or [0]
    rows = []
    for s in seeds:
        base = run_icu(llm, adaptive=False, seed=s, **kwargs).result.metrics
        adap = run_icu(llm, adaptive=True, seed=s, **kwargs).result.metrics
        rows.append({"seed": s, "baseline": base, "adaptive": adap})
    diffs = [r["baseline"]["false_alarms"] - r["adaptive"]["false_alarms"] for r in rows]
    summary: dict[str, Any] = {"runs": rows, "mean_false_alarm_reduction": round(statistics.mean(diffs), 2)}
    if len(diffs) > 1:
        sd = statistics.stdev(diffs)
        summary["paired_t"] = round(statistics.mean(diffs) / (sd / math.sqrt(len(diffs))), 3) if sd else math.inf
        summary["df"] = len(diffs) - 1
    return summary
