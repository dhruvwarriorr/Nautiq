"""Train-only residual candidates, tuning selection and explicit release refusal."""

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import lightgbm as lgb
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from ..argo.evidence import canonical
from ..argo.storage import digest
from ..climatology.grid import VARIABLES, instant
from ..climatology.model import band, fit as fit_reference, predict as baseline, region
from .features import NAMES, VERSION, audit_partitions, vector

METHOD = "residual-expected-mean-v1"
SPLITS = ("train", "tune", "calibration", "test")


def load_policy(path):
    p = json.loads(Path(path).read_bytes())
    if (
        p.get("schema_version") != 1
        or p.get("method_version") != METHOD
        or p.get("feature_version") != VERSION
        or p.get("features") != list(NAMES)
        or p.get("release_approved") is not False
        or not 1 <= p["max_rounds"] <= 200
        or not 2 <= p["early_stopping_rounds"] <= 30
        or p["leaves"] != [7, 15]
        or not 0 < p["learning_rate"] <= 0.2
        or not 5 <= p["min_samples_leaf"] <= 100
        or not 0 <= p["l2_regularization"] <= 100
        or not 20 <= p["min_train_profiles"] <= 2000
        or not 10 <= p["min_tune_profiles"] <= 2000
        or not 10 <= p["min_test_profiles"] <= 2000
        or not 10 <= p["min_subgroup_profiles"] <= 2000
        or not 1 <= p["max_profiles"] <= 2000
        or not 1 <= p["max_rows"] <= 32000
        or not 10 <= p["bootstrap_replicates"] <= 1000
        or not 1 <= p["audit_cell_degrees"] <= 10
        or not 0 < p["spatial_buffer_degrees"] <= 5
        or p["spatial_folds"] != 2
        or p["platform_folds"] != 2
    ):
        raise ValueError("invalid_expected_policy")
    gate = p["promotion"]
    if (
        any(
            type(gate[name]) is not bool
            for name in (
                "untouched_test",
                "independence_audits_approved",
                "source_and_coverage_approved",
            )
        )
        or (
            gate["reviewed_gate_id"] is not None
            and (
                not isinstance(gate["reviewed_gate_id"], str)
                or not gate["reviewed_gate_id"].strip()
            )
        )
        or not 0 < gate["min_relative_profile_mae_improvement"] < 1
        or not 0 <= gate["max_subgroup_relative_regression"] <= 0.5
        or any(not 0 < gate["max_absolute_bias"][v] < 5 for v in VARIABLES)
    ):
        raise ValueError("invalid_promotion_policy")
    return p


def weights(rows):
    count = Counter(r["profile_id"] for r in rows)
    return np.asarray([1 / count[r["profile_id"]] for r in rows])


def eligible(grid, variable, reference):
    rows, means = [], []
    for row in grid:
        value = baseline(row, variable, reference)["expected_mean"]
        if row[variable] is not None and value is not None:
            rows.append(row)
            means.append(value)
    return rows, np.asarray(means)


def score(rows, truth, predicted, p):
    count = len(rows)
    if not count:
        return {
            "rows": 0,
            "profiles": 0,
            "mae": None,
            "rmse": None,
            "median_absolute_error": None,
            "bias": None,
            "profile_weighted_mae": None,
            "profile_bootstrap_mae_95": None,
        }
    error = np.asarray(truth) - np.asarray(predicted)
    if not np.isfinite(error).all():
        raise ValueError("nonfinite_model_output")
    groups = defaultdict(list)
    for r, e in zip(rows, error, strict=True):
        groups[r["profile_id"]].append(abs(float(e)))
    means = np.asarray([np.mean(es) for _, es in sorted(groups.items())])
    interval = None
    if len(means) >= 3:
        rng = np.random.default_rng(p["seed"])
        interval = np.quantile(
            [
                rng.choice(means, len(means), replace=True).mean()
                for _ in range(p["bootstrap_replicates"])
            ],
            [0.025, 0.975],
        ).tolist()
    return {
        "rows": count,
        "profiles": len(means),
        "mae": float(np.abs(error).mean()),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "median_absolute_error": float(np.median(np.abs(error))),
        "bias": float(error.mean()),
        "profile_weighted_mae": float(means.mean()),
        "profile_bootstrap_mae_95": interval,
    }


def evaluate(rows, means, predictions, variable, reference, p):
    report = {}
    for split in SPLITS:
        mask = np.asarray([r["split"] == split for r in rows], dtype=bool)
        selected = [r for r, take in zip(rows, mask, strict=True) if take]
        truth = np.asarray([r[variable] for r in selected])
        names = {"overall": np.ones(len(selected), dtype=bool)}
        for area in ("arabian", "bay_bengal"):
            names[f"region:{area}"] = np.asarray(
                [region(r, reference["policy"]) == area for r in selected], dtype=bool
            )
        for i, (a, b) in enumerate(reference["policy"]["depth_bands_m"]):
            names[f"depth_band:{a}-{b}m"] = np.asarray(
                [band(r["depth_m"], reference["policy"]) == i for r in selected],
                dtype=bool,
            )
        for name, months in (
            ("DJF", (12, 1, 2)),
            ("MAM", (3, 4, 5)),
            ("JJA", (6, 7, 8)),
            ("SON", (9, 10, 11)),
        ):
            names[f"season:{name}"] = np.asarray(
                [instant(r["observed_at"]).month in months for r in selected],
                dtype=bool,
            )
        for z in reference["policy"]["standard_depths_m"]:
            names[f"depth:{z}m"] = np.asarray(
                [r["depth_m"] == z for r in selected], dtype=bool
            )
        report[split] = {
            family: {
                name: score(
                    [r for r, take in zip(selected, take, strict=True) if take],
                    truth[take],
                    np.asarray(values)[mask][take],
                    p,
                )
                for name, take in names.items()
            }
            for family, values in {"climatology": means, **predictions}.items()
        }
    return report


def train_variable(grid, variable, reference, p):
    rows, means = eligible(grid, variable, reference)
    masks = {s: np.asarray([r["split"] == s for r in rows], dtype=bool) for s in SPLITS}
    counts = {
        s: len({r["profile_id"] for r in rows if r["split"] == s}) for s in SPLITS
    }
    if (
        counts["train"] < p["min_train_profiles"]
        or counts["tune"] < p["min_tune_profiles"]
    ):
        return {
            "status": "unsupported",
            "profile_counts": counts,
            "reason": "insufficient_training_or_tuning_profiles",
        }, {}
    x = np.asarray([vector(r, reference["policy"]) for r in rows])
    truth = np.asarray([r[variable] for r in rows])
    residual = truth - means
    train_rows = [r for r in rows if r["split"] == "train"]
    tune_rows = [r for r in rows if r["split"] == "tune"]
    wt, wv = weights(train_rows), weights(tune_rows)
    candidates, predictions, selected = {}, {}, {}

    def tune_mae(predicted, data):
        return (
            "profile_weighted_mae",
            float(np.sum(wv * np.abs(data.get_label() - predicted)) / wv.sum()),
            False,
        )

    with threadpool_limits(limits=1):
        for family in ("lightgbm", "hgbr"):
            choices = []
            for leaves in p["leaves"]:
                if family == "lightgbm":
                    params = {
                        "objective": "regression",
                        "metric": "None",
                        "num_leaves": leaves,
                        "learning_rate": p["learning_rate"],
                        "min_data_in_leaf": p["min_samples_leaf"],
                        "lambda_l2": p["l2_regularization"],
                        "num_threads": 1,
                        "deterministic": True,
                        "force_col_wise": True,
                        "seed": p["seed"],
                        "verbosity": -1,
                    }
                    train = lgb.Dataset(
                        x[masks["train"]],
                        label=residual[masks["train"]],
                        weight=wt,
                        feature_name=list(NAMES),
                    )
                    tune = lgb.Dataset(
                        x[masks["tune"]],
                        label=residual[masks["tune"]],
                        weight=wv,
                        reference=train,
                    )
                    model = lgb.train(
                        params,
                        train,
                        num_boost_round=p["max_rounds"],
                        valid_sets=[tune],
                        feval=tune_mae,
                        callbacks=[
                            lgb.early_stopping(
                                p["early_stopping_rounds"], verbose=False
                            )
                        ],
                    )
                    predicted = means + model.predict(
                        x, num_iteration=model.best_iteration, num_threads=1
                    )
                    artifact = model.model_to_string(num_iteration=model.best_iteration)
                    config = {**params, "best_iteration": model.best_iteration}
                else:
                    config = {
                        "max_iter": p["max_rounds"],
                        "max_leaf_nodes": leaves,
                        "learning_rate": p["learning_rate"],
                        "min_samples_leaf": p["min_samples_leaf"],
                        "l2_regularization": p["l2_regularization"],
                        "early_stopping": False,
                        "random_state": p["seed"],
                    }
                    model = HistGradientBoostingRegressor(**config).fit(
                        x[masks["train"]], residual[masks["train"]], sample_weight=wt
                    )
                    predicted = means + model.predict(x)
                    artifact = (
                        None  # Never serialize or load an executable sklearn pickle.
                    )
                metric = score(
                    tune_rows, truth[masks["tune"]], predicted[masks["tune"]], p
                )
                choices.append(
                    (
                        metric["profile_weighted_mae"],
                        leaves,
                        predicted,
                        artifact,
                        config,
                    )
                )
            best = min(choices, key=lambda c: (c[0], c[1]))
            predictions[family] = best[2]
            selected[family] = {
                "leaves": best[1],
                "tuning_profile_weighted_mae": best[0],
                "parameters": best[4],
            }
            candidates[family] = [
                {
                    "leaves": c[1],
                    "tuning_profile_weighted_mae": c[0],
                    "parameters": c[4],
                }
                for c in choices
            ]
            if family == "lightgbm":
                text = best[3]
    geometry = {
        k: [min(r[k] for r in train_rows), max(r[k] for r in train_rows)]
        for k in ("latitude", "longitude", "depth_m")
    }
    model = {
        "model_text": text,
        "model_sha256": digest(text.encode()),
        "feature_names": list(NAMES),
        "training_envelope": geometry,
        "fit_hash": digest(
            canonical(
                {
                    "training_rows": train_rows,
                    "policy": p,
                    "reference_fit_hash": reference["fit_hash"],
                }
            )
        ),
        "selected": selected["lightgbm"],
    }
    report = {
        "status": "trained",
        "profile_counts": counts,
        "candidate_rows": len(grid),
        "supported_rows": len(rows),
        "missing_or_unsupported_rows": len(grid) - len(rows),
        "candidates": candidates,
        "selected": selected,
        "evaluation": evaluate(rows, means, predictions, variable, reference, p),
    }
    return report, model


def promotion(report, variable, p):
    reasons = []
    gate = p["promotion"]
    if report["status"] != "trained":
        return {
            "eligible": False,
            "reasons": [report["reason"]],
            "active_method": "climatology",
        }
    if not gate["reviewed_gate_id"]:
        reasons.append("promotion_thresholds_not_reviewed")
    if not gate["untouched_test"]:
        reasons.append("test_block_previously_inspected")
    if not gate["independence_audits_approved"]:
        reasons.append("spatial_platform_audits_not_approved")
    if not gate["source_and_coverage_approved"]:
        reasons.append("source_coverage_not_approved")
    test = report["evaluation"]["test"]
    reference = test["climatology"]["overall"]
    candidate = test["lightgbm"]["overall"]
    if candidate["profiles"] < p["min_test_profiles"]:
        reasons.append("insufficient_test_profiles")
    if (
        reference["profile_weighted_mae"] is None
        or reference["profile_weighted_mae"] <= 1e-12
        or candidate["profile_weighted_mae"] is None
        or candidate["profile_weighted_mae"]
        > reference["profile_weighted_mae"]
        * (1 - gate["min_relative_profile_mae_improvement"])
    ):
        reasons.append("insufficient_material_improvement")
    if (
        candidate["bias"] is None
        or abs(candidate["bias"]) > gate["max_absolute_bias"][variable]
    ):
        reasons.append("bias_gate_failed")
    checks = []
    for name, base in sorted(test["climatology"].items()):
        if name == "overall":
            continue
        result = test["lightgbm"][name]
        adequate = base["profiles"] >= p["min_subgroup_profiles"]
        regressed = adequate and result["profile_weighted_mae"] > max(
            base["profile_weighted_mae"], 1e-12
        ) * (1 + gate["max_subgroup_relative_regression"])
        if regressed:
            reasons.append("subgroup_regression:" + name)
        checks.append(
            {
                "group": name,
                "profiles": base["profiles"],
                "adequate": adequate,
                "regressed": regressed,
            }
        )
    return {
        "eligible": not reasons,
        "active_method": "lightgbm_residual" if not reasons else "climatology",
        "reasons": reasons,
        "subgroup_checks": checks,
        "thresholds": gate,
    }


def fit(grid, reference, p, *, audits=True):
    if (
        len(grid) > p["max_rows"]
        or len({r["profile_id"] for r in grid}) > p["max_profiles"]
    ):
        raise ValueError("expected_training_budget")
    models, variables = {}, {}
    for v in VARIABLES:
        report, model = train_variable(grid, v, reference, p)
        report["promotion"] = promotion(report, v, p)
        variables[v] = report
        if model:
            models[v] = model
    audit_reports = []
    if audits:
        for kind in ("spatial", "platform"):
            for name, complement, held in audit_partitions(grid, p, kind):
                # Refit the entire reference and boosting on the complement, including support.
                audit_reference = fit_reference(complement, reference["policy"])
                fold_report = {
                    "kind": kind,
                    "fold": name,
                    "complement_profiles": len({r["profile_id"] for r in complement}),
                    "held_profiles": len({r["profile_id"] for r in held}),
                    "reference_fit_hash": audit_reference["fit_hash"],
                    "variables": {},
                }
                for v in VARIABLES:
                    result, model = train_variable(complement, v, audit_reference, p)
                    if model:
                        rows, means = eligible(held, v, audit_reference)
                        booster = lgb.Booster(model_str=model["model_text"])
                        pred = (
                            means
                            + booster.predict(
                                np.asarray(
                                    [vector(r, audit_reference["policy"]) for r in rows]
                                ),
                                num_threads=1,
                            )
                            if rows
                            else means
                        )
                        result["held_evaluation"] = score(
                            rows, [r[v] for r in rows], pred, p
                        )
                        train_rows, train_means = eligible(
                            complement, v, audit_reference
                        )
                        mask = np.asarray(
                            [r["split"] == "train" for r in train_rows], dtype=bool
                        )
                        training = [r for r in train_rows if r["split"] == "train"]
                        with threadpool_limits(limits=1):
                            hgbr = HistGradientBoostingRegressor(
                                **result["selected"]["hgbr"]["parameters"]
                            ).fit(
                                np.asarray(
                                    [
                                        vector(r, audit_reference["policy"])
                                        for r in train_rows
                                    ]
                                )[mask],
                                np.asarray([r[v] for r in train_rows])[mask]
                                - train_means[mask],
                                sample_weight=weights(training),
                            )
                            hgbr_prediction = (
                                means
                                + hgbr.predict(
                                    np.asarray(
                                        [
                                            vector(r, audit_reference["policy"])
                                            for r in rows
                                        ]
                                    )
                                )
                                if rows
                                else means
                            )
                        result["held_comparison"] = {
                            "climatology": score(rows, [r[v] for r in rows], means, p),
                            "hgbr": score(
                                rows, [r[v] for r in rows], hgbr_prediction, p
                            ),
                            "lightgbm": result["held_evaluation"],
                        }
                        result["held_supported_rows"] = len(rows)
                        result["held_candidate_rows"] = len(held)
                    fold_report["variables"][v] = result
                audit_reports.append(fold_report)
    return {
        "models": models,
        "variables": variables,
        "independence_audits": audit_reports,
        "feature_schema": {
            "version": VERSION,
            "names": list(NAMES),
            "omitted_static_features": ["bathymetry_m", "distance_to_coast_km"],
            "reason": "static_sources_not_validated",
        },
        "coast_distance_evaluation": {
            "status": "unavailable",
            "reason": "coast_distance_source_not_validated",
        },
        "bootstrap_limitations": "Profile bootstrap does not establish serial-float independence; spatial/platform audits refit the complete reference on held-group complements.",
        "estimand": "conditional_mean",
        "release_approved": False,
    }


def infer(rows, bundle, explain=False):
    if not 1 <= len(rows) <= 32:
        raise ValueError("expected_request_budget")
    reference = bundle["climatology"]
    x = np.asarray([vector(r, reference["policy"]) for r in rows])
    response = [{"depth_m": r["depth_m"]} for r in rows]
    for v in VARIABLES:
        m = bundle["models"].get(v)
        booster = lgb.Booster(model_str=m["model_text"]) if m else None
        correction = (
            booster.predict(x, num_threads=1) if booster else [None] * len(rows)
        )
        contributions = (
            booster.predict(x, pred_contrib=True, num_threads=1)
            if booster and explain
            else None
        )
        decision = bundle["variables"][v]["promotion"]
        for i, row in enumerate(rows):
            ref = baseline(row, v, reference)
            mean = ref["expected_mean"]
            supported = m and all(
                m["training_envelope"][k][0] <= row[k] <= m["training_envelope"][k][1]
                for k in m["training_envelope"]
            )
            candidate = (
                float(mean + correction[i]) if mean is not None and supported else None
            )
            low, high = reference["policy"]["physical_bounds"][v]
            if candidate is not None and (
                not math.isfinite(candidate) or not low <= candidate <= high
            ):
                candidate = None
            use = decision["eligible"] and candidate is not None
            point = {
                "climatology_mean": mean,
                "candidate_mean": candidate,
                "candidate_residual": float(correction[i])
                if candidate is not None
                else None,
                "expected_mean": candidate if use else mean,
                "ml_residual": float(correction[i])
                if use
                else 0.0
                if mean is not None
                else None,
                "active_method": "lightgbm_residual"
                if use
                else "climatology"
                if mean is not None
                else "unavailable",
                "reason": ref["reason"],
                "candidate_reason": None
                if candidate is not None
                else "unsupported_candidate_coverage",
                "promotion_reasons": decision["reasons"],
                "baseline_support": ref,
                "feature_contributions": [],
                "contribution_bias": None,
            }
            if contributions is not None and candidate is not None:
                values = contributions[i]
                if not math.isclose(
                    float(values.sum()),
                    float(correction[i]),
                    abs_tol=1e-8,
                    rel_tol=1e-8,
                ):
                    raise ValueError("contribution_additivity_failed")
                point["feature_contributions"] = [
                    {"feature": name, "contribution": float(value)}
                    for name, value in zip(NAMES, values[:-1], strict=True)
                ]
                point["contribution_bias"] = float(values[-1])
            response[i][v] = point
    return {
        "rows": response,
        "estimand": "conditional_mean",
        "method_version": METHOD,
        "feature_version": VERSION,
        "release_approved": False,
        "interval_status": "unavailable_not_calibrated",
        "explanation_interpretation": "Tree contributions explain the residual model, not oceanographic causation.",
    }
