#!/usr/bin/env python3
"""
PANOPTICON DARK KNIGHT — Main Entry Point
==========================================
CLI runner for the satellite-only foresight engine.

Usage:
    python -m panopticon.main                    # Run synthetic Dubai scenario
    python -m panopticon.main --scenario taiwan  # Run Taiwan scenario
    python -m panopticon.main --dashboard        # Launch Streamlit dashboard
    python -m panopticon.main --no-ethics        # Skip activation gate (testing)

"This is a contingency tool. Power like this demands restraint."
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from panopticon.config import PropagationWeights, SluiceConfig, ThreadingConfig
from panopticon.core.events import EventType, observables_to_seeds
from panopticon.core.propagator import BicycleChainPropagator
from panopticon.core.threading import DivergentThreader
from panopticon.ethics.protocol import EthicalProtocol
from panopticon.ingest.simulator import dubai_strike_scenario, taiwan_strait_scenario
from panopticon.oracle.insight import InsightOracle, format_report_text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("panopticon")


def run_scenario(
    scenario_name: str = "dubai",
    skip_ethics: bool = False,
    verbose: bool = False,
) -> str:
    """
    Run a full Panopticon analysis on a scenario.
    Returns the formatted oracle report.
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # --- Ethics gate ---
    if not skip_ethics:
        protocol = EthicalProtocol()
        if not protocol.activate("activate contingency"):
            print("ERROR: Activation failed.")
            sys.exit(1)
    else:
        print("\n  [ETHICS BYPASSED — testing mode]\n")

    # --- Ingest ---
    print("  [1/5] Ingesting satellite observables...")
    if scenario_name == "taiwan":
        sim = taiwan_strait_scenario()
    else:
        sim = dubai_strike_scenario()

    observables = sim.sorted_by_time()
    print(f"        {len(observables)} observables ingested from: {sim.name}")

    # --- Classify seeds ---
    print("  [2/5] Classifying event seeds...")
    seeds = observables_to_seeds(observables)
    for seed in seeds:
        print(f"        SEED: {seed.label} — intensity={seed.intensity:.2f} "
              f"conf={seed.confidence:.2f} obs={seed.metadata.get('cluster_size', '?')}")

    # --- Propagate ---
    print("  [3/5] Propagating bicycle chain...")
    propagator = BicycleChainPropagator(
        weights=PropagationWeights(),
        sluice=SluiceConfig(),
        threading=ThreadingConfig(top_k=20, max_depth=8),
    )
    graph = propagator.propagate_seeds(
        seeds,
        flagged_zones=[(25.01, 55.08, 20.0)] if scenario_name == "dubai" else [],
    )

    # Inject wildcard
    roots = graph.get_roots()
    if roots:
        propagator.inject_wildcard(
            roots[0].event_id,
            EventType.STRIKE_BARRAGE,
            "Secondary explosion — fuel depot",
            forced_propensity=0.15,
        )

    summary = graph.summary()
    print(f"        Graph: {summary['nodes']} nodes, {summary['edges']} edges, "
          f"max depth {summary['max_depth']}")

    # --- Thread divergent futures ---
    print("  [4/5] Threading divergent futures...")
    threader = DivergentThreader(config=ThreadingConfig(top_k=20))
    threads = threader.generate_threads(graph)

    # Inject user wildcard
    if roots:
        wc = threader.inject_user_wildcard(
            graph, roots[0].event_id,
            "Cyber false-flag disrupts port comms",
            EventType.MILITARY_ACTIVITY,
        )
        if wc:
            threads.append(wc)

    print(f"        {len(threads)} divergent futures generated")

    opt_count = sum(1 for t in threads if t.branch_type == "optimistic")
    pes_count = sum(1 for t in threads if t.branch_type == "pessimistic")
    wld_count = sum(1 for t in threads if t.branch_type == "wildcard")
    print(f"        Optimistic: {opt_count} | Pessimistic: {pes_count} | Wildcard: {wld_count}")

    # --- Oracle ---
    print("  [5/5] Consulting the Oracle...")
    oracle = InsightOracle(max_insights=10)
    report = oracle.generate_report(graph, threads, scenario_name=sim.name)

    report_text = format_report_text(report)
    print()
    print(report_text)

    # --- Cleanup ---
    if not skip_ethics:
        protocol.deactivate()

    return report_text


def main():
    parser = argparse.ArgumentParser(
        description="PANOPTICON DARK KNIGHT — Satellite foresight engine",
    )
    parser.add_argument(
        "--scenario", "-s",
        choices=["dubai", "taiwan"],
        default="dubai",
        help="Which scenario to run (default: dubai)",
    )
    parser.add_argument(
        "--dashboard", "-d",
        action="store_true",
        help="Launch Streamlit dashboard instead of CLI",
    )
    parser.add_argument(
        "--no-ethics",
        action="store_true",
        help="Skip ethics activation gate (testing only)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()

    if args.dashboard:
        import subprocess
        subprocess.run([
            sys.executable, "-m", "streamlit", "run",
            "panopticon/dashboard/app.py",
            "--theme.backgroundColor", "#0a0a0a",
            "--theme.secondaryBackgroundColor", "#111111",
            "--theme.textColor", "#e0e0e0",
            "--theme.primaryColor", "#4da6ff",
        ])
    else:
        run_scenario(
            scenario_name=args.scenario,
            skip_ethics=args.no_ethics,
            verbose=args.verbose,
        )


if __name__ == "__main__":
    main()
