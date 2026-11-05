"""Marketplace de livros (arXiv:2307.06187, Seção IV).

Vendedores possuem livros idênticos e definem o preço; compradores querem
comprar um livro pelo menor preço. Uma venda se completa quando o comprador
envia ``Buy_Book: <preço>`` e o vendedor responde ``Confirm_sale: <preço>``.

Diferente do experimento original, o ambiente é normativo. As normas coíbem
os comportamentos indesejados relatados no artigo: agentes enviando mensagens
a si mesmos e fingindo ser clientes (Fig. 7), e confirmações sem pedido.
"""

from __future__ import annotations

import random
import re
from typing import Any

from llm_mas.core.agent import LLMAgent, Perception
from llm_mas.core.environment import Environment
from llm_mas.core.knowledge import Knowledge
from llm_mas.core.messages import Action
from llm_mas.core.simulation import Simulation, SimulationResult
from llm_mas.llm.base import LLMClient
from llm_mas.llm.parsing import format_action
from llm_mas.norms import Condition, Deontic, Norm, NormKnowledgeBase

# Um comando só tem efeito quando é a mensagem inteira: citar "Confirm_sale: 30"
# dentro de uma frase (p.ex. ao recusar uma nova venda) é conversa, não comando.
COMMAND_RE = re.compile(r"\s*(Buy_Book|Confirm_sale)\s*:?\s*\{?\s*\$?\s*(\d+(?:[.,]\d+)?)\s*\}?\s*\.?\s*",
                        re.IGNORECASE)
COMMAND_WORD_RE = re.compile(r"buy_book|confirm_sale", re.IGNORECASE)
CANONICAL = {"buy_book": "Buy_Book", "confirm_sale": "Confirm_sale"}
PRICE_RE = re.compile(r"\$\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*(?:reais|dólares|dolares)")
BUDGET = 50.0
# Regras do protocolo, explícitas no prompt: as políticas heurísticas já as
# seguem por construção, e o LLM precisa conhecê-las para a comparação ser justa.
MARKET_RULES = (
    "Comandos (Buy_Book e Confirm_sale) só têm efeito quando enviados sozinhos na mensagem, "
    "exatamente como 'Buy_Book: <preço>' ou 'Confirm_sale: <preço>'. Mencioná-los dentro de uma "
    "frase não tem efeito. Para conversar e enviar um comando ao mesmo agente, use duas ações.",
    "Mensagens enviadas em uma iteração chegam ao destinatário no início da iteração seguinte.",
    "Uma confirmação só gera venda se, naquele momento, o vendedor ainda tiver o livro e o comprador "
    "ainda não tiver comprado; se dois vendedores confirmarem ao mesmo comprador, vale o pedido mais antigo.",
)


def parse_command(content: str) -> tuple[str, float | None]:
    m = COMMAND_RE.fullmatch(content)
    if m:
        return CANONICAL[m.group(1).lower()], float(m.group(2).replace(",", "."))
    p = PRICE_RE.search(content)
    if p:
        return "chat", float((p.group(1) or p.group(2)).replace(",", "."))
    return "chat", None


def marketplace_norms() -> list[Norm]:
    send = ("type", "==", "send")
    return [
        Norm(
            "MKT-NO-SELF", "É proibido enviar mensagens para si mesmo.", Deontic.PROHIBITION, "*",
            target=Condition.all(send, ("receiver", "==", "@agent")), sanction=10,
        ),
        Norm(
            "MKT-NO-IMPERSONATION", "É proibido reproduzir ou forjar mensagens atribuídas a outro agente.",
            Deontic.PROHIBITION, "*",
            target=Condition(
                all_of=Condition.all(send).all_of,
                any_of=Condition.any(("content", "contains", "sent you this message"),
                                     ("content", "contains", "enviou esta mensagem")).any_of,
            ),
            sanction=10,
        ),
        Norm(
            "MKT-CONFIRM-NEEDS-ORDER",
            "Vendedores só podem enviar Confirm_sale a um comprador que lhes enviou Buy_Book com o mesmo preço.",
            Deontic.PROHIBITION, "seller",
            target=Condition.all(send, ("command", "==", "Confirm_sale"), ("has_order", "==", False)),
            sanction=5,
        ),
    ]


class MarketplaceEnv(Environment):
    """Disputas numa mesma rodada (um comprador confirmado por dois vendedores,
    ou um vendedor confirmando a dois compradores) são resolvidas por ordem de
    chegada do pedido ``Buy_Book``; empates, por sorteio da semente."""

    def __init__(self, seed: int | None = None) -> None:
        super().__init__("marketplace", seed)
        self.orders: dict[tuple[str, str], tuple[float, int]] = {}  # (comprador, vendedor) -> (preço, iteração)
        self.sales: list[dict[str, Any]] = []
        self.sold: set[str] = set()
        self.bought: set[str] = set()
        self._tiebreak_rng = random.Random(f"{seed}:market")

    @property
    def sellers(self) -> list[str]:
        return [a.id for a in self.agents_with_role("seller")]

    @property
    def buyers(self) -> list[str]:
        return [a.id for a in self.agents_with_role("buyer")]

    def apply_round(self, actions: list[Action]) -> None:
        sellers = set(self.sellers)
        for a in actions:
            if a.type == "send":
                a.data["command"], a.data["price"] = parse_command(a.data["content"])

        # 1. Confirmações valem contra os pedidos existentes no início da rodada.
        candidates = []
        for a in actions:
            if a.type != "send" or a.data["command"] != "Confirm_sale":
                continue
            seller, buyer, price = a.agent, a.data["receiver"], a.data["price"]
            order = self.orders.get((buyer, seller))
            a.data["has_order"] = order is not None and price is not None and abs(order[0] - price) < 0.01
            a.data["executed"] = False
            if a.data["has_order"]:
                candidates.append((order[1], a))
        candidates.sort(key=lambda c: (c[1].agent, c[1].data["receiver"]))  # base canônica para o sorteio
        for _, a in sorted(candidates, key=lambda c: (c[0], self._tiebreak_rng.random())):
            seller, buyer = a.agent, a.data["receiver"]
            if seller not in self.sold and buyer not in self.bought:
                self._complete_sale(seller, buyer, a.data["price"], a.iteration)
                a.data["executed"] = True

        # 2. Novos pedidos passam a valer a partir da próxima rodada.
        for a in sorted(actions, key=lambda a: a.agent):
            if a.type == "send" and a.data["command"] == "Buy_Book" and a.data["price"] is not None \
                    and a.data["receiver"] in sellers:
                self.orders[(a.agent, a.data["receiver"])] = (a.data["price"], a.iteration)
            self.apply(a)
            self._feedback(a, sellers)

    def _feedback(self, a: Action, sellers: set[str]) -> None:
        """Avisa o agente quando um comando não teve efeito (visto na próxima iteração)."""
        if a.type != "send":
            return
        receiver, command = a.data["receiver"], a.data["command"]
        if command == "chat" and COMMAND_WORD_RE.search(a.data["content"]):
            self.notify(a.agent, f"Sua mensagem a {receiver} cita um comando, mas não é só o comando; "
                                 "foi tratada como conversa e não teve efeito.")
        elif command == "Confirm_sale" and not a.data["executed"]:
            if not a.data["has_order"]:
                why = f"{receiver} não tinha pedido Buy_Book com esse preço para você"
            elif a.agent in self.sold:
                why = "seu livro já tinha sido vendido"
            else:
                why = f"{receiver} já tinha comprado de outro vendedor"
            self.notify(a.agent, f"Sua confirmação a {receiver} não gerou venda: {why}.")
        elif command == "Buy_Book" and receiver not in sellers:
            self.notify(a.agent, f"Buy_Book enviado a {receiver}, que não é vendedor; não teve efeito.")

    def public_state(self) -> dict[str, Any]:
        """Estado público do mercado, visto igualmente por agentes LLM e heurísticos."""
        return {"vendedores_que_já_venderam": sorted(self.sold),
                "compradores_que_já_compraram": sorted(self.bought)}

    def _complete_sale(self, seller: str, buyer: str, price: float, iteration: int) -> None:
        self.sold.add(seller)
        self.bought.add(buyer)
        self.sales.append({"seller": seller, "buyer": buyer, "price": price, "iteration": iteration})
        self.agents[seller].score += price  # pontuação do vendedor = preço de venda
        self.agents[buyer].score += BUDGET - price  # comprador: quanto economizou

    def metrics(self) -> dict[str, Any]:
        sends = [a for a in self.log if a.type == "send"]
        return {
            "sales": self.sales,
            "unsold_sellers": sorted(set(self.sellers) - self.sold),
            "buyers_without_book": sorted(set(self.buyers) - self.bought),
            "messages": len(sends),
            "self_messages": sum(1 for a in sends if a.data["receiver"] == a.agent),
            "llm_failures": self.state.get("llm_failures", 0),
        }


class SellerAgent(LLMAgent):
    def __init__(self, agent_id: str, llm: LLMClient | None = None) -> None:
        super().__init__(agent_id, "seller", llm, Knowledge())

    def system_prompt(self) -> str:
        env = self.env
        assert isinstance(env, MarketplaceEnv)
        self.knowledge.goals = [
            f"Você é {self.id}. Vendedores: {', '.join(env.sellers)}. Compradores: {', '.join(env.buyers)}.",
            "O objetivo dos vendedores é maximizar os ganhos.",
            f"O vendedor que não vender seu livro em {env.max_iterations} iterações perde.",
            "Você tem um livro e define o preço. Pode enviar mensagens a cada iteração.",
            "A venda se completa quando você recebe 'Buy_Book: <preço>' de um comprador e responde a ele "
            "com 'Confirm_sale: <preço>' (mesmo preço). Sua pontuação é o preço de venda.",
            *MARKET_RULES,
        ]
        return super().system_prompt()

    def sense(self, iteration: int) -> dict[str, Any]:
        env = self.env
        assert isinstance(env, MarketplaceEnv)
        return {"livro_vendido": self.id in env.sold, **env.public_state()}

    def should_deliberate(self, perception: Perception) -> bool:
        env = self.env
        assert isinstance(env, MarketplaceEnv)
        return self.id not in env.sold

    def heuristic(self, p: Perception) -> str:
        env = self.env
        assert isinstance(env, MarketplaceEnv)
        if self.id in env.sold:
            return ""
        b = self.knowledge.beliefs
        b.setdefault("price", round(self.rng.uniform(20, 40)))
        b.setdefault("reserve", round(self.rng.uniform(14, 20)))
        orders: dict[str, float] = b.setdefault("orders", {})
        for m in p.messages:
            command, price = parse_command(m.content)
            if command == "Buy_Book" and price is not None and m.sender not in env.bought:
                orders[m.sender] = price
        for buyer in list(orders):
            if buyer in env.bought:
                del orders[buyer]
        last = p.iteration >= (env.max_iterations or 3)
        if orders:
            buyer, price = max(orders.items(), key=lambda kv: kv[1])
            if price >= b["reserve"] or last:
                return format_action(buyer, f"Confirm_sale: {price:g}")
            b["price"] = max(b["reserve"], round((b["price"] + price) / 2))
            return format_action(buyer, f"Consigo fazer por ${b['price']}. Envie Buy_Book: {b['price']}.")
        if p.iteration > 1:
            b["price"] = max(b["reserve"], round(b["price"] * 0.85))
        return "".join(
            format_action(buyer, f"Tenho um livro à venda por ${b['price']}. Tem interesse?")
            for buyer in env.buyers if buyer not in env.bought
        )


class BuyerAgent(LLMAgent):
    def __init__(self, agent_id: str, llm: LLMClient | None = None) -> None:
        super().__init__(agent_id, "buyer", llm, Knowledge())

    def system_prompt(self) -> str:
        env = self.env
        assert isinstance(env, MarketplaceEnv)
        self.knowledge.goals = [
            f"Você é {self.id}. Vendedores: {', '.join(env.sellers)}. Compradores: {', '.join(env.buyers)}.",
            f"Seu objetivo é comprar um livro pelo melhor preço; seu orçamento é ${BUDGET:g}.",
            f"O comprador que não comprar um livro em {env.max_iterations} iterações perde.",
            "Para comprar, envie 'Buy_Book: <preço>' a um vendedor; a compra se completa quando ele "
            "responder 'Confirm_sale: <preço>' com o mesmo preço.",
            *MARKET_RULES,
        ]
        return super().system_prompt()

    def sense(self, iteration: int) -> dict[str, Any]:
        env = self.env
        assert isinstance(env, MarketplaceEnv)
        return {"livro_comprado": self.id in env.bought, **env.public_state()}

    def should_deliberate(self, perception: Perception) -> bool:
        env = self.env
        assert isinstance(env, MarketplaceEnv)
        return self.id not in env.bought

    def heuristic(self, p: Perception) -> str:
        env = self.env
        assert isinstance(env, MarketplaceEnv)
        if self.id in env.bought:
            return ""
        b = self.knowledge.beliefs
        b.setdefault("target", round(self.rng.uniform(15, 22)))
        quotes: dict[str, float] = b.setdefault("quotes", {})
        for m in p.messages:
            _, price = parse_command(m.content)
            if price is not None and m.sender in env.sellers:
                quotes[m.sender] = price
        quotes = {s: q for s, q in quotes.items() if s not in env.sold}
        b["quotes"] = quotes
        if not quotes:
            if p.iteration == 1:
                return "".join(format_action(s, "Olá, tenho interesse em comprar um livro. Qual o preço?")
                               for s in env.sellers)
            return ""
        seller, quote = min(quotes.items(), key=lambda kv: kv[1])
        last = p.iteration >= (env.max_iterations or 3) - 1
        offer = quote if (quote <= b["target"] or last) else max(b["target"], round(quote * 0.85))
        return format_action(seller, f"Buy_Book: {offer:g}")


def build_marketplace(llm: LLMClient | None = None, sellers: int = 3, buyers: int = 2,
                      seed: int | None = 0, normative: bool = True) -> MarketplaceEnv:
    env = MarketplaceEnv(seed)
    for i in range(1, sellers + 1):
        env.register(SellerAgent(f"Agent{i}", llm))
    for i in range(sellers + 1, sellers + buyers + 1):
        env.register(BuyerAgent(f"Agent{i}", llm))
    if normative:
        env.use_norms(NormKnowledgeBase(marketplace_norms()))
    return env


def run_marketplace(llm: LLMClient | None = None, iterations: int = 3, seed: int | None = 0,
                    normative: bool = True) -> SimulationResult:
    env = build_marketplace(llm, seed=seed, normative=normative)
    return Simulation(env, iterations).run()
