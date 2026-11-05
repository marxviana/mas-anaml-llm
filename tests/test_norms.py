from llm_mas.core import Action, Agent, Environment, Perception, Simulation
from llm_mas.llm import FunctionLLM
from llm_mas.norms import (
    Condition,
    Deontic,
    LLMNormProcessor,
    LLMNormRecommender,
    LLMNormValidator,
    Norm,
    NormAdaptationEngine,
    NormKnowledgeBase,
    NormProposal,
    RejectAll,
    SafetyBound,
)


def alarm_norm(**kw) -> Norm:
    defaults = dict(
        id="N-LOW", description="alarmar se x < limite", deontic=Deontic.OBLIGATION, addressee="alerting",
        target=Condition.all(("type", "==", "alert")), activation=Condition.all(("x", "<", "$min")),
        parameters={"min": 10}, deadline=2, sanction=5, reward=1,
    )
    return Norm(**{**defaults, **kw})


def test_condition_params_and_field_refs():
    c = Condition.all(("x", "<", "$min"), ("receiver", "==", "@agent"))
    assert c.evaluate({"x": 3, "receiver": "A", "agent": "A"}, {"min": 5})
    assert not c.evaluate({"x": 3, "receiver": "B", "agent": "A"}, {"min": 5})
    assert not c.evaluate({"receiver": "A", "agent": "A"}, {"min": 5})  # campo ausente
    assert Condition.from_dict(c.to_dict()) == c


def test_override_replaces_general_norm_only_in_scope():
    kb = NormKnowledgeBase([alarm_norm()])
    proposal = NormProposal("N-LOW", {"min": 5}, persistence=2, scope_field="id", scope_value="P1")
    kb.put(proposal.build(kb), 1, "teste", "auto")
    assert [n.id for n in kb.applicable({"id": "P1"}, Deontic.OBLIGATION)] == ["N-LOW@P1"]
    assert [n.id for n in kb.applicable({"id": "P2"}, Deontic.OBLIGATION)] == ["N-LOW"]
    assert kb.get("N-LOW@P1").persistence == 2


class SensorEnv(Environment):
    def __init__(self, values):
        super().__init__()
        self.values = values

    def facts(self):
        return [{"id": "P1", "x": self.values[self.iteration - 1]}]


class Alerter(Agent):
    def __init__(self, comply: bool):
        super().__init__("Al", "alerting")
        self.comply = comply

    def analyze_and_plan(self, p: Perception):
        if not self.comply:
            return []
        return [Action(self.id, "alert", {"subject": ob.subject}) for ob in self.env.monitor.pending_for(self)]


def run_alarm(values, comply, **norm_kw):
    env = SensorEnv(values)
    env.use_norms(NormKnowledgeBase([alarm_norm(**norm_kw)]))
    env.register(Alerter(comply))
    return Simulation(env, len(values)).run(), env


def test_obligation_fulfilled_once_per_episode():
    result, env = run_alarm([5, 5, 5, 20, 5, 20], comply=True)
    alerts = [a.iteration for a in result.actions if a.type == "alert"]
    # ativação em t1 e t5 → alerta na iteração seguinte; não realarma enquanto a condição persiste
    assert alerts == [2, 6]
    assert env.agents["Al"].score == 2


def test_obligation_violated_when_deadline_expires():
    result, env = run_alarm([5, 20, 20, 20], comply=False)
    assert [(v.norm_id, v.iteration) for v in result.violations] == [("N-LOW", 3)]
    assert env.agents["Al"].score == -5


def test_persistence_filters_transient_readings():
    result, _ = run_alarm([5, 20, 5, 5, 20, 20], comply=True, persistence=2)
    assert [a.iteration for a in result.actions if a.type == "alert"] == [5]


def test_prohibition_with_field_reference():
    env = Environment()
    env.use_norms(NormKnowledgeBase([Norm("NO-SELF", "sem autoenvio", Deontic.PROHIBITION, "*",
                                          target=Condition.all(("type", "==", "send"), ("receiver", "==", "@agent")),
                                          sanction=3)]))

    class Selfish(Agent):
        def analyze_and_plan(self, p):
            return [Action.send(self.id, self.id, "comprei de mim mesmo")]

    env.register(Selfish("A", "x"))
    result = Simulation(env, 1).run()
    assert [v.norm_id for v in result.violations] == ["NO-SELF"]
    assert "VIOLOU a norma NO-SELF" in env.agents["A"].knowledge.render()


def test_validator_enforces_bounds_and_non_adaptable():
    kb = NormKnowledgeBase([alarm_norm(), alarm_norm(id="CRIT", adaptable=False)])
    v = LLMNormValidator([SafetyBound("N-LOW", "min", 8, 12)], max_persistence=3)
    assert v.validate(NormProposal("N-LOW", {"min": 9}), kb).ok
    assert not v.validate(NormProposal("N-LOW", {"min": 2}), kb).ok
    assert not v.validate(NormProposal("N-LOW", {"min": 9}, persistence=5), kb).ok
    assert not v.validate(NormProposal("N-LOW", {"other": 9}), kb).ok
    assert not v.validate(NormProposal("CRIT", {"min": 9}), kb).ok


def test_validator_rejects_unknown_scope_and_specific_base():
    kb = NormKnowledgeBase([alarm_norm()])
    v = LLMNormValidator(scope_values={"id": {"P1", "P2"}})
    assert v.validate(NormProposal("N-LOW", {"min": 9}, scope_field="id", scope_value="P1"), kb).ok
    assert not v.validate(NormProposal("N-LOW", {"min": 9}, scope_field="patient", scope_value="P1"), kb).ok
    assert not v.validate(NormProposal("N-LOW", {"min": 9}, scope_field="id", scope_value="P9"), kb).ok
    kb.put(NormProposal("N-LOW", {"min": 9}, scope_field="id", scope_value="P1").build(kb), 1, "", "auto")
    assert not v.validate(NormProposal("N-LOW@P1", {"min": 8}, scope_field="id", scope_value="P1"), kb).ok


def test_recommender_prompt_includes_rejection_history():
    llm = FunctionLLM(lambda s, p, schema: {"proposals": []})
    kb = NormKnowledgeBase([alarm_norm()])
    kb.record_rejection(5, "N-LOW@P1", None, "limiar abaixo do mínimo", "rejected_validation")
    LLMNormRecommender(llm).recommend(kb, {}, 10)
    assert "limiar abaixo do mínimo" in llm.calls[0][1] and "rejected_validation" in llm.calls[0][1]


def test_llm_validator_cannot_override_safety_bounds():
    approve_all = FunctionLLM(lambda s, p, schema: {"approve": True, "issues": []})
    kb = NormKnowledgeBase([alarm_norm()])
    v = LLMNormValidator([SafetyBound("N-LOW", "min", 8, 12)], llm=approve_all)
    assert not v.validate(NormProposal("N-LOW", {"min": 1}), kb).ok
    assert approve_all.calls == []


def test_llm_recommender_and_engine_with_supervisor():
    llm = FunctionLLM(lambda s, p, schema: {"proposals": [{
        "base_norm_id": "N-LOW", "scope_field": "id", "scope_value": "P1",
        "parameters": [{"name": "min", "value": 9}], "persistence": 2, "rationale": "baseline baixo",
    }]})
    processor = LLMNormProcessor(recommender=LLMNormRecommender(llm), validator=LLMNormValidator())

    kb = NormKnowledgeBase([alarm_norm()])
    changes = NormAdaptationEngine(kb, processor).adapt(10, {"evidência": 1})
    assert [c.norm_id for c in changes] == ["N-LOW@P1"] and kb.get("N-LOW@P1").parameters == {"min": 9}

    kb2 = NormKnowledgeBase([alarm_norm()])
    assert NormAdaptationEngine(kb2, processor, RejectAll()).adapt(10, {}) == []
    assert kb2.history[-1].status == "rejected_supervisor" and kb2.get("N-LOW@P1") is None


def test_interpret_natural_language_norm():
    llm = FunctionLLM(lambda s, p, schema: {
        "id": "NO-HIGH-PRICE", "description": "Vendedores não podem confirmar vendas acima de 100",
        "deontic": "prohibition", "addressee": "seller",
        "target": {"all_of": [{"var": "command", "op": "==", "value": "Confirm_sale"},
                              {"var": "price", "op": ">", "value": "$max_price"}], "any_of": []},
        "activation": {"all_of": [], "any_of": []},
        "parameters": [{"name": "max_price", "value": 100}], "deadline": 1, "sanction": 5,
    })
    norm = LLMNormProcessor(llm=llm).interpret("Vendedores não podem confirmar vendas acima de 100 reais")
    assert norm.deontic is Deontic.PROHIBITION and norm.activation is None
    assert norm.target.evaluate({"command": "Confirm_sale", "price": 120}, norm.parameters)
    assert not norm.target.evaluate({"command": "Confirm_sale", "price": 80}, norm.parameters)
