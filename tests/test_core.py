from llm_mas.core import Action, Agent, Environment, Perception, Simulation
from llm_mas.core.agent import LLMAgent
from llm_mas.llm import FunctionLLM, parse_actions
from llm_mas.llm.parsing import format_action


class Echo(Agent):
    """Responde a cada mensagem recebida com 'eco: <conteúdo>'."""

    def analyze_and_plan(self, p: Perception) -> list[Action]:
        return [Action.send(self.id, m.sender, f"eco: {m.content}") for m in p.messages]


class Starter(Agent):
    def analyze_and_plan(self, p: Perception) -> list[Action]:
        return [Action.send(self.id, "B", "oi")] if p.iteration == 1 else []


def test_messages_are_delivered_next_iteration():
    env = Environment()
    env.register(Starter("A", "x"))
    env.register(Echo("B", "y"))
    result = Simulation(env, 3).run()
    sends = [(a.iteration, a.agent, a.data["content"]) for a in result.actions]
    assert sends == [(1, "A", "oi"), (2, "B", "eco: oi")]
    assert "eco: oi" in env.agents["A"].knowledge.render()


def test_parse_actions_accepts_paper_format_and_missing_backslash():
    text = "pensando...\\begin{action}Agent4: Buy_Book: 18\\end{action} e begin{action}Agent2: oi\\end{action}"
    actions = parse_actions(text, "Agent1")
    assert [(a.data["receiver"], a.data["content"]) for a in actions] == [("Agent4", "Buy_Book: 18"), ("Agent2", "oi")]
    assert parse_actions(format_action("X", "y"), "Z")[0].data == {"receiver": "X", "content": "y"}


def test_llm_agent_prompt_contains_memory_and_messages():
    llm = FunctionLLM(lambda system, prompt, schema: format_action("B", "resposta"))

    class Talker(LLMAgent):
        pass

    env = Environment()
    env.register(Starter("B", "x"))
    talker = env.register(Talker("A", "falante", llm))
    env.agents["B"].analyze_and_plan = lambda p: [Action.send("B", "A", "olá A")] if p.iteration == 1 else []
    Simulation(env, 2).run()
    system, prompt = llm.calls[-1]
    assert "agente A" in system and "olá A" in prompt and "Iteração atual: 2 de 2" in prompt
    assert talker.last_output.startswith("\\begin{action}")
