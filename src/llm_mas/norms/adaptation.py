"""Norm Adaptation Engine com supervisão humana (ANA-ML 2.0, Seção III-C).

Ciclo de adaptação contínua: monitoramento (evidências do ambiente) →
avaliação/recomendação (LLM-NormRecommender) → validação (LLM-NormValidator)
→ supervisão humana → implantação na base de normas.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from llm_mas.norms.knowledge_base import NormChange, NormKnowledgeBase
from llm_mas.norms.llm_components import LLMNormProcessor, NormProposal, ValidationResult

if TYPE_CHECKING:
    from llm_mas.core.environment import Environment


@dataclass(frozen=True)
class ReviewDecision:
    approved: bool
    reviewer: str
    notes: str = ""


class HumanSupervisor(Protocol):
    def review(self, proposal: NormProposal, validation: ValidationResult) -> ReviewDecision: ...


class AutoApprove:
    """Aprova toda proposta que passou na validação (simulações em lote)."""

    def review(self, proposal: NormProposal, validation: ValidationResult) -> ReviewDecision:
        return ReviewDecision(True, "auto")


class RejectAll:
    def review(self, proposal: NormProposal, validation: ValidationResult) -> ReviewDecision:
        return ReviewDecision(False, "reject-all")


class ConsoleSupervisor:
    """Pergunta a um especialista humano no terminal."""

    def __init__(self, name: str = "especialista") -> None:
        self.name = name

    def review(self, proposal: NormProposal, validation: ValidationResult) -> ReviewDecision:
        print(f"\nProposta para {proposal.target_id}: parâmetros={proposal.parameters} "
              f"persistência={proposal.persistence}\n  Justificativa: {proposal.rationale}")
        answer = input("Aprovar? [s/N] ").strip().lower()
        return ReviewDecision(answer in ("s", "sim", "y", "yes"), self.name)


class NormAdaptationEngine:
    def __init__(self, kb: NormKnowledgeBase, processor: LLMNormProcessor,
                 supervisor: HumanSupervisor | None = None, every: int = 10) -> None:
        self.kb = kb
        self.processor = processor
        self.supervisor = supervisor or AutoApprove()
        self.every = every

    def maybe_adapt(self, iteration: int, env: Environment) -> list[NormChange]:
        if iteration % self.every:
            return []
        evidence_fn = getattr(env, "adaptation_evidence", None)
        evidence: dict[str, Any] = evidence_fn() if evidence_fn else {}
        return self.adapt(iteration, evidence)

    def adapt(self, iteration: int, evidence: dict[str, Any]) -> list[NormChange]:
        applied: list[NormChange] = []
        for proposal in self.processor.recommender.recommend(self.kb, evidence, iteration):
            validation = self.processor.validator.validate(proposal, self.kb)
            if not validation.ok:
                self.kb.record_rejection(iteration, proposal.target_id, None,
                                         f"{proposal.rationale} | " + "; ".join(validation.issues),
                                         "rejected_validation")
                continue
            candidate = proposal.build(self.kb)
            decision = self.supervisor.review(proposal, validation)
            if not decision.approved:
                self.kb.record_rejection(iteration, proposal.target_id, candidate,
                                         f"{proposal.rationale} | {decision.notes}", "rejected_supervisor")
                continue
            applied.append(self.kb.put(candidate, iteration, proposal.rationale, decision.reviewer))
        return applied
