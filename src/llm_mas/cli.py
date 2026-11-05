"""Linha de comando: ``python -m llm_mas <cenário> [opções]``.

Exemplos::

    python -m llm_mas marketplace
    python -m llm_mas icu --compare --seeds 0 1 2 3 4
    python -m llm_mas project --static
    python -m llm_mas icu --llm claude --effort low --iterations 60
    python -m llm_mas interpret "Vendedores não podem confirmar vendas acima de 100 reais"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_mas.core.simulation import SimulationResult
from llm_mas.llm import make_llm


def load_dotenv(path: Path = Path(".env")) -> None:
    """Carrega variáveis ``NOME=valor`` de um arquivo ``.env`` sem sobrescrever
    as já definidas no ambiente."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.removeprefix("export ").strip(), value.strip().strip("'\""))


def _require_credentials() -> None:
    has_env = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    has_profile = (Path.home() / ".config" / "anthropic").is_dir()
    if not (has_env or has_profile):
        sys.exit("Credenciais da API não encontradas. Crie o arquivo .env na pasta do projeto com\n"
                 "  ANTHROPIC_API_KEY=sk-ant-...\n(veja .env.example) ou faça `ant auth login`.")


def _llm(args: argparse.Namespace, **kwargs: Any):
    if args.llm == "claude":
        _require_credentials()
        return make_llm("claude", effort=args.effort, model=args.model, **kwargs)
    return make_llm("offline")


def _print_result(result: SimulationResult, verbose: bool) -> None:
    if verbose:
        for a in result.actions:
            if a.type == "send":
                print(f"[it {a.iteration}] {a.agent} → {a.data['receiver']}: {a.data['content']}")
            else:
                print(f"[it {a.iteration}] {a.agent} {a.type} {a.data}")
        print()
    for v in result.violations:
        print(f"[it {v.iteration}] VIOLAÇÃO {v.norm_id} por {v.agent}: {v.detail}")
    print("\nPontuações:", json.dumps(result.scores, ensure_ascii=False))
    print("Métricas:", json.dumps(result.metrics, ensure_ascii=False, indent=2))


def _dump(path: str | None, data: Any) -> None:
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nResultados salvos em {path}")


def cmd_marketplace(args: argparse.Namespace) -> None:
    from llm_mas.scenarios.marketplace import run_marketplace

    result = run_marketplace(_llm(args), iterations=args.iterations or 3, seed=args.seed,
                             normative=not args.no_norms)
    _print_result(result, verbose=True)
    _dump(args.json, {"metrics": result.metrics, "scores": result.scores})


def cmd_icu(args: argparse.Namespace) -> None:
    from llm_mas.norms import ConsoleSupervisor
    from llm_mas.scenarios.icu import compare_icu, run_icu

    llm = _llm(args)
    kwargs = {"patients": args.patients, "iterations": args.iterations or 120, "adapt_every": args.adapt_every,
              "decision_policy": args.decision}
    if args.compare:
        summary = compare_icu(llm, seeds=args.seeds, **kwargs)
        print(f"{'semente':>7} | {'alarmes falsos (estático → adaptativo)':>40} | {'sensibilidade':>15} | latência")
        for r in summary["runs"]:
            b, a = r["baseline"], r["adaptive"]
            print(f"{r['seed']:>7} | {b['false_alarms']:>19} → {a['false_alarms']:<18} | "
                  f"{b['sensitivity']} → {a['sensitivity']:<6} | {b['mean_latency']} → {a['mean_latency']}")
        print(f"\nRedução média de alarmes falsos: {summary['mean_false_alarm_reduction']}")
        if "paired_t" in summary:
            print(f"Teste t pareado: t = {summary['paired_t']} (gl = {summary['df']})")
        _dump(args.json, summary)
        return
    supervisor = ConsoleSupervisor() if args.human else None
    run = run_icu(llm, adaptive=not args.static, seed=args.seed, supervisor=supervisor, **kwargs)
    print("Métricas:", json.dumps(run.result.metrics, ensure_ascii=False, indent=2))
    if run.processor:
        print()
        print(run.processor.auditor.audit(run.env.norms, run.result.norm_events, run.result.metrics))
    _dump(args.json, {"metrics": run.result.metrics,
                      "norms": run.env.norms.snapshot() if run.env.norms else []})


def cmd_project(args: argparse.Namespace) -> None:
    from llm_mas.scenarios.project import run_project

    result, env = run_project(_llm(args), adaptive=not args.static, iterations=args.iterations or 60,
                              seed=args.seed, brief=args.brief)
    print(f"Cenário: {env.scenario.description}")
    _print_result(result, verbose=args.verbose)
    _dump(args.json, {"metrics": result.metrics, "scores": result.scores})


def cmd_interpret(args: argparse.Namespace) -> None:
    from llm_mas.norms import LLMNormProcessor

    if args.llm != "claude":
        sys.exit("interpretar normas em linguagem natural requer --llm claude")
    norm = LLMNormProcessor(llm=_llm(args)).interpret(args.text, args.vocabulary)
    print(json.dumps(norm.to_dict(), ensure_ascii=False, indent=2))


def cmd_dry_run(args: argparse.Namespace) -> None:
    from llm_mas.experiments import DryRunLLM, estimate_cost, run_comparison
    from llm_mas.llm.claude import PRICES

    out = Path(args.out or "results/dry-run")
    dry = DryRunLLM()
    run_comparison(dry, out, args.scenarios, args.seeds, args.iterations or 120, args.llm_decision,
                   args.llm_validator)
    price_in, price_out = PRICES[args.model]
    est = estimate_cost(dry, price_in, price_out)
    print(f"\nDRY-RUN (nenhuma chamada à API) — modelo {args.model}, preços US$ {price_in}/{price_out} por MTok")
    print(f"{'categoria':18} {'chamadas':>8} {'tokens entrada':>15} {'tokens saída*':>14} {'custo US$':>10}")
    for kind, k in sorted(est["by_kind"].items()):
        print(f"{kind:18} {k['calls']:>8} {k['input_tokens']:>15,.0f} {k['output_tokens']:>14,.0f} {k['cost_usd']:>10.2f}")
    print(f"{'TOTAL':18} {est['calls']:>8} {'':>15} {'':>14} {est['cost_usd']:>10.2f}")
    print("* saída estimada pelo observado com effort medium (teto); com effort low tende a ser menor.\n"
          "  Agentes LLM podem fazer um pouco mais ou menos chamadas que as políticas offline usadas aqui.")


def cmd_compare_llm(args: argparse.Namespace) -> None:
    from llm_mas.experiments import estimate_calls, run_comparison
    from llm_mas.llm.claude import BudgetExceeded

    if args.dry_run:
        cmd_dry_run(args)
        return
    _require_credentials()
    out = Path(args.out or f"results/{datetime.now():%Y%m%d-%H%M%S}")
    out.mkdir(parents=True, exist_ok=True)
    calls = estimate_calls(args.scenarios, args.seeds, args.iterations or 120, args.llm_decision, args.llm_validator)
    print(f"Cenários: {', '.join(args.scenarios)} | sementes {args.seeds} (execuções pareadas por semente)")
    print(f"Modelo {args.model}, effort {args.effort}; ~{calls} chamadas ao LLM; "
          f"limite de custo US$ {args.max_cost:.2f}. Saída em {out}/")
    llm = make_llm("claude", effort=args.effort, model=args.model, max_cost=args.max_cost,
                   transcript=out / "transcripts.jsonl")
    try:
        run_comparison(llm, out, args.scenarios, args.seeds, args.iterations or 120, args.llm_decision,
                       args.llm_validator)
    except BudgetExceeded as exc:
        sys.exit(f"Interrompido: {exc}. Resultados parciais em {out}/results.json")
    print((out / "report.md").read_text(encoding="utf-8"))


def cmd_deliberation(args: argparse.Namespace) -> None:
    from llm_mas.experiments import DryRunLLM, estimate_cost
    from llm_mas.experiments_phase2 import run_phase2
    from llm_mas.llm.claude import PRICES, BudgetExceeded

    out = Path(args.out or ("results/phase2-dry-run" if args.dry_run else f"results/phase2-{datetime.now():%Y%m%d-%H%M%S}"))
    if args.dry_run:
        llm = DryRunLLM() if args.llm == "claude" else None
    elif args.llm == "claude":
        _require_credentials()
        out.mkdir(parents=True, exist_ok=True)
        llm = make_llm("claude", effort=args.effort, model=args.model, max_cost=args.max_cost,
                       transcript=out / "transcripts.jsonl")
    else:
        llm = None
    try:
        run_phase2(llm, out, args.seeds, args.detections, args.sanctions, args.llm_detections, args.iterations or 120)
    except BudgetExceeded as exc:
        sys.exit(f"Interrompido: {exc}. Resultados parciais em {out}/results.json")
    if args.dry_run and llm is not None:
        price_in, price_out = PRICES[args.model]
        est = estimate_cost(llm, price_in, price_out)
        print(f"DRY-RUN (nenhuma chamada à API): {est['calls']} chamadas, custo estimado US$ {est['cost_usd']:.2f}")
        for kind, k in est["by_kind"].items():
            print(f"  {kind}: {k['calls']} chamadas, {k['input_tokens']:,.0f} tokens de entrada, "
                  f"{k['output_tokens']:,.0f} de saída, US$ {k['cost_usd']:.2f}")
        return
    print((out / "report.md").read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(prog="llm-mas", description="Sistemas multiagentes com LLMs")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--llm", choices=["offline", "claude"], default="offline",
                        help="offline = políticas determinísticas; claude = API do Claude")
    common.add_argument("--model", default="claude-opus-5-5")
    common.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"], default="medium")
    common.add_argument("--iterations", type=int)
    common.add_argument("--json", help="salvar resultados em um arquivo JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("marketplace", parents=[common], help="marketplace de livros (arXiv:2307.06187)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--no-norms", action="store_true", help="executa sem normas, como no artigo original")
    p.set_defaults(func=cmd_marketplace)

    p = sub.add_parser("icu", parents=[common], help="monitoramento de UTI com normas adaptativas (ANA-ML 2.0)")
    p.add_argument("--seed", "--seeds", dest="seeds", type=int, nargs="+", default=[0])
    p.add_argument("--patients", type=int, default=12)
    p.add_argument("--adapt-every", type=int, default=15)
    p.add_argument("--decision", choices=["news", "oracle"], default="news",
                   help="política offline do agente de decisão (oracle = rótulos perfeitos, só referência)")
    p.add_argument("--static", action="store_true", help="normas estáticas (sistema tradicional)")
    p.add_argument("--compare", action="store_true", help="compara estático × adaptativo nas sementes")
    p.add_argument("--human", action="store_true", help="supervisor humano aprova cada adaptação no terminal")
    p.set_defaults(func=cmd_icu)

    p = sub.add_parser("project", parents=[common], help="gestão de projetos com contextos dinâmicos (Tema 2)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--static", action="store_true", help="plano estático: o gerente não reage ao contexto")
    p.add_argument("--brief", default="", help="descrição do cenário para o gerador (com --llm claude)")
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=cmd_project)

    p = sub.add_parser("compare-llm", parents=[common], help="compara os cenários sem LLM × com LLM")
    p.add_argument("--scenarios", nargs="+", choices=["marketplace", "icu", "project"],
                   default=["marketplace", "icu", "project"])
    p.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    p.add_argument("--llm-decision", action="store_true", help="UTI: usa o LLM também no agente de decisão")
    p.add_argument("--llm-validator", action="store_true",
                   help="UTI: acrescenta a revisão do LLM ao validador (muda duas variáveis de uma vez)")
    p.add_argument("--max-cost", type=float, default=10.0, help="limite de custo estimado em US$")
    p.add_argument("--dry-run", action="store_true",
                   help="simula o experimento inteiro sem chamar a API e estima chamadas e custo")
    p.add_argument("--out", help="pasta de saída (padrão: results/<data-hora>)")
    p.set_defaults(func=cmd_compare_llm)

    p = sub.add_parser("deliberation", parents=[common],
                       help="fase 2: agentes que decidem cumprir ou violar normas (UTI)")
    p.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    p.add_argument("--detections", type=float, nargs="+", default=[0.3, 0.7, 1.0],
                   help="probabilidades de detecção para as estratégias offline")
    p.add_argument("--sanctions", type=float, nargs="+", default=[0.2, 1.0, 3.0],
                   help="escalas da sanção para as estratégias offline")
    p.add_argument("--llm-detections", type=float, nargs="+", default=[0.3, 0.7, 1.0],
                   help="probabilidades de detecção para a deliberação por LLM")
    p.add_argument("--max-cost", type=float, default=10.0)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--out")
    p.set_defaults(func=cmd_deliberation)

    p = sub.add_parser("interpret", parents=[common], help="converte uma norma em linguagem natural (LLM)")
    p.add_argument("text")
    p.add_argument("--vocabulary", default="")
    p.set_defaults(func=cmd_interpret)

    args = parser.parse_args(argv)
    if args.command == "icu":
        args.seed = args.seeds[0]
    args.func(args)


if __name__ == "__main__":
    main()
