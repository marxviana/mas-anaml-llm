"""llm_mas — Sistemas Multiagentes com LLMs.

Implementa os temas do projeto "Engenharia de Software de Sistemas Multiagentes
para Tecnologias Emergentes" (PUC-Rio / University of Waterloo):

* ``core``      — agentes autoadaptativos com laço MAPE-K baseado em LLM
                  (Nascimento, Alencar & Cowan, arXiv:2307.06187).
* ``norms``     — sistemas multiagentes normativos adaptativos com LLM
                  (ANA-ML 2.0 / JSAN+AN — Tema 1).
* ``scenarios`` — estudos de caso: marketplace de livros, monitoramento de UTI
                  e simulação de gestão de projetos com contextos dinâmicos (Tema 2).
"""

from llm_mas.core import Action, Agent, Environment, Knowledge, LLMAgent, Message, Perception, Simulation

__all__ = [
    "Action",
    "Agent",
    "Environment",
    "Knowledge",
    "LLMAgent",
    "Message",
    "Perception",
    "Simulation",
]

__version__ = "0.1.0"
