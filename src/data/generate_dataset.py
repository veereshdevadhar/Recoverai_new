from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.customer_generator import generate_customers
from src.data.merchant_generator import generate_merchants
from src.data.event_generator import generate_events
from src.data.recovery_simulator import simulate_action, ACTIONS
from src.data.validator import validate_events


def main(n_events: int = 100_000, seed: int = 44):
    """Generate the synthetic RecoverAI benchmark.

    The project benchmark is intentionally large enough to support meaningful
    model training while keeping the complete stack free and reproducible.
    """
    raw = ROOT / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    # Keep entity cardinality proportional to the event volume so the model sees
    # diverse customer and merchant histories instead of repeatedly observing a
    # tiny fixed population.
    customers = generate_customers(n=max(2_000, n_events // 50))
    merchants = generate_merchants(n=max(200, n_events // 500))
    events = generate_events(customers, merchants, n=n_events, seed=seed)
    outcomes = simulate_action(events, ACTIONS, seed=seed + 1)

    validate_events(events)

    customers.to_csv(raw / "customers.csv", index=False)
    merchants.to_csv(raw / "merchants.csv", index=False)
    events.to_csv(raw / "events.csv", index=False)
    outcomes.to_csv(raw / "recovery_actions.csv", index=False)

    print(f"Generated {len(customers):,} customers")
    print(f"Generated {len(merchants):,} merchants")
    print(f"Generated {len(events):,} events")
    print(f"Generated {len(outcomes):,} action simulations")
    print("\nEvent distribution:")
    print(events["event_type"].value_counts())
    print("\nRecovery success rate by action:")
    print(outcomes.groupby("action")["recovery_success"].mean().round(4))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the RecoverAI synthetic benchmark")
    parser.add_argument("--events", type=int, default=100_000, help="Number of payment-risk events (default: 100000)")
    parser.add_argument("--seed", type=int, default=44, help="Random seed")
    args = parser.parse_args()
    if args.events < 1_000:
        raise SystemExit("--events must be at least 1000")
    main(args.events, args.seed)
