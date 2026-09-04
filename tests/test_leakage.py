from src.models.train_v2 import LEAKAGE


def test_known_outcome_columns_are_leakage_protected():
    forbidden = {'true_recovery_probability', 'simulated_success_probability', 'recovery_success', 'revenue_recovered'}
    assert forbidden.issubset(LEAKAGE)
