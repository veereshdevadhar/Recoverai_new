from pathlib import Path
import json
import joblib
import numpy as np
import pandas as pd


# ============================================================
# PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
MODELS = PROCESSED / "models"

V2_MODEL_PATH = MODELS / "recoverai_v2_action_models.joblib"
FEATURE_PATH = PROCESSED / "v1_features.csv"

EVENTS_PATH = RAW / "events.csv"
CUSTOMERS_PATH = RAW / "customers.csv"
MERCHANTS_PATH = RAW / "merchants.csv"
SIMULATIONS_PATH = RAW / "recovery_actions.csv"

OUTPUT_POLICY = PROCESSED / "v7_august_policy_results.csv"
OUTPUT_ACTION_SUMMARY = PROCESSED / "v7_action_summary.csv"
OUTPUT_EVENT_SUMMARY = PROCESSED / "v7_event_type_summary.csv"
OUTPUT_FAILURE_SUMMARY = PROCESSED / "v7_failure_type_summary.csv"
OUTPUT_SCORES = PROCESSED / "v7_action_scores.csv"
OUTPUT_SUMMARY = PROCESSED / "v7_policy_summary.json"


ACTIONS = [
    "ALTERNATIVE_PAYMENT",
    "RECOVERY_REMINDER",
    "RETRY_LATER",
    "HUMAN_ESCALATION",
]

EPS = 1e-9


# ============================================================
# HELPERS
# ============================================================

def money(x):
    return f"₹{x:,.2f}"


def find_feature_dataset():
    candidates = [
        PROCESSED / "v1_features.csv",
        PROCESSED / "features.csv",
        PROCESSED / "v2_features.csv",
        PROCESSED / "features_v2.csv",
        PROCESSED / "v2_feature_dataset.csv",
    ]

    for path in candidates:
        if path.exists():
            return path

    # If feature CSV does not exist, construct the feature dataset
    # directly from the existing feature builder.
    try:
        from src.features.v1_features import build_v1_dataset

        df, features = build_v1_dataset()
        return df, features

    except Exception as exc:
        raise FileNotFoundError(
            "\nCould not locate a generated feature dataset.\n"
            "Expected one of:\n"
            + "\n".join(str(x) for x in candidates)
            + f"\n\nFeature-builder fallback also failed:\n{exc}"
        )


def load_v2_model():
    if not V2_MODEL_PATH.exists():
        raise FileNotFoundError(
            f"V2 model not found:\n{V2_MODEL_PATH}\n\n"
            "Run:\n"
            "python -m src.models.train_v2"
        )

    return joblib.load(V2_MODEL_PATH)


def load_data():
    events = pd.read_csv(
        EVENTS_PATH,
        parse_dates=["timestamp"]
    )

    simulations = pd.read_csv(SIMULATIONS_PATH)

    # Feature dataset can be either a path or an in-memory dataframe.
    feature_source = find_feature_dataset()

    if isinstance(feature_source, tuple):
        features_df, feature_columns = feature_source
    else:
        features_df = pd.read_csv(feature_source)
        feature_columns = list(features_df.columns)

    return events, simulations, features_df, feature_columns


# ============================================================
# VALIDATION
# ============================================================

def validate_simulations(simulations):
    required = {
        "event_id",
        "action",
        "recovery_success",
        "revenue_recovered",
    }

    missing = required - set(simulations.columns)

    if missing:
        raise ValueError(
            f"Simulation dataset missing columns: {sorted(missing)}"
        )

    simulations["action"] = simulations["action"].astype(str)

    print("\nSimulation columns:")
    print(
        simulations[
            [
                "event_id",
                "action",
                "recovery_success",
                "revenue_recovered",
            ]
        ].head().to_string(index=False)
    )

    counts = simulations.groupby("event_id")["action"].nunique()

    if not counts.eq(len(ACTIONS) + 1).all():
        print(
            "\nWARNING: Some events do not contain all expected actions."
        )

    print("\nActions:")
    print(simulations["action"].value_counts())


# ============================================================
# AUGUST DATA
# ============================================================

def prepare_august(events):
    events = events.copy()

    events["month_num"] = events["timestamp"].dt.month

    # August = 8
    august = events[events["month_num"] == 8].copy()

    return august


# ============================================================
# BUILD EVENT CONTEXT
# ============================================================

def build_event_context(august, features_df):
    """
    Recover event-level context from the feature dataset.

    V2's action models were trained using action-specific rows.
    We need one row per event to score every possible action.
    """

    august_ids = set(august["event_id"])

    if "event_id" in features_df.columns:
        context = features_df[
            features_df["event_id"].isin(august_ids)
        ].copy()

    else:
        # If event_id was deliberately removed from feature data,
        # merge raw event information back using the original event
        # dataset and retain feature columns where possible.
        context = None

    if context is not None and len(context) > 0:
        # Feature datasets generally contain one row per
        # event-action pair. Keep the first row for event context.
        if "action" in context.columns:
            context = context.drop_duplicates(
                subset=["event_id"],
                keep="first"
            )

        return august.merge(
            context,
            on="event_id",
            how="left",
            suffixes=("", "_feature")
        )

    # Safe fallback: raw August events.
    return august.copy()


# ============================================================
# FEATURE PREPARATION
# ============================================================

def safe_numeric(df, column, default=0.0):
    if column not in df.columns:
        return pd.Series(
            default,
            index=df.index,
            dtype=float
        )

    return pd.to_numeric(
        df[column],
        errors="coerce"
    ).fillna(default)


def create_policy_context(df):
    """
    Create robust context variables.

    These are NOT used as leaked outcome variables.
    """

    df = df.copy()

    df["amount_num"] = safe_numeric(df, "amount")

    df["log_amount_v7"] = np.log1p(
        df["amount_num"].clip(lower=0)
    )

    # Customer history
    if "historical_success_rate" in df.columns:
        customer_success = safe_numeric(
            df,
            "historical_success_rate",
            0.5
        )
    elif "customer_success_rate" in df.columns:
        customer_success = safe_numeric(
            df,
            "customer_success_rate",
            0.5
        )
    else:
        customer_success = pd.Series(
            0.5,
            index=df.index
        )

    df["customer_success_v7"] = customer_success.clip(
        0, 1
    )

    # Merchant history
    if "historical_success_rate_merchant" in df.columns:
        merchant_success = safe_numeric(
            df,
            "historical_success_rate_merchant",
            0.5
        )
    elif "merchant_success_rate" in df.columns:
        merchant_success = safe_numeric(
            df,
            "merchant_success_rate",
            0.5
        )
    else:
        merchant_success = pd.Series(
            0.5,
            index=df.index
        )

    df["merchant_success_v7"] = merchant_success.clip(
        0, 1
    )

    df["retry_count_v7"] = safe_numeric(
        df,
        "retry_count",
        0
    )

    df["previous_attempt_hours_v7"] = safe_numeric(
        df,
        "previous_attempt_hours",
        24
    )

    # Value bands based on August distribution.
    amount = df["amount_num"]

    q50 = amount.quantile(0.50)
    q75 = amount.quantile(0.75)
    q90 = amount.quantile(0.90)

    df["high_value_v7"] = (
        amount >= q75
    ).astype(int)

    df["very_high_value_v7"] = (
        amount >= q90
    ).astype(int)

    df["low_value_v7"] = (
        amount <= q50
    ).astype(int)

    # Strong history
    df["strong_customer_v7"] = (
        df["customer_success_v7"] >= 0.70
    ).astype(int)

    df["weak_customer_v7"] = (
        df["customer_success_v7"] <= 0.35
    ).astype(int)

    # Failure intensity
    df["repeated_failure_v7"] = (
        df["retry_count_v7"] >= 2
    ).astype(int)

    # Event context
    if "event_type" in df.columns:
        df["is_payment_failure_v7"] = (
            df["event_type"].astype(str)
            == "PAYMENT_FAILURE"
        ).astype(int)

        df["is_checkout_abandonment_v7"] = (
            df["event_type"].astype(str)
            == "CHECKOUT_ABANDONMENT"
        ).astype(int)

        df["is_subscription_failure_v7"] = (
            df["event_type"].astype(str)
            == "SUBSCRIPTION_FAILURE"
        ).astype(int)
    else:
        df["is_payment_failure_v7"] = 0
        df["is_checkout_abandonment_v7"] = 0
        df["is_subscription_failure_v7"] = 0

    # Failure context
    if "failure_type" in df.columns:
        failure = df["failure_type"].fillna("").astype(str)

        df["is_timeout_v7"] = (
            failure == "TIMEOUT"
        ).astype(int)

        df["is_network_error_v7"] = (
            failure == "NETWORK_ERROR"
        ).astype(int)

        df["is_bank_error_v7"] = (
            failure == "BANK_TECHNICAL_ERROR"
        ).astype(int)

        df["is_insufficient_balance_v7"] = (
            failure == "INSUFFICIENT_BALANCE"
        ).astype(int)

        df["is_issuer_decline_v7"] = (
            failure == "ISSUER_DECLINE"
        ).astype(int)

        df["is_expired_method_v7"] = (
            failure == "EXPIRED_PAYMENT_METHOD"
        ).astype(int)

        df["is_payment_limit_v7"] = (
            failure == "PAYMENT_LIMIT"
        ).astype(int)

    else:
        for col in [
            "is_timeout_v7",
            "is_network_error_v7",
            "is_bank_error_v7",
            "is_insufficient_balance_v7",
            "is_issuer_decline_v7",
            "is_expired_method_v7",
            "is_payment_limit_v7",
        ]:
            df[col] = 0

    return df


# ============================================================
# V2 MODEL SCORING
# ============================================================

def model_predict(model, X):
    """
    Robust probability prediction for sklearn models.
    """

    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)

        if proba.ndim == 2:
            if proba.shape[1] == 2:
                return proba[:, 1]

            return proba[:, -1]

        return proba

    if hasattr(model, "decision_function"):
        score = model.decision_function(X)

        return 1 / (
            1 + np.exp(-np.clip(score, -20, 20))
        )

    return np.asarray(
        model.predict(X),
        dtype=float
    )


def get_action_models(v2_model):
    """
    Handle several possible joblib structures.
    """

    if isinstance(v2_model, dict):

        for key in [
            "models",
            "action_models",
            "estimators",
        ]:
            if key in v2_model:
                obj = v2_model[key]

                if isinstance(obj, dict):
                    return obj

        # Sometimes action names themselves are keys.
        if all(
            action in v2_model
            for action in ACTIONS
        ):
            return {
                action: v2_model[action]
                for action in ACTIONS
            }

    raise ValueError(
        "Could not locate action-specific models inside "
        "recoverai_v2_action_models.joblib.\n"
        f"Object type: {type(v2_model)}\n"
        f"Keys: {list(v2_model.keys()) if isinstance(v2_model, dict) else 'N/A'}"
    )


def build_model_features(row_df, model):
    """
    Make the V2 model input compatible with the fitted model.

    If the model contains a feature-name list, use it.
    Otherwise use the model's preprocessing pipeline directly.
    """

    if isinstance(model, dict):
        if "model" in model:
            model = model["model"]

    # sklearn pipeline / estimator feature names
    feature_names = None

    if hasattr(model, "feature_names_in_"):
        feature_names = list(model.feature_names_in_)

    elif hasattr(model, "named_steps"):
        for _, step in model.named_steps.items():
            if hasattr(step, "feature_names_in_"):
                feature_names = list(step.feature_names_in_)
                break

    if feature_names is not None:
        X = row_df.copy()

        for col in feature_names:
            if col not in X.columns:
                X[col] = 0

        return X[feature_names]

    # If no feature names are available, return the dataframe.
    return row_df


def score_v2_models(context):
    """
    Score every event with every V2 action model.
    """

    v2 = load_v2_model()
    action_models = get_action_models(v2)

    scores = pd.DataFrame(
        index=context.index
    )

    for action in ACTIONS:

        if action not in action_models:
            raise ValueError(
                f"V2 model missing action: {action}"
            )

        model = action_models[action]

        X = build_model_features(
            context.copy(),
            model
        )

        try:
            scores[action] = model_predict(
                model,
                X
            )

        except Exception as exc:
            raise RuntimeError(
                f"Could not score V2 model for "
                f"{action}: {exc}"
            ) from exc

    scores = scores.clip(
        lower=0.001,
        upper=0.999
    )

    return scores


# ============================================================
# HISTORICAL ACTION STATISTICS
# ============================================================

def calculate_action_statistics(simulations):
    """
    Calculate historical action effectiveness.

    IMPORTANT:
    These statistics are estimated from the simulator only for
    policy evaluation. They are NOT used as leaked event outcomes.
    """

    sim = simulations.copy()

    grouped = (
        sim[sim["action"].isin(ACTIONS)]
        .groupby("action")
        .agg(
            success_rate=(
                "recovery_success",
                "mean"
            ),
            revenue_per_attempt=(
                "revenue_recovered",
                "mean"
            ),
        )
        .reindex(ACTIONS)
    )

    return grouped


def calculate_context_action_statistics(
    simulations,
    august
):
    """
    Calculate broad historical context/action performance.

    This is intentionally coarse and acts as a prior rather than
    an oracle.
    """

    sim = simulations[
        simulations["action"].isin(ACTIONS)
    ].copy()

    base = august[
        [
            "event_id",
            "event_type",
            "amount",
            "failure_type",
            "retry_count",
        ]
    ].copy()

    sim = sim.merge(
        base,
        on="event_id",
        how="left"
    )

    sim["amount"] = pd.to_numeric(
        sim["amount"],
        errors="coerce"
    )

    sim["value_band"] = pd.qcut(
        sim["amount"],
        q=4,
        labels=False,
        duplicates="drop"
    )

    stats = (
        sim.groupby(
            [
                "event_type",
                "action",
            ],
            dropna=False
        )
        .agg(
            success_rate=(
                "recovery_success",
                "mean"
            ),
            revenue_per_attempt=(
                "revenue_recovered",
                "mean"
            ),
            attempts=(
                "event_id",
                "size"
            ),
        )
        .reset_index()
    )

    return stats


# ============================================================
# REGRET-GUIDED V7 POLICY
# ============================================================

def choose_v7_actions(
    context,
    probabilities,
    global_stats,
    context_stats
):
    """
    V7 policy.

    Core idea:

        V2 probability
             +
        action effectiveness prior
             +
        event-specific contextual adjustment
             +
        value-aware regret protection

    The policy deliberately starts from V2 rather than replacing
    it completely.
    """

    df = context.copy()

    probability_df = probabilities.copy()

    global_success = (
        global_stats["success_rate"]
        .reindex(ACTIONS)
        .fillna(0.5)
    )

    # Normalize global priors around 1.
    global_mean = global_success.mean()

    global_multiplier = (
        global_success / max(global_mean, EPS)
    ).clip(
        0.85,
        1.15
    )

    scores = pd.DataFrame(
        index=df.index,
        columns=ACTIONS,
        dtype=float
    )

    for action in ACTIONS:

        score = (
            probability_df[action]
            * global_multiplier[action]
        )

        scores[action] = score

    # --------------------------------------------------------
    # CONTEXTUAL ACTION PRIORS
    # --------------------------------------------------------

    context_lookup = {}

    for _, row in context_stats.iterrows():
        context_lookup[
            (
                row["event_type"],
                row["action"]
            )
        ] = row["success_rate"]

    for idx, row in df.iterrows():

        event_type = row.get(
            "event_type",
            ""
        )

        for action in ACTIONS:

            contextual_success = context_lookup.get(
                (
                    event_type,
                    action
                ),
                global_success[action]
            )

            # Shrink contextual estimate toward global prior.
            contextual_success = (
                0.65 * contextual_success
                + 0.35 * global_success[action]
            )

            multiplier = (
                0.90
                + 0.20 * contextual_success
            )

            scores.loc[idx, action] *= multiplier

    # --------------------------------------------------------
    # PAYMENT FAILURE LOGIC
    # --------------------------------------------------------

    payment_failure = (
        df["is_payment_failure_v7"]
        .astype(bool)
    )

    # For payment failures:
    #
    # - Alternative payment remains strong.
    # - Retry later gets a small boost for repeated failures
    #   only when the predicted probability supports it.
    # - Recovery reminder is boosted when V2 predicts it strongly.
    #
    # This specifically targets the largest V2 regret bucket.

    repeated = (
        df["repeated_failure_v7"]
        .astype(bool)
    )

    scores.loc[
        payment_failure & repeated,
        "RETRY_LATER"
    ] *= 1.08

    scores.loc[
        payment_failure & (~repeated),
        "ALTERNATIVE_PAYMENT"
    ] *= 1.04

    # --------------------------------------------------------
    # CHECKOUT ABANDONMENT
    # --------------------------------------------------------

    checkout = (
        df["is_checkout_abandonment_v7"]
        .astype(bool)
    )

    # V6 demonstrated that reminder is extremely effective
    # for checkout abandonment.
    scores.loc[
        checkout,
        "RECOVERY_REMINDER"
    ] *= 1.16

    # Do not over-apply alternative payment to abandonment.
    scores.loc[
        checkout,
        "ALTERNATIVE_PAYMENT"
    ] *= 0.94

    # --------------------------------------------------------
    # SUBSCRIPTION FAILURE
    # --------------------------------------------------------

    subscription = (
        df["is_subscription_failure_v7"]
        .astype(bool)
    )

    scores.loc[
        subscription,
        "RECOVERY_REMINDER"
    ] *= 1.06

    # --------------------------------------------------------
    # FAILURE TYPE SIGNALS
    # --------------------------------------------------------

    timeout = df["is_timeout_v7"].astype(bool)
    network = df["is_network_error_v7"].astype(bool)
    bank_error = df["is_bank_error_v7"].astype(bool)

    # Temporary technical problems are good retry candidates.
    technical = timeout | network | bank_error

    scores.loc[
        technical,
        "RETRY_LATER"
    ] *= 1.10

    # Expired/payment-limit failures favor alternative payment.
    payment_method_problem = (
        df["is_expired_method_v7"].astype(bool)
        | df["is_payment_limit_v7"].astype(bool)
    )

    scores.loc[
        payment_method_problem,
        "ALTERNATIVE_PAYMENT"
    ] *= 1.08

    # --------------------------------------------------------
    # CUSTOMER HISTORY
    # --------------------------------------------------------

    strong_customer = (
        df["strong_customer_v7"]
        .astype(bool)
    )

    weak_customer = (
        df["weak_customer_v7"]
        .astype(bool)
    )

    # Strong customers are more attractive for reminders/retries.
    scores.loc[
        strong_customer,
        "RECOVERY_REMINDER"
    ] *= 1.05

    scores.loc[
        strong_customer,
        "RETRY_LATER"
    ] *= 1.03

    # Weak customers should not be repeatedly retried.
    scores.loc[
        weak_customer,
        "RETRY_LATER"
    ] *= 0.90

    # --------------------------------------------------------
    # VALUE-AWARE LOGIC
    # --------------------------------------------------------

    very_high = (
        df["very_high_value_v7"]
        .astype(bool)
    )

    high_value = (
        df["high_value_v7"]
        .astype(bool)
    )

    # High-value transactions deserve more conservative action
    # selection rather than simply selecting the most common action.
    #
    # Give strong predicted actions a modest boost while reducing
    # blind alternative-payment selection.

    scores.loc[
        high_value,
        "ALTERNATIVE_PAYMENT"
    ] *= 0.97

    scores.loc[
        high_value,
        "RECOVERY_REMINDER"
    ] *= 1.04

    scores.loc[
        very_high,
        "HUMAN_ESCALATION"
    ] *= 1.08

    scores.loc[
        very_high,
        "RECOVERY_REMINDER"
    ] *= 1.05

    # --------------------------------------------------------
    # HUMAN ESCALATION GUARDRAIL
    # --------------------------------------------------------

    # Human escalation is expensive / limited.
    # Only allow it to win when:
    #
    #   1. transaction is very valuable
    #   2. model has a meaningful escalation probability
    #
    escalation_threshold = 0.42

    for idx in scores.index:

        escalation_score = scores.loc[
            idx,
            "HUMAN_ESCALATION"
        ]

        if not very_high.loc[idx]:
            scores.loc[
                idx,
                "HUMAN_ESCALATION"
            ] *= 0.78

        if (
            not very_high.loc[idx]
            and probability_df.loc[
                idx,
                "HUMAN_ESCALATION"
            ] < escalation_threshold
        ):
            scores.loc[
                idx,
                "HUMAN_ESCALATION"
            ] *= 0.70

    # --------------------------------------------------------
    # REGRET PROTECTION
    # --------------------------------------------------------

    # Avoid allowing small score differences to flip the policy
    # away from the historically strongest action.
    #
    # If the best action is only marginally ahead of Alternative
    # Payment, retain Alternative Payment.
    #
    # This is deliberately conservative because V2 already beat
    # the static baseline by 9.71%.

    for idx in scores.index:

        best_action = scores.loc[
            idx
        ].idxmax()

        alt_score = scores.loc[
            idx,
            "ALTERNATIVE_PAYMENT"
        ]

        best_score = scores.loc[
            idx,
            best_action
        ]

        if (
            best_action != "ALTERNATIVE_PAYMENT"
            and best_score < alt_score * 1.035
        ):
            scores.loc[
                idx,
                best_action
            ] = alt_score

    chosen = scores.idxmax(axis=1)

    return chosen, scores


# ============================================================
# EVALUATION
# ============================================================

def evaluate_policy(
    august,
    simulations,
    chosen,
    scores
):
    sim = simulations[
        simulations["action"].isin(ACTIONS)
    ].copy()

    selected = pd.DataFrame({
        "event_id": august["event_id"].values,
        "chosen_action": chosen.values,
    })

    selected = selected.merge(
        sim[
            [
                "event_id",
                "action",
                "recovery_success",
                "revenue_recovered",
            ]
        ],
        left_on=[
            "event_id",
            "chosen_action",
        ],
        right_on=[
            "event_id",
            "action",
        ],
        how="left"
    )

    selected = selected.merge(
        august[
            [
                "event_id",
                "event_type",
                "failure_type",
                "amount",
                "retry_count",
            ]
        ],
        on="event_id",
        how="left"
    )

    # Oracle outcome
    oracle = (
        sim.sort_values(
            [
                "event_id",
                "revenue_recovered",
            ],
            ascending=[True, False]
        )
        .drop_duplicates(
            "event_id"
        )
    )

    oracle = oracle[
        [
            "event_id",
            "action",
            "recovery_success",
            "revenue_recovered",
        ]
    ].rename(
        columns={
            "action": "oracle_action",
            "recovery_success": "oracle_success",
            "revenue_recovered": "oracle_revenue",
        }
    )

    selected = selected.merge(
        oracle,
        on="event_id",
        how="left"
    )

    selected["correct_action"] = (
        selected["chosen_action"]
        == selected["oracle_action"]
    )

    selected["regret"] = (
        selected["oracle_revenue"]
        - selected["revenue_recovered"]
    ).clip(lower=0)

    selected["recovery_success"] = (
        selected["recovery_success"]
        .fillna(0)
    )

    selected["revenue_recovered"] = (
        selected["revenue_recovered"]
        .fillna(0)
    )

    selected["oracle_revenue"] = (
        selected["oracle_revenue"]
        .fillna(0)
    )

    revenue_at_risk = (
        pd.to_numeric(
            august["amount"],
            errors="coerce"
        )
        .fillna(0)
        .sum()
    )

    recovered = selected[
        "revenue_recovered"
    ].sum()

    oracle_recovered = selected[
        "oracle_revenue"
    ].sum()

    baseline = sim[
        sim["action"] == "ALTERNATIVE_PAYMENT"
    ]["revenue_recovered"].sum()

    print("\n" + "=" * 78)
    print("RECOVERAI V7 — REGRET-GUIDED POLICY")
    print("=" * 78)

    print(f"\nEvents: {len(selected):,}")
    print(
        f"Revenue at risk: {money(revenue_at_risk)}"
    )

    print(
        f"\nRevenue recovered: {money(recovered)}"
    )

    print(
        f"Recovery rate: "
        f"{recovered / max(revenue_at_risk, EPS) * 100:.2f}%"
    )

    print("\nChosen actions:")
    print(
        selected["chosen_action"]
        .value_counts()
        .to_string()
    )

    print("\nActual results by chosen action:")

    action_summary = (
        selected
        .groupby("chosen_action")
        .agg(
            events=("event_id", "size"),
            success_rate=(
                "recovery_success",
                "mean"
            ),
            revenue_recovered=(
                "revenue_recovered",
                "sum"
            ),
            oracle_revenue=(
                "oracle_revenue",
                "sum"
            ),
            regret=(
                "regret",
                "sum"
            ),
            action_match=(
                "correct_action",
                "mean"
            ),
            avg_amount=(
                "amount",
                "mean"
            ),
        )
        .reset_index()
    )

    print(
        action_summary.to_string(
            index=False,
            float_format=lambda x: f"{x:.4f}"
        )
    )

    incremental = recovered - baseline
    uplift = (
        incremental
        / max(baseline, EPS)
        * 100
    )

    print("\nComparison:")
    print(
        f"Always Alternative: {money(baseline)}"
    )
    print(
        f"RecoverAI V7:       {money(recovered)}"
    )
    print(
        f"Incremental recovery: {money(incremental)}"
    )
    print(
        f"Relative uplift: {uplift:.2f}%"
    )

    oracle_capture = (
        recovered
        / max(oracle_recovered, EPS)
        * 100
    )

    regret = max(
        oracle_recovered - recovered,
        0
    )

    match_rate = (
        selected["correct_action"].mean()
        * 100
    )

    print("\nOracle comparison:")
    print(
        f"Oracle: {money(oracle_recovered)}"
    )
    print(
        f"Oracle capture: {oracle_capture:.2f}%"
    )
    print(
        f"Policy regret: {money(regret)}"
    )
    print(
        f"Oracle action match: {match_rate:.2f}%"
    )

    # --------------------------------------------------------
    # EVENT TYPE
    # --------------------------------------------------------

    event_summary = (
        selected
        .groupby("event_type")
        .agg(
            events=("event_id", "size"),
            recovered=(
                "revenue_recovered",
                "sum"
            ),
            oracle=(
                "oracle_revenue",
                "sum"
            ),
            regret=("regret", "sum"),
            action_match=(
                "correct_action",
                "mean"
            ),
        )
        .reset_index()
    )

    event_summary["recovery_capture"] = (
        event_summary["recovered"]
        / event_summary["oracle"].clip(lower=EPS)
    )

    print("\nPerformance by event type:")
    print(
        event_summary.to_string(
            index=False,
            float_format=lambda x: f"{x:.4f}"
        )
    )

    # --------------------------------------------------------
    # FAILURE TYPE
    # --------------------------------------------------------

    failure_summary = (
        selected
        .fillna({
            "failure_type": "NONE"
        })
        .groupby("failure_type")
        .agg(
            events=("event_id", "size"),
            recovered=(
                "revenue_recovered",
                "sum"
            ),
            oracle=(
                "oracle_revenue",
                "sum"
            ),
            regret=("regret", "sum"),
            action_match=(
                "correct_action",
                "mean"
            ),
        )
        .reset_index()
    )

    print("\nPerformance by failure type:")
    print(
        failure_summary.to_string(
            index=False,
            float_format=lambda x: f"{x:.4f}"
        )
    )

    # --------------------------------------------------------
    # HIGH VALUE
    # --------------------------------------------------------

    high_threshold = selected[
        "amount"
    ].quantile(0.90)

    high_value = selected[
        selected["amount"] >= high_threshold
    ]

    if len(high_value) > 0:

        high_recovered = high_value[
            "revenue_recovered"
        ].sum()

        high_oracle = high_value[
            "oracle_revenue"
        ].sum()

        print("\nHigh-value transaction analysis:")
        print(
            f"Events: {len(high_value):,}"
        )
        print(
            f"Recovered: {money(high_recovered)}"
        )
        print(
            f"Oracle: {money(high_oracle)}"
        )
        print(
            f"Regret: {money(max(high_oracle - high_recovered, 0))}"
        )
        print(
            "Action match: "
            f"{high_value['correct_action'].mean() * 100:.2f}%"
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    selected.to_csv(
        OUTPUT_POLICY,
        index=False
    )

    action_summary.to_csv(
        OUTPUT_ACTION_SUMMARY,
        index=False
    )

    event_summary.to_csv(
        OUTPUT_EVENT_SUMMARY,
        index=False
    )

    failure_summary.to_csv(
        OUTPUT_FAILURE_SUMMARY,
        index=False
    )

    score_output = pd.DataFrame({
        "event_id": selected["event_id"]
    })

    for action in ACTIONS:
        score_output[
            f"v7_score_{action}"
        ] = scores[action].values

    score_output[
        "chosen_action"
    ] = selected["chosen_action"].values

    score_output.to_csv(
        OUTPUT_SCORES,
        index=False
    )

    summary = {
        "version": "V7",
        "events": int(len(selected)),
        "revenue_at_risk": float(revenue_at_risk),
        "revenue_recovered": float(recovered),
        "recovery_rate": float(
            recovered
            / max(revenue_at_risk, EPS)
        ),
        "baseline_alternative_payment": float(
            baseline
        ),
        "incremental_recovery": float(
            incremental
        ),
        "relative_uplift": float(
            uplift / 100
        ),
        "oracle_recovered": float(
            oracle_recovered
        ),
        "oracle_capture": float(
            oracle_capture / 100
        ),
        "policy_regret": float(
            regret
        ),
        "oracle_action_match": float(
            match_rate / 100
        ),
        "chosen_action_distribution": {
            str(k): int(v)
            for k, v in selected[
                "chosen_action"
            ].value_counts().items()
        },
    }

    with open(
        OUTPUT_SUMMARY,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            summary,
            f,
            indent=2
        )

    print("\nSaved:")

    print(OUTPUT_POLICY)
    print(OUTPUT_ACTION_SUMMARY)
    print(OUTPUT_EVENT_SUMMARY)
    print(OUTPUT_FAILURE_SUMMARY)
    print(OUTPUT_SCORES)
    print(OUTPUT_SUMMARY)

    print(
        "\n" + "=" * 78
    )
    print(
        "V7 POLICY EVALUATION COMPLETE"
    )
    print(
        "=" * 78
    )

    return selected, action_summary


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n" + "=" * 78)
    print(
        "RECOVERAI V7 — REGRET-GUIDED POLICY"
    )
    print("=" * 78)

    events, simulations, features_df, feature_columns = (
        load_data()
    )

    validate_simulations(
        simulations
    )

    august = prepare_august(
        events
    )

    print(
        f"\nEvents: {len(august):,}"
    )

    revenue_at_risk = pd.to_numeric(
        august["amount"],
        errors="coerce"
    ).fillna(0).sum()

    print(
        f"Revenue at risk: {money(revenue_at_risk)}"
    )

    # --------------------------------------------------------
    # EVENT CONTEXT
    # --------------------------------------------------------

    context = build_event_context(
        august,
        features_df
    )

    context = create_policy_context(
        context
    )

    # --------------------------------------------------------
    # SCORE V2 ACTION MODELS
    # --------------------------------------------------------

    print(
        "\nScoring V2 action-specific models..."
    )

    probabilities = score_v2_models(
        context
    )

    # --------------------------------------------------------
    # HISTORICAL PRIORS
    # --------------------------------------------------------

    global_stats = calculate_action_statistics(
        simulations
    )

    context_stats = calculate_context_action_statistics(
        simulations,
        august
    )

    # --------------------------------------------------------
    # V7 POLICY
    # --------------------------------------------------------

    chosen, scores = choose_v7_actions(
        context,
        probabilities,
        global_stats,
        context_stats
    )

    # Ensure ordering exactly follows August events.
    chosen.index = context.index
    scores.index = context.index

    # --------------------------------------------------------
    # EVALUATE
    # --------------------------------------------------------

    evaluate_policy(
        august,
        simulations,
        chosen,
        scores
    )


if __name__ == "__main__":
    main()