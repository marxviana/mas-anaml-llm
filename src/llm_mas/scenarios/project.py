"""Modelagem de contextos dinâmicos em simulação de gestão de projetos de
software baseada em multiagentes (Tema 2 do projeto).

* ``ScenarioGenerator``   — gera cenários de projeto (equipe, backlog e eventos
                            de contexto); com LLM, a partir de uma descrição em
                            linguagem natural (Hong et al., 2023 — geração de cenários).
* ``ProjectManagerAgent`` — gerente (LLM): apoio à decisão de alocação diante de
                            mudanças de contexto (Chen et al., 2023).
* ``DeveloperAgent``      — executa tarefas, relata status e se adapta a sanções.
* Eventos de contexto     — mudança de requisitos, saída/entrada de
                            desenvolvedores, pico de bugs, queda de produtividade.
* Normas                  — limite de WIP por desenvolvedor (proibição) e prazo
                            para atribuir tarefas sem responsável (obrigação).

``adaptive=False`` modela um plano estático (o gerente só aloca no início),
permitindo comparar com a gestão que reage ao contexto dinâmico.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from llm_mas.core.agent import Agent, LLMAgent, Perception
from llm_mas.core.environment import Environment
from llm_mas.core.knowledge import Knowledge
from llm_mas.core.messages import Action
from llm_mas.core.simulation import Simulation, SimulationResult
from llm_mas.llm.base import LLMClient
from llm_mas.llm.parsing import format_action
from llm_mas.norms import Condition, Deontic, Norm, NormEvent, NormKnowledgeBase

SKILLS = ("backend", "frontend", "qa")
# Uma atribuição por mensagem, e só quando é a mensagem inteira (como os comandos do marketplace).
ASSIGN_RE = re.compile(r"\s*assign\s+(T\d+)\s*\.?\s*", re.IGNORECASE)
WIP_LIMIT = 2


@dataclass
class Task:
    id: str
    skill: str
    effort: float
    status: str = "todo"  # todo | assigned | doing | done | orphaned
    assignee: str | None = None
    progress: float = 0.0
    created: int = 0
    done_at: int | None = None


@dataclass
class DeveloperSpec:
    id: str
    skills: dict[str, float]  # habilidade -> produtividade (pontos/iteração)


@dataclass
class ContextEvent:
    iteration: int
    kind: str  # requirement_change | developer_leave | developer_join | bug_spike | productivity_drop
    description: str
    developer: str = ""
    n_tasks: int = 0
    skill: str = ""
    factor: float = 1.0
    duration: int = 0
    skills: dict[str, float] = field(default_factory=dict)


@dataclass
class ProjectScenario:
    team: list[DeveloperSpec]
    tasks: list[Task]
    events: list[ContextEvent]
    description: str = ""


def project_norms() -> list[Norm]:
    return [
        Norm(
            "PM-WIP-LIMIT", f"Um desenvolvedor não deve iniciar uma tarefa tendo {WIP_LIMIT} ou mais em andamento.",
            Deontic.PROHIBITION, "developer",
            target=Condition.all(("type", "==", "start"), ("wip", ">=", "$wip_limit")),
            parameters={"wip_limit": WIP_LIMIT}, sanction=2,
        ),
        Norm(
            "PM-ASSIGN-BACKLOG", "Toda tarefa sem responsável deve ser atribuída a alguém em até 2 iterações.",
            Deontic.OBLIGATION, "manager",
            # só conta uma atribuição que teve efeito; reabre a cada prazo enquanto a tarefa
            # continuar sem responsável, então as violações medem a duração do abandono
            target=Condition.all(("type", "==", "send"), ("command", "==", "assign"), ("executed", "==", True)),
            activation=Condition.all(("status", "in", ["todo", "orphaned"])),
            deadline=2, sanction=3, reward=0.5, rearm=True,
        ),
    ]


# --------------------------------------------------------------------------
# Geração de cenários
# --------------------------------------------------------------------------
SCENARIO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "team": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "skills": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"skill": {"type": "string", "enum": list(SKILLS)},
                                           "productivity": {"type": "number"}},
                            "required": ["skill", "productivity"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["id", "skills"],
                "additionalProperties": False,
            },
        },
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"skill": {"type": "string", "enum": list(SKILLS)}, "effort": {"type": "number"}},
                "required": ["skill", "effort"],
                "additionalProperties": False,
            },
        },
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "iteration": {"type": "integer"},
                    "kind": {"type": "string", "enum": ["requirement_change", "developer_leave", "developer_join",
                                                        "bug_spike", "productivity_drop"]},
                    "description": {"type": "string"},
                    "developer": {"type": "string"},
                    "n_tasks": {"type": "integer"},
                    "skill": {"type": "string"},
                    "factor": {"type": "number"},
                    "duration": {"type": "integer"},
                },
                "required": ["iteration", "kind", "description", "developer", "n_tasks", "skill", "factor",
                             "duration"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["description", "team", "tasks", "events"],
    "additionalProperties": False,
}


class ScenarioGenerator:
    SYSTEM = (
        "Você gera cenários realistas para simular a gestão de um projeto de software com sistemas "
        "multiagentes. Produtividade em pontos de esforço por iteração (0.5 a 3); esforço das tarefas "
        "entre 1 e 10. Eventos de contexto devem ocorrer durante o projeto e referenciar desenvolvedores "
        "existentes (exceto developer_join, que cria um novo). Campos que não se aplicam a um evento "
        "recebem string vazia, 0 ou 1.0."
    )

    def __init__(self, llm: LLMClient | None = None, seed: int | None = 0) -> None:
        self.llm = llm
        import random

        self.rng = random.Random(seed)

    def generate(self, brief: str = "") -> ProjectScenario:
        if self.llm is None:
            return self._offline()
        data = self.llm.generate_json(self.SYSTEM, brief or "Projeto web de porte médio, equipe de 4 a 5 pessoas.",
                                      SCENARIO_SCHEMA)
        team = [DeveloperSpec(d["id"], {s["skill"]: s["productivity"] for s in d["skills"]}) for d in data["team"]]
        tasks = [Task(f"T{i + 1}", t["skill"], t["effort"]) for i, t in enumerate(data["tasks"])]
        events = [ContextEvent(**e) for e in data["events"]]
        return ProjectScenario(team, tasks, events, data["description"])

    def _offline(self) -> ProjectScenario:
        r = self.rng
        team = [
            DeveloperSpec("Dev1", {"backend": 2.0, "qa": 0.8}),
            DeveloperSpec("Dev2", {"backend": 1.5, "frontend": 1.2}),
            DeveloperSpec("Dev3", {"frontend": 2.0, "qa": 1.0}),
            DeveloperSpec("Dev4", {"qa": 1.8, "backend": 0.7}),
        ]
        tasks = [Task(f"T{i + 1}", SKILLS[i % 3], float(r.randint(2, 8))) for i in range(18)]
        events = [
            ContextEvent(6, "requirement_change", "Cliente pede novas funcionalidades de backend.",
                         n_tasks=4, skill="backend"),
            ContextEvent(9, "developer_leave", "Dev2 é realocado para outro projeto.", developer="Dev2"),
            ContextEvent(12, "bug_spike", "Testes de integração revelam bugs.", n_tasks=3, skill="qa"),
            ContextEvent(14, "productivity_drop", "Dev3 fica parcialmente indisponível.", developer="Dev3",
                         factor=0.5, duration=5),
            ContextEvent(16, "developer_join", "Dev5 entra na equipe.", developer="Dev5",
                         skills={"backend": 1.6, "frontend": 1.4}),
        ]
        return ProjectScenario(team, tasks, events, "Cenário offline padrão (5 eventos de contexto).")


# --------------------------------------------------------------------------
# Ambiente
# --------------------------------------------------------------------------
class ProjectEnv(Environment):
    def __init__(self, scenario: ProjectScenario, seed: int | None = None) -> None:
        super().__init__("project", seed)
        self.scenario = scenario
        self.tasks: dict[str, Task] = {t.id: t for t in scenario.tasks}
        self.events_by_iteration: dict[int, list[ContextEvent]] = {}
        for e in scenario.events:
            self.events_by_iteration.setdefault(e.iteration, []).append(e)
        self.event_log: list[ContextEvent] = []
        self.done = False
        self.completed_at: int | None = None
        self.initial_effort = sum(t.effort for t in scenario.tasks)
        self.initial_capacity = sum(max(d.skills.values()) for d in scenario.team)

    def developers(self) -> list[DeveloperAgent]:
        # ordenados por id: desempates não dependem da ordem de registro
        return sorted((a for a in self.agents.values() if isinstance(a, DeveloperAgent)), key=lambda d: d.id)

    def update(self, iteration: int) -> None:
        for event in self.events_by_iteration.get(iteration, []):
            self._apply_event(event, iteration)
        for dev in self.developers():
            dev.work(iteration)
        if all(t.status == "done" for t in self.tasks.values()) and not self.done:
            self.done = True
            self.completed_at = iteration

    def _new_tasks(self, n: int, skill: str, iteration: int) -> None:
        for _ in range(n):
            tid = f"T{len(self.tasks) + 1}"
            self.tasks[tid] = Task(tid, skill or "backend", float(self.rng.randint(2, 6)), created=iteration)

    def _apply_event(self, e: ContextEvent, iteration: int) -> None:
        self.event_log.append(e)
        if e.kind in ("requirement_change", "bug_spike"):
            self._new_tasks(e.n_tasks, e.skill, iteration)
        elif e.kind == "developer_leave" and e.developer in self.agents:
            dev = self.agents[e.developer]
            assert isinstance(dev, DeveloperAgent)
            dev.available = False
            dev.queue.clear()
            for t in self.tasks.values():
                if t.assignee == dev.id and t.status != "done":
                    t.status, t.assignee = "orphaned", None
        elif e.kind == "developer_join" and e.developer not in self.agents:
            self.register(DeveloperAgent(e.developer, e.skills or {"backend": 1.0}, manager=self.manager_id))
        elif e.kind == "productivity_drop" and e.developer in self.agents:
            dev = self.agents[e.developer]
            assert isinstance(dev, DeveloperAgent)
            dev.factor, dev.factor_until = e.factor, iteration + e.duration

    @property
    def manager_id(self) -> str:
        return next(a.id for a in self.agents.values() if a.role == "manager")

    def apply(self, action: Action) -> None:
        if action.type == "send":
            m = ASSIGN_RE.fullmatch(action.data["content"])
            receiver = self.agents.get(action.data["receiver"])
            if m:
                tid = m.group(1).upper()
                task = self.tasks.get(tid)
                action.data.update(command="assign", subject=tid, executed=False)
                if task is None:
                    why = f"a tarefa {tid} não existe"
                elif not isinstance(receiver, DeveloperAgent):
                    why = f"{action.data['receiver']} não é desenvolvedor"
                elif not receiver.available:
                    why = f"{receiver.id} não está mais no projeto"
                elif task.status not in ("todo", "orphaned"):
                    why = f"a tarefa {tid} já está {task.status} ({task.assignee or '-'})"
                else:
                    why = ""
                    task.status, task.assignee = "assigned", receiver.id
                    action.data["executed"] = True
                if why:
                    self.notify(action.agent, f"'assign {tid}' para {action.data['receiver']} não teve efeito: {why}.")
            else:
                action.data.setdefault("command", "chat")
                if "assign" in action.data["content"].lower() and action.agent == self.manager_id:
                    self.notify(action.agent, f"Sua mensagem a {action.data['receiver']} cita 'assign', mas não é "
                                              "só o comando 'assign <IdTarefa>'; não teve efeito.")
        elif action.type == "start":
            task = self.tasks[action.data["subject"]]
            task.status = "doing"
        super().apply(action)

    def facts(self) -> list[dict[str, Any]]:
        return [{"id": t.id, "status": t.status, "skill": t.skill} for t in self.tasks.values()]

    def metrics(self) -> dict[str, Any]:
        done = [t for t in self.tasks.values() if t.status == "done"]
        planned = math.ceil(self.initial_effort / self.initial_capacity)
        remaining = sum(t.effort - t.progress for t in self.tasks.values() if t.status != "done")
        return {
            "tasks_total": len(self.tasks),
            "tasks_done": len(done),
            "remaining_effort": round(remaining, 1),
            "completed_at": self.completed_at,
            "planned_iterations": planned,
            "schedule_slip": (self.completed_at - planned) if self.completed_at else None,
            "context_events": [f"it {e.iteration}: {e.kind} — {e.description}" for e in self.event_log],
            "llm_failures": self.state.get("llm_failures", 0),
        }

    def status_report(self) -> str:
        lines = []
        for t in self.tasks.values():
            if t.status != "done":
                who = t.assignee or "-"
                lines.append(f"{t.id} [{t.skill}, esforço {t.effort:g}, {t.progress:.1f} feito] {t.status} ({who})")
        return "\n".join(lines) or "(todas as tarefas concluídas)"

    def team_report(self) -> str:
        lines = []
        for d in self.developers():
            state = "disponível" if d.available else "fora do projeto"
            skills = ", ".join(f"{k}:{v:g}" for k, v in d.skills.items())
            load = sum(self.tasks[t].effort - self.tasks[t].progress for t in d.assigned_tasks())
            lines.append(f"{d.id} ({state}; {skills}; carga restante {load:.1f}; fator {d.current_factor():g})")
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Agentes
# --------------------------------------------------------------------------
class DeveloperAgent(Agent):
    def __init__(self, agent_id: str, skills: dict[str, float], manager: str, respects_wip: bool = True) -> None:
        super().__init__(agent_id, "developer", Knowledge(goals=["concluir as tarefas atribuídas"]))
        self.skills = skills
        self.manager = manager
        self.available = True
        self.respects_wip = respects_wip
        self.queue: list[str] = []
        self.factor = 1.0
        self.factor_until = 0

    def current_factor(self) -> float:
        assert self.env is not None
        return self.factor if self.env.iteration < self.factor_until else 1.0

    def doing(self) -> list[Task]:
        env = self.env
        assert isinstance(env, ProjectEnv)
        return [t for t in env.tasks.values() if t.assignee == self.id and t.status == "doing"]

    def assigned_tasks(self) -> list[str]:
        env = self.env
        assert isinstance(env, ProjectEnv)
        return [t.id for t in env.tasks.values() if t.assignee == self.id and t.status in ("assigned", "doing")]

    def work(self, iteration: int) -> None:
        """Avança as tarefas em andamento; multitarefa tem custo de troca de contexto."""
        doing = self.doing()
        if not self.available or not doing:
            return
        switch_penalty = 0.8 if len(doing) > 1 else 1.0
        for task in doing:
            productivity = self.skills.get(task.skill, 0.3)
            task.progress += productivity * self.current_factor() * switch_penalty / len(doing)
            if task.progress >= task.effort:
                task.progress, task.status, task.done_at = task.effort, "done", iteration

    def analyze_and_plan(self, p: Perception) -> list[Action]:
        env = self.env
        assert isinstance(env, ProjectEnv)
        if not self.available:
            return []
        for m in p.messages:
            match = ASSIGN_RE.fullmatch(m.content)
            if match and match.group(1).upper() not in self.queue:
                self.queue.append(match.group(1).upper())
        self.queue = [t for t in self.queue if t in env.tasks
                      and env.tasks[t].assignee == self.id and env.tasks[t].status == "assigned"]
        actions = []
        wip = len(self.doing())
        while self.queue and (not self.respects_wip or wip < WIP_LIMIT):
            tid = self.queue.pop(0)
            actions.append(Action(self.id, "start", {"subject": tid, "wip": wip}))
            wip += 1
        done_now = [t.id for t in env.tasks.values() if t.assignee == self.id and t.done_at == p.iteration]
        if actions or done_now:
            started = ", ".join(a.data["subject"] for a in actions) or "-"
            actions.append(Action.send(self.id, self.manager,
                                       f"status: iniciei {started}; concluí {', '.join(done_now) or '-'}"))
        return actions

    def on_norm_event(self, event: NormEvent) -> None:
        super().on_norm_event(event)
        if event.kind == "violation" and event.norm_id == "PM-WIP-LIMIT":
            self.respects_wip = True  # adaptação: passa a respeitar o limite de WIP


class ProjectManagerAgent(LLMAgent):
    def __init__(self, agent_id: str, llm: LLMClient | None = None, adaptive: bool = True) -> None:
        super().__init__(agent_id, "manager", llm, Knowledge(goals=[
            "Concluir o projeto o quanto antes, mantendo todas as tarefas com responsável.",
            "Atribuir tarefas a desenvolvedores disponíveis com a habilidade adequada, equilibrando a carga.",
            "Reagir a mudanças de contexto (requisitos, saída de pessoas, bugs, queda de produtividade).",
            "Para atribuir, envie ao desenvolvedor uma mensagem contendo só 'assign <IdTarefa>' — uma tarefa "
            "por mensagem; para várias tarefas, use várias ações. Texto junto com o comando o anula.",
            "Só têm efeito atribuições de tarefas existentes, ainda sem responsável, a desenvolvedores "
            "disponíveis. O desenvolvedor recebe a mensagem e começa a tarefa na iteração seguinte.",
            "Norma PM-ASSIGN-BACKLOG: tarefa sem responsável por mais de 2 iterações gera sanção, "
            "repetida a cada 2 iterações enquanto continuar sem responsável.",
        ]))
        self.adaptive = adaptive

    def sense(self, iteration: int) -> dict[str, Any]:
        env = self.env
        assert isinstance(env, ProjectEnv)
        new_events = [f"{e.kind}: {e.description}" for e in env.event_log if e.iteration == iteration]
        return {
            "eventos_de_contexto_nesta_iteração": "; ".join(new_events) or "nenhum",
            "equipe": "\n" + env.team_report(),
            "backlog_pendente": "\n" + env.status_report(),
        }

    def analyze_and_plan(self, p: Perception) -> list[Action]:
        env = self.env
        assert isinstance(env, ProjectEnv)
        if not self.adaptive and p.iteration > 1:
            return []  # plano estático: aloca uma vez e não reage ao contexto
        if not any(t.status in ("todo", "orphaned") for t in env.tasks.values()):
            return []  # nada a decidir: evita uma chamada ao LLM
        return super().analyze_and_plan(p)

    def heuristic(self, p: Perception) -> str:
        env = self.env
        assert isinstance(env, ProjectEnv)
        devs = [d for d in env.developers() if d.available]
        load = {d.id: sum(env.tasks[t].effort - env.tasks[t].progress for t in d.assigned_tasks()) for d in devs}
        out = []
        pending = sorted((t for t in env.tasks.values() if t.status in ("todo", "orphaned")),
                         key=lambda t: (t.status != "orphaned", t.created, t.id))
        for task in pending:
            if not devs:
                break
            best = min(devs, key=lambda d: (load[d.id] + task.effort) / d.skills.get(task.skill, 0.3))
            load[best.id] += task.effort
            out.append(format_action(best.id, f"assign {task.id}"))
        return "".join(out)


def run_project(llm: LLMClient | None = None, adaptive: bool = True, iterations: int = 60, seed: int | None = 0,
                scenario: ProjectScenario | None = None, brief: str = "",
                undisciplined: tuple[str, ...] = ("Dev1",)) -> tuple[SimulationResult, ProjectEnv]:
    scenario = scenario or ScenarioGenerator(llm, seed).generate(brief)
    env = ProjectEnv(scenario, seed)
    env.use_norms(NormKnowledgeBase(project_norms()))
    env.register(ProjectManagerAgent("PM", llm, adaptive))
    for spec in scenario.team:
        env.register(DeveloperAgent(spec.id, dict(spec.skills), "PM", respects_wip=spec.id not in undisciplined))
    return Simulation(env, iterations).run(), env
