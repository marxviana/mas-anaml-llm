import itertools

from llm_mas.core import Simulation
from llm_mas.core.messages import Action
from llm_mas.llm import FunctionLLM
from llm_mas.llm.parsing import format_action
from llm_mas.norms import NormKnowledgeBase
from llm_mas.scenarios.icu import run_icu
from llm_mas.scenarios.marketplace import BuyerAgent, MarketplaceEnv, SellerAgent, marketplace_norms

IDS = ["Agent1", "Agent2", "Agent3", "Agent4", "Agent5"]


def market(order, seed, llm=None, parallel=None):
    env = MarketplaceEnv(seed)
    agents = {i: SellerAgent(i, llm) if int(i[-1]) <= 3 else BuyerAgent(i, llm) for i in IDS}
    for i in order:
        env.register(agents[i])
    env.use_norms(NormKnowledgeBase(marketplace_norms()))
    result = Simulation(env, 3, parallel=parallel).run()
    sends = sorted((a.iteration, a.agent, a.data["receiver"], a.data["content"]) for a in result.actions)
    return result.metrics["sales"], sends, result.scores


def test_marketplace_outcome_does_not_depend_on_registration_order():
    for seed in range(8):
        reference = market(IDS, seed)
        for order in itertools.islice(itertools.permutations(IDS), 0, 120, 17):
            assert market(list(order), seed) == reference


def test_parallel_and_sequential_decisions_match():
    assert market(IDS, 3, parallel=True) == market(IDS, 3, parallel=False)


def test_mailbox_position_is_not_tied_to_sender_identity():
    firsts = set()
    for seed in range(30):
        env = MarketplaceEnv(seed)
        for i in IDS:
            env.register(SellerAgent(i))
        for sender in IDS[1:]:
            env.post_action = None
            env.apply(Action.send(sender, "Agent1", "oi"))
        env.deliver()
        firsts.add(env.collect("Agent1")[0].sender)
    assert len(firsts) > 1


def test_simultaneous_confirmations_follow_first_come_first_served():
    """Agent4 pediu a Agent1 na it. 1 e a Agent2 na it. 2; ambos confirmam na it. 3:
    vale o pedido mais antigo, e a outra confirmação não gera venda nem violação."""

    def script(system, prompt, schema):
        it = int(prompt.split("Iteração atual: ")[1].split()[0])
        me = system.split("agente ")[1].split()[0]
        plan = {
            ("Agent4", 1): format_action("Agent1", "Buy_Book: 30"),
            ("Agent4", 2): format_action("Agent2", "Buy_Book: 25"),
            ("Agent1", 3): format_action("Agent4", "Confirm_sale: 30"),
            ("Agent2", 3): format_action("Agent4", "Confirm_sale: 25"),
        }
        return plan.get((me, it), "")

    for order in (IDS, IDS[::-1]):
        sales, _, _ = market(order, 0, FunctionLLM(script))
        assert [(s["seller"], s["price"]) for s in sales] == [("Agent1", 30.0)]


def test_icu_alarm_records_the_reading_that_triggered_each_norm():
    run = run_icu(adaptive=False, iterations=60, seed=0, decision_policy="oracle")
    kb = run.env.norms
    assert run.env.alarms
    for alarm in run.env.alarms:
        assert alarm["reading_iteration"] == alarm["iteration"] - 1  # o alarme soa na iteração seguinte
        patient = run.env.patients[alarm["patient"]]
        assert alarm["true"] == patient.in_episode(alarm["reading_iteration"])
        for norm_id, trig in alarm["triggers"].items():
            norm = kb.get(norm_id)
            assert norm.activation.evaluate({"id": alarm["patient"], **trig["vitals"]}, norm.parameters)
    assessed = [a for a in run.env.alarms if a["verdict"] is not None]
    assert assessed and all(a["verdict"] == a["true"] for a in assessed)
