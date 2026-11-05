"""Componentes LLM da extensão do JSAN+AN (ANA-ML 2.0, Seção IV):

* ``LLMNormRecommender`` — sugere refinamentos/novas normas a partir de evidências;
* ``LLMNormValidator``   — verifica consistência e limites de segurança;
* ``LLMNormAuditor``     — relata eficácia e conformidade em linguagem natural;
* ``LLMNormProcessor``   — fachada que reúne os três e interpreta normas
                            escritas em linguagem natural.

Todos funcionam sem LLM (``llm=None``) usando regras determinísticas ou uma
política *fallback* fornecida pelo cenário, o que permite comparar a abordagem
com e sem LLM e executar os testes offline. As restrições de segurança do
validador são sempre determinísticas: o LLM pode reprovar uma proposta, mas
nunca aprovar uma que viole um limite.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from llm_mas.llm.base import LLMError, tolerate
from llm_mas.norms.condition import Condition
from llm_mas.norms.knowledge_base import NormKnowledgeBase
from llm_mas.norms.norm import Deontic, Norm

if TYPE_CHECKING:
    from llm_mas.llm.base import LLMClient
    from llm_mas.norms.monitor import NormEvent


# --------------------------------------------------------------------------
# Propostas de adaptação
# --------------------------------------------------------------------------
@dataclass
class NormProposal:
    """Refinamento proposto para ``base_norm_id``.

    Sem escopo, altera a norma geral. Com ``scope_field``/``scope_value``,
    cria (ou atualiza) uma norma específica que substitui a geral apenas
    naquele contexto — p.ex. um limiar por paciente.
    """

    base_norm_id: str
    parameters: dict[str, float] = field(default_factory=dict)
    persistence: int | None = None
    scope_field: str | None = None
    scope_value: str | None = None
    rationale: str = ""

    @property
    def target_id(self) -> str:
        return f"{self.base_norm_id}@{self.scope_value}" if self.scope_field else self.base_norm_id

    def build(self, kb: NormKnowledgeBase) -> Norm:
        base = kb.get(self.base_norm_id)
        if base is None:
            raise KeyError(self.base_norm_id)
        if not self.scope_field:
            return base.with_changes(
                parameters={**base.parameters, **self.parameters},
                persistence=self.persistence or base.persistence,
            )
        existing = kb.get(self.target_id)
        source = existing or base
        return Norm(
            id=self.target_id,
            description=f"{base.description} [ajustada para {self.scope_field}={self.scope_value}]",
            deontic=base.deontic,
            addressee=base.addressee,
            target=base.target,
            activation=base.activation,
            scope=Condition.all((self.scope_field, "==", self.scope_value)),
            parameters={**source.parameters, **self.parameters},
            deadline=base.deadline,
            persistence=self.persistence or source.persistence,
            sanction=base.sanction,
            reward=base.reward,
            adaptable=True,
            overrides=base.id,
            rearm=base.rearm,
            version=existing.version + 1 if existing else 1,
        )


PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "base_norm_id": {"type": "string"},
                    "scope_field": {"type": "string", "description": "campo do fato; vazio = norma geral"},
                    "scope_value": {"type": "string"},
                    "parameters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "value": {"type": "number"}},
                            "required": ["name", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "persistence": {"type": "integer", "description": "0 = manter a atual"},
                    "rationale": {"type": "string"},
                },
                "required": ["base_norm_id", "scope_field", "scope_value", "parameters", "persistence", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["proposals"],
    "additionalProperties": False,
}

RecommenderFallback = Callable[[NormKnowledgeBase, dict[str, Any], int], list[NormProposal]]


class LLMNormRecommender:
    SYSTEM = (
        "Você é o LLM-NormRecommender de um sistema multiagente normativo adaptativo. "
        "Analise as normas vigentes e as evidências coletadas pelos agentes e proponha "
        "refinamentos de parâmetros que reduzam falhas observadas sem comprometer a segurança. "
        "Proponha apenas mudanças sustentadas pelas evidências; uma lista vazia é uma resposta válida. "
        "Nunca proponha alterações em normas marcadas como não adaptáveis e respeite os limites informados."
    )

    def __init__(self, llm: LLMClient | None = None, fallback: RecommenderFallback | None = None,
                 domain_brief: str = "") -> None:
        self.llm = llm
        self.fallback = fallback
        self.domain_brief = domain_brief
        self.failures = 0

    def recommend(self, kb: NormKnowledgeBase, evidence: dict[str, Any], iteration: int) -> list[NormProposal]:
        if self.llm is None:
            return self.fallback(kb, evidence, iteration) if self.fallback else []
        prompt = (
            f"Domínio:\n{self.domain_brief}\n\n"
            f"Iteração: {iteration}\n\n"
            f"Normas vigentes (JSON):\n{json.dumps(kb.snapshot(), ensure_ascii=False, separators=(",", ":"))}\n\n"
            f"Evidências (JSON):\n{json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))}\n\n"
            f"Histórico de propostas (aplicadas e rejeitadas, com motivos) — não repita uma proposta "
            f"rejeitada sem evidência nova:\n{self._history(kb)}\n\n"
            "Para uma norma específica de um contexto, use scope_field/scope_value "
            "(ex.: scope_field='id', scope_value='P3'). Para alterar a norma geral, deixe ambos vazios. "
            "base_norm_id é sempre o id da norma geral (sem '@'); para reajustar uma norma específica "
            "já existente, repita a proposta sobre a norma geral com o mesmo escopo. "
            "persistence = número de leituras consecutivas exigidas; use 0 para manter a persistência atual."
        )
        try:
            data = self.llm.generate_json(self.SYSTEM, prompt, PROPOSAL_SCHEMA)
        except LLMError as exc:  # falha pontual: usa a política offline nesta revisão
            tolerate(exc)
            self.failures += 1
            return self.fallback(kb, evidence, iteration) if self.fallback else []
        return [
            NormProposal(
                base_norm_id=p["base_norm_id"],
                parameters={x["name"]: x["value"] for x in p["parameters"]},
                persistence=p["persistence"] or None,
                scope_field=p["scope_field"] or None,
                scope_value=p["scope_value"] or None,
                rationale=p["rationale"],
            )
            for p in data.get("proposals", [])
        ]

    @staticmethod
    def _history(kb: NormKnowledgeBase, limit: int = 30) -> str:
        lines = []
        for c in kb.history[-limit:]:
            params = c.after.parameters if c.after else {}
            lines.append(f"- it {c.iteration} {c.norm_id} {params} [{c.status}]: {c.rationale}")
        return "\n".join(lines) or "(nenhuma)"


# --------------------------------------------------------------------------
# Validação
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SafetyBound:
    norm_id: str
    parameter: str
    minimum: float | None = None
    maximum: float | None = None


@dataclass
class ValidationResult:
    ok: bool
    issues: list[str] = field(default_factory=list)


VALIDATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"approve": {"type": "boolean"}, "issues": {"type": "array", "items": {"type": "string"}}},
    "required": ["approve", "issues"],
    "additionalProperties": False,
}


class LLMNormValidator:
    SYSTEM = (
        "Você é o LLM-NormValidator. Verifique se a norma candidata é consistente com o conjunto "
        "de normas vigentes: aponte conflitos, lacunas de segurança ou incoerências. "
        "Aprove apenas se não houver problemas."
    )

    def __init__(self, bounds: Iterable[SafetyBound] = (), max_persistence: int = 3,
                 llm: LLMClient | None = None, scope_values: dict[str, set[str]] | None = None) -> None:
        """``scope_values`` lista os campos de escopo válidos e seus valores
        (ex.: ``{"id": {"P1", "P2"}}``); sem ele, o escopo não é verificado."""
        self.bounds = list(bounds)
        self.max_persistence = max_persistence
        self.llm = llm
        self.scope_values = scope_values
        self.failures = 0

    def validate(self, proposal: NormProposal, kb: NormKnowledgeBase) -> ValidationResult:
        issues: list[str] = []
        base = kb.get(proposal.base_norm_id)
        if base is None:
            return ValidationResult(False, [f"norma inexistente: {proposal.base_norm_id}"])
        if not base.adaptable:
            return ValidationResult(False, [f"norma {base.id} não é adaptável"])
        if base.overrides:
            return ValidationResult(False, [f"{base.id} é uma norma específica; proponha sobre {base.overrides}"])
        if proposal.scope_field and self.scope_values is not None:
            valid = self.scope_values.get(proposal.scope_field)
            if valid is None:
                issues.append(f"campo de escopo inexistente: {proposal.scope_field}")
            elif proposal.scope_value not in valid:
                issues.append(f"valor de escopo inexistente: {proposal.scope_field}={proposal.scope_value}")
        for name, value in proposal.parameters.items():
            if name not in base.parameters:
                issues.append(f"parâmetro desconhecido em {base.id}: {name}")
                continue
            for b in self.bounds:
                if b.norm_id == base.id and b.parameter == name:
                    if b.minimum is not None and value < b.minimum:
                        issues.append(f"{base.id}.{name}={value} abaixo do mínimo de segurança {b.minimum}")
                    if b.maximum is not None and value > b.maximum:
                        issues.append(f"{base.id}.{name}={value} acima do máximo de segurança {b.maximum}")
        if proposal.persistence is not None and not 1 <= proposal.persistence <= self.max_persistence:
            issues.append(f"persistência {proposal.persistence} fora de [1, {self.max_persistence}]")
        if issues or self.llm is None:
            return ValidationResult(not issues, issues)

        candidate = proposal.build(kb)
        prompt = (
            f"Normas vigentes:\n{json.dumps(kb.snapshot(), ensure_ascii=False, separators=(",", ":"))}\n\n"
            f"Norma candidata:\n{json.dumps(candidate.to_dict(), ensure_ascii=False, separators=(",", ":"))}\n\n"
            f"Justificativa: {proposal.rationale}"
        )
        try:
            data = self.llm.generate_json(self.SYSTEM, prompt, VALIDATION_SCHEMA)
        except LLMError as exc:  # falha pontual: vale só a verificação determinística
            tolerate(exc)
            self.failures += 1
            return ValidationResult(True, [])
        return ValidationResult(bool(data["approve"]), list(data["issues"]))


# --------------------------------------------------------------------------
# Auditoria
# --------------------------------------------------------------------------
@dataclass
class AuditReport:
    stats: dict[str, Any]
    changes: list[str]
    narrative: str

    def __str__(self) -> str:
        lines = ["== Auditoria de normas =="]
        for norm_id, s in sorted(self.stats["by_norm"].items()):
            lines.append(f"  {norm_id}: {s['violation']} violações, {s['fulfillment']} cumprimentos")
        lines.append(f"  Mudanças de normas: {len(self.changes)}")
        lines.extend(f"    - {c}" for c in self.changes)
        lines.append("")
        lines.append(self.narrative)
        return "\n".join(lines)


class LLMNormAuditor:
    SYSTEM = (
        "Você é o LLM-NormAuditor. Com base nas estatísticas de aplicação das normas, no histórico "
        "de adaptações e nas métricas do sistema, escreva um relatório curto e objetivo para um "
        "especialista humano: eficácia das normas, desalinhamentos encontrados e recomendações. "
        "Não invente números que não estejam nos dados."
    )

    def __init__(self, llm: LLMClient | None = None) -> None:
        self.llm = llm
        self.failures = 0

    def audit(self, kb: NormKnowledgeBase, events: list[NormEvent], metrics: dict[str, Any]) -> AuditReport:
        by_norm: dict[str, dict[str, int]] = defaultdict(lambda: {"violation": 0, "fulfillment": 0})
        for e in events:
            by_norm[e.norm_id][e.kind] += 1
        stats = {"by_norm": dict(by_norm), "norms": len(kb)}
        changes = [
            f"it {c.iteration} {c.norm_id} [{c.status}] por {c.approved_by}: {c.rationale}" for c in kb.history
        ]
        if self.llm is None:
            applied = sum(1 for c in kb.history if c.status == "applied")
            rejected = len(kb.history) - applied
            narrative = (
                f"{applied} adaptação(ões) aplicada(s) e {rejected} rejeitada(s). "
                f"Métricas: {json.dumps(metrics, ensure_ascii=False)}"
            )
        else:
            prompt = (
                f"Estatísticas por norma: {json.dumps(stats, ensure_ascii=False)}\n"
                f"Histórico de adaptações:\n" + "\n".join(changes or ["(nenhuma)"]) + "\n"
                f"Métricas do sistema: {json.dumps(metrics, ensure_ascii=False)}"
            )
            try:
                narrative = self.llm.generate(self.SYSTEM, prompt)
            except LLMError as exc:
                tolerate(exc)
                self.failures += 1
                narrative = "(auditoria do LLM indisponível)"
        return AuditReport(stats, changes, narrative)


# --------------------------------------------------------------------------
# Interpretação de normas em linguagem natural e fachada
# --------------------------------------------------------------------------
_COMPARISON = {
    "type": "object",
    "properties": {
        "var": {"type": "string"},
        "op": {"type": "string", "enum": ["<", "<=", ">", ">=", "==", "!=", "in", "contains"]},
        "value": {"type": ["string", "number", "boolean"]},
    },
    "required": ["var", "op", "value"],
    "additionalProperties": False,
}
_CONDITION = {
    "type": "object",
    "properties": {
        "all_of": {"type": "array", "items": _COMPARISON},
        "any_of": {"type": "array", "items": _COMPARISON},
    },
    "required": ["all_of", "any_of"],
    "additionalProperties": False,
}
NORM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "description": {"type": "string"},
        "deontic": {"type": "string", "enum": [d.value for d in Deontic]},
        "addressee": {"type": "string"},
        "target": _CONDITION,
        "activation": _CONDITION,
        "parameters": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "value": {"type": "number"}},
                "required": ["name", "value"],
                "additionalProperties": False,
            },
        },
        "deadline": {"type": "integer"},
        "sanction": {"type": "number"},
    },
    "required": ["id", "description", "deontic", "addressee", "target", "activation", "parameters",
                 "deadline", "sanction"],
    "additionalProperties": False,
}


class LLMNormProcessor:
    """LLM-NormProcessor (ANA-ML 2.0): interpreta, gera e modifica normas."""

    INTERPRET_SYSTEM = (
        "Você é o LLM-NormProcessor. Converta uma norma escrita em linguagem natural para a "
        "representação estruturada do sistema. Condições são listas de comparações {var, op, value}; "
        "um value iniciado por '$' referencia um parâmetro da norma e '@' referencia outro campo do "
        "contexto. Para proibições e obrigações, 'target' descreve a ação regulada (o campo 'type' "
        "identifica a ação). 'activation' descreve quando a norma vale (listas vazias = sempre)."
    )

    def __init__(self, recommender: LLMNormRecommender | None = None, validator: LLMNormValidator | None = None,
                 auditor: LLMNormAuditor | None = None, llm: LLMClient | None = None) -> None:
        self.llm = llm
        self.recommender = recommender or LLMNormRecommender(llm)
        self.validator = validator or LLMNormValidator(llm=llm)
        self.auditor = auditor or LLMNormAuditor(llm)

    def interpret(self, text: str, vocabulary: str = "") -> Norm:
        if self.llm is None:
            raise RuntimeError("interpretar normas em linguagem natural requer um LLM")
        prompt = f"Norma:\n{text}\n\nVocabulário disponível (campos e ações):\n{vocabulary or '(livre)'}"
        data = self.llm.generate_json(self.INTERPRET_SYSTEM, prompt, NORM_SCHEMA)

        def cond(c: dict[str, Any]) -> Condition:
            return Condition.from_dict({
                "all_of": [[x["var"], x["op"], x["value"]] for x in c["all_of"]],
                "any_of": [[x["var"], x["op"], x["value"]] for x in c["any_of"]],
            })

        activation = cond(data["activation"])
        return Norm(
            id=data["id"],
            description=data["description"],
            deontic=Deontic(data["deontic"]),
            addressee=data["addressee"],
            target=cond(data["target"]),
            activation=activation if (activation.all_of or activation.any_of) else None,
            parameters={p["name"]: p["value"] for p in data["parameters"]},
            deadline=max(1, int(data["deadline"])),
            sanction=float(data["sanction"]),
        )
