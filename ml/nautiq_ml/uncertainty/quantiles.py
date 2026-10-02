"""Tuning-selected native quantile families and train-disjoint profile CQR."""

import json
import tempfile
from pathlib import Path
from time import perf_counter

import catboost
import lightgbm as lgb
import numpy as np
from threadpoolctl import threadpool_limits

from ..argo.evidence import canonical
from ..argo.storage import digest
from ..climatology.grid import VARIABLES, instant
from ..climatology.model import band, fit as fit_reference, region
from ..expected_state.features import NAMES, VERSION, audit_partitions, vector
from ..expected_state.model import SPLITS, eligible, weights
from . import calibration

METHOD = "profile-mondrian-cqr-v1"


def load_policy(path):
    p = json.loads(Path(path).read_bytes())
    validate_policy(p)
    return p


def validate_policy(p):
    if (
        p.get("schema_version") != 1
        or p.get("method_version") != METHOD
        or p.get("feature_version") != VERSION
        or p.get("quantiles") != [0.1, 0.5, 0.9]
        or p.get("alpha") != 0.2
        or p.get("release_approved") is not False
        or p.get("calibration_unit") != calibration.UNIT
        or p.get("hierarchy") != ["region_depth", "region", "depth", "global"]
        or p.get("leaves") != [7, 15]
        or p.get("catboost_depths") != [3, 4]
        or not 1 <= p["max_rounds"] <= 200
        or not 2 <= p["early_stopping_rounds"] <= 30
        or not 0 < p["learning_rate"] <= 0.2
        or not 5 <= p["min_samples_leaf"] <= 100
        or not 0 <= p["l2_regularization"] <= 100
        or any(
            not 10 <= p[k] <= 2000
            for k in (
                "min_train_profiles",
                "min_tune_profiles",
                "min_calibration_profiles",
                "min_test_profiles",
                "min_subgroup_profiles",
            )
        )
        or not 1 <= p["max_profiles"] <= 2000
        or not 1 <= p["max_rows"] <= 32000
        or p["spatial_folds"] != 2
        or p["platform_folds"] != 2
        or not 1 <= p["audit_cell_degrees"] <= 10
        or not 0 < p["spatial_buffer_degrees"] <= 5
        or not 1 <= p["monitor_window_days"] <= 366
        or not 1 <= p["monitor_max_profiles"] <= 2000
        or not 10 <= p["monitor_min_profiles"] <= 2000
        or not 1 <= p["monitor_suspect_score_multiplier"] <= 10
        or not 0 <= p["family_pinball_tie_tolerance"] <= 0.05
        or not 1 <= p["max_predict_p95_ms"] <= 1000
    ):
        raise ValueError("invalid_uncertainty_policy")
    gate = p["coverage_gate"]
    if (
        any(
            type(gate[k]) is not bool
            for k in (
                "untouched_test",
                "exchangeability_approved",
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
        or not 0 < gate["coverage_tolerance"] < 0.3
        or any(not 0 < gate["max_mean_width"][v] < 100 for v in VARIABLES)
    ):
        raise ValueError("invalid_coverage_gate")


def pinball(truth, predicted, rows, alphas=(0.1, 0.5, 0.9)):
    errors = np.asarray(truth)[:, None] - np.asarray(predicted)
    loss = np.maximum(
        np.asarray(alphas) * errors, (np.asarray(alphas) - 1) * errors
    ).mean(axis=1)
    w = weights(rows)
    return float(np.sum(w * loss) / w.sum())


def cat_text(model):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "model.json"
        model.save_model(str(path), format="json")
        value = json.loads(path.read_bytes())
    # These training receipt fields are volatile; trees, feature metadata and parameters stay intact.
    for name in ("model_guid", "train_finish_time"):
        value.get("model_info", {}).pop(name, None)
    return canonical(value).decode()


def native(artifact):
    if artifact["family"] == "lightgbm":
        return [lgb.Booster(model_str=t) for t in artifact["model_texts"]]
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "model.json"
        path.write_text(artifact["model_texts"][0])
        model = catboost.CatBoostRegressor()
        model.load_model(str(path), format="json")
    return model


def predict(artifact, x, models=None):
    models = native(artifact) if models is None else models
    if artifact["family"] == "lightgbm":
        return np.column_stack([m.predict(x, num_threads=1) for m in models])
    return np.asarray(models.predict(x, thread_count=1))


def train(rows, means, variable, reference, p):
    masks = {s: np.asarray([r["split"] == s for r in rows], dtype=bool) for s in SPLITS}
    counts = {
        s: len({r["profile_id"] for r in rows if r["split"] == s}) for s in SPLITS
    }
    if (
        counts["train"] < p["min_train_profiles"]
        or counts["tune"] < p["min_tune_profiles"]
    ):
        return {}, {
            "status": "unsupported",
            "reason": "insufficient_training_or_tuning_profiles",
            "profile_counts": counts,
        }
    x = np.asarray([vector(r, reference["policy"]) for r in rows])
    y = np.asarray([r[variable] for r in rows])
    residual = y - means
    tr = [r for r in rows if r["split"] == "train"]
    tu = [r for r in rows if r["split"] == "tune"]
    wt, wv = weights(tr), weights(tu)
    geometry = {
        k: [min(r[k] for r in tr), max(r[k] for r in tr)]
        for k in ("latitude", "longitude", "depth_m")
    }
    candidates, artifacts, selected = {}, {}, {}
    with threadpool_limits(limits=1):
        for family, settings in (
            ("lightgbm", p["leaves"]),
            ("catboost", p["catboost_depths"]),
        ):
            choices = []
            for setting in settings:
                texts, configs = [], []
                if family == "lightgbm":
                    for alpha in p["quantiles"]:
                        config = {
                            "objective": "quantile",
                            "alpha": alpha,
                            "metric": "None",
                            "num_leaves": setting,
                            "learning_rate": p["learning_rate"],
                            "min_data_in_leaf": p["min_samples_leaf"],
                            "lambda_l2": p["l2_regularization"],
                            "num_threads": 1,
                            "deterministic": True,
                            "force_col_wise": True,
                            "seed": p["seed"],
                            "verbosity": -1,
                        }

                        def tune_loss(predicted, data, level=alpha):
                            error = data.get_label() - predicted
                            return (
                                "profile_pinball",
                                float(
                                    np.sum(
                                        wv
                                        * np.maximum(level * error, (level - 1) * error)
                                    )
                                    / wv.sum()
                                ),
                                False,
                            )

                        model = lgb.train(
                            config,
                            lgb.Dataset(
                                x[masks["train"]],
                                label=residual[masks["train"]],
                                weight=wt,
                                feature_name=list(NAMES),
                            ),
                            num_boost_round=p["max_rounds"],
                            valid_sets=[
                                lgb.Dataset(
                                    x[masks["tune"]],
                                    label=residual[masks["tune"]],
                                    weight=wv,
                                )
                            ],
                            feval=tune_loss,
                            callbacks=[
                                lgb.early_stopping(
                                    p["early_stopping_rounds"], verbose=False
                                )
                            ],
                        )
                        texts.append(
                            model.model_to_string(num_iteration=model.best_iteration)
                        )
                        configs.append(
                            {**config, "best_iteration": model.best_iteration}
                        )
                else:
                    config = {
                        "loss_function": "MultiQuantile:alpha=0.1,0.5,0.9",
                        "iterations": p["max_rounds"],
                        "depth": setting,
                        "learning_rate": p["learning_rate"],
                        "l2_leaf_reg": p["l2_regularization"],
                        "random_seed": p["seed"],
                        "thread_count": 1,
                        "allow_writing_files": False,
                        "verbose": False,
                    }
                    model = catboost.CatBoostRegressor(**config)
                    model.fit(
                        catboost.Pool(
                            x[masks["train"]],
                            residual[masks["train"]],
                            weight=wt,
                            feature_names=list(NAMES),
                        ),
                        eval_set=catboost.Pool(
                            x[masks["tune"]],
                            residual[masks["tune"]],
                            weight=wv,
                            feature_names=list(NAMES),
                        ),
                        early_stopping_rounds=p["early_stopping_rounds"],
                        use_best_model=True,
                    )
                    texts.append(cat_text(model))
                    configs.append(
                        {**config, "best_iteration": model.get_best_iteration() + 1}
                    )
                artifact = {
                    "family": family,
                    "model_texts": texts,
                    "model_sha256": [digest(t.encode()) for t in texts],
                    "feature_names": list(NAMES),
                    "training_envelope": geometry,
                    "parameters": configs,
                }
                loss = pinball(
                    y[masks["tune"]],
                    means[masks["tune"], None] + predict(artifact, x[masks["tune"]]),
                    tu,
                )
                choices.append((loss, setting, artifact))
            best = min(choices, key=lambda c: (c[0], c[1]))
            artifacts[family] = best[2]
            selected[family] = {
                "setting": best[1],
                "tuning_profile_pinball": best[0],
                "parameters": best[2]["parameters"],
            }
            tune_raw = means[masks["tune"], None] + predict(best[2], x[masks["tune"]])
            tune_ordered = np.sort(tune_raw, axis=1)
            selected[family]["tuning_raw_coverage"] = float(
                (
                    (y[masks["tune"]] >= tune_ordered[:, 0])
                    & (y[masks["tune"]] <= tune_ordered[:, 2])
                ).mean()
            )
            selected[family]["tuning_crossing_rate"] = float(
                np.any(np.diff(tune_raw, axis=1) < 0, axis=1).mean()
            )
            candidates[family] = [
                {"setting": c[1], "tuning_profile_pinball": c[0]} for c in choices
            ]
    best_loss = min(c["tuning_profile_pinball"] for c in selected.values())
    contenders = [
        f
        for f in selected
        if selected[f]["tuning_profile_pinball"]
        <= best_loss * (1 + p["family_pinball_tie_tolerance"]) + 1e-12
    ]
    chosen = min(
        contenders,
        key=lambda f: (
            abs(selected[f]["tuning_raw_coverage"] - (1 - p["alpha"])),
            selected[f]["tuning_crossing_rate"],
            0 if f == "lightgbm" else 1,
        ),
    )
    return artifacts, {
        "status": "trained",
        "profile_counts": counts,
        "selected_family": chosen,
        "selected": selected,
        "candidates": candidates,
        "selection_rule": "tuning pinball within frozen tolerance, then closest raw nominal coverage, crossing rate, existing LightGBM operational path; measured latency must pass selection budget; no test/calibration tuning",
    }


def envelope(row, artifact):
    return all(
        low <= row[key] <= high
        for key, (low, high) in artifact["training_envelope"].items()
    )


def evaluate(rows, means, variable, artifact, reference, p):
    rows_and_indices = [(r, i) for i, r in enumerate(rows) if envelope(r, artifact)]
    kept = [r for r, _ in rows_and_indices]
    indices = [i for _, i in rows_and_indices]
    if not kept:
        return None, {}, None
    x = np.asarray([vector(r, reference["policy"]) for r in kept])
    raw = means[indices, None] + predict(artifact, x)
    if raw.shape != (len(kept), 3) or not np.isfinite(raw).all():
        raise ValueError("invalid_quantile_output")
    ordered = np.sort(raw, axis=1)
    truth = np.asarray([r[variable] for r in kept])
    calibrated = calibration.fit(kept, truth, ordered, reference["policy"], p)
    intervals, selections = calibration.apply(
        kept, ordered, reference["policy"], calibrated
    )
    report = partition_metrics(
        kept, truth, ordered, intervals, raw, selections, reference
    )
    # Report latency separately from reproducible bundle identity: benchmark CLI records actual timings.
    return calibrated, report, len(rows) - len(kept)


def partition_metrics(rows, y, q, intervals, raw, selections, reference):
    report = {}
    cp = reference["policy"]
    for split in SPLITS:
        split_mask = np.array([r["split"] == split for r in rows], dtype=bool)
        groups = {"overall": np.ones(len(rows), dtype=bool)}
        for area in ("arabian", "bay_bengal"):
            groups[f"region:{area}"] = np.array(
                [region(r, cp) == area for r in rows], dtype=bool
            )
            for i in range(len(cp["depth_bands_m"])):
                groups[f"region_depth:{area}:{i}"] = np.array(
                    [
                        region(r, cp) == area and band(r["depth_m"], cp) == i
                        for r in rows
                    ],
                    dtype=bool,
                )
        for i in range(len(cp["depth_bands_m"])):
            groups[f"depth_band:{i}"] = np.array(
                [band(r["depth_m"], cp) == i for r in rows], dtype=bool
            )
        for season, months in (
            ("DJF", (12, 1, 2)),
            ("MAM", (3, 4, 5)),
            ("JJA", (6, 7, 8)),
            ("SON", (9, 10, 11)),
        ):
            groups[f"season:{season}"] = np.array(
                [instant(r["observed_at"]).month in months for r in rows], dtype=bool
            )
        report[split] = {}
        for name, mask in groups.items():
            take = split_mask & mask
            selected = [r for r, ok in zip(rows, take, strict=True) if ok]
            report[split][name] = calibration.metrics(
                selected,
                y[take],
                q[take],
                intervals[take],
                raw[take],
                [s for s, ok in zip(selections, take, strict=True) if ok],
                cp,
            )
    return report


def coverage_gate(result, variable, p):
    reasons = []
    g = p["coverage_gate"]
    if result["status"] != "trained":
        return {"qualified": False, "reasons": [result["reason"]]}
    if not g["reviewed_gate_id"]:
        reasons.append("coverage_thresholds_not_reviewed")
    for key in (
        "untouched_test",
        "exchangeability_approved",
        "independence_audits_approved",
        "source_and_coverage_approved",
    ):
        if not g[key]:
            reasons.append(key + "_not_approved")
    test = result["families"][result["selected_family"]]["evaluation"]["test"]
    if result["families"][result["selected_family"]][
        "outside_quantile_training_envelope_rows"
    ]:
        reasons.append("quantile_training_envelope_missing_support")
    checks = []
    for name, metric in sorted(test.items()):
        adequate = metric["profiles"] >= (
            p["min_test_profiles"] if name == "overall" else p["min_subgroup_profiles"]
        )
        accepted = (
            adequate
            and metric["profile_group_coverage"] is not None
            and abs(metric["profile_group_coverage"] - (1 - p["alpha"]))
            <= g["coverage_tolerance"]
            and metric["profile_weighted_width"] <= g["max_mean_width"][variable]
            and metric["unavailable_rows"] == 0
        )
        checks.append(
            {
                "group": name,
                "profiles": metric["profiles"],
                "adequate": adequate,
                "accepted": accepted,
            }
        )
        if name == "overall" and not adequate:
            reasons.append("insufficient_test_profiles")
        elif adequate and not accepted:
            reasons.append("coverage_or_width_gate_failed:" + name)
    return {"qualified": not reasons, "reasons": reasons, "checks": checks}


def fit(grid, reference, p, audits=True):
    if (
        len(grid) > p["max_rows"]
        or len({r["profile_id"] for r in grid}) > p["max_profiles"]
    ):
        raise ValueError("uncertainty_training_budget")
    models, variables = {}, {}
    for v in VARIABLES:
        rows, means = eligible(grid, v, reference)
        artifacts, result = train(rows, means, v, reference, p)
        if artifacts:
            result["families"] = {}
            for family, artifact in artifacts.items():
                cal, evaluation, unavailable = evaluate(
                    rows, means, v, artifact, reference, p
                )
                if cal is None:
                    raise ValueError("uncertainty_domain_unavailable")
                artifact["calibration"] = cal
                result["families"][family] = {
                    "calibration": cal,
                    "evaluation": evaluation,
                    "outside_quantile_training_envelope_rows": unavailable,
                    "native_model_count": len(artifact["model_texts"]),
                }
            models[v] = artifacts
        result["coverage_gate"] = coverage_gate(result, v, p)
        variables[v] = result
    audit_reports = []
    if audits:
        for kind in ("spatial", "platform"):
            for name, complement, held in audit_partitions(grid, p, kind):
                ref = fit_reference(complement, reference["policy"])
                local = fit(complement, ref, p, audits=False)
                entry = {
                    "fold": name,
                    "kind": kind,
                    "complement_profiles": len({r["profile_id"] for r in complement}),
                    "held_profiles": len({r["profile_id"] for r in held}),
                    "reference_fit_hash": ref["fit_hash"],
                    "variables": {},
                }
                for v, result in local["variables"].items():
                    info = {
                        "status": result["status"],
                        "profile_counts": result["profile_counts"],
                        "families": {},
                    }
                    if result["status"] != "trained":
                        info["reason"] = result["reason"]
                    else:
                        rows, means = eligible(held, v, ref)
                        for family, artifact in local["models"][v].items():
                            indices = [
                                i
                                for i, row in enumerate(rows)
                                if envelope(row, artifact)
                            ]
                            chosen = [rows[i] for i in indices]
                            if chosen:
                                raw = means[indices, None] + predict(
                                    artifact,
                                    np.asarray(
                                        [vector(r, ref["policy"]) for r in chosen]
                                    ),
                                )
                                ordered = np.sort(raw, axis=1)
                                intervals, selections = calibration.apply(
                                    chosen,
                                    ordered,
                                    ref["policy"],
                                    artifact["calibration"],
                                )
                                info["families"][family] = calibration.metrics(
                                    chosen,
                                    [r[v] for r in chosen],
                                    ordered,
                                    intervals,
                                    raw,
                                    selections,
                                    ref["policy"],
                                )
                            else:
                                info["families"][family] = calibration.metrics(
                                    [], [], np.empty((0, 3)), np.empty((0, 2))
                                )
                    entry["variables"][v] = info
                audit_reports.append(entry)
    return {
        "models": models,
        "variables": variables,
        "independence_audits": audit_reports,
        "feature_schema": {"version": VERSION, "names": list(NAMES)},
        "nominal_coverage": 1 - p["alpha"],
        "coverage_unit": calibration.UNIT,
        "interval_interpretation": "Predictive natural variability; not measurement error or uncertainty in the fitted climatological mean.",
        "coast_distance_evaluation": "unavailable_static_source_not_validated",
        "release_approved": False,
    }


def benchmark_latency(bundle, repeats=10):
    # Volatile performance evidence is logged outside content-addressed model identity.
    result = {}
    row = {
        "latitude": 15.0,
        "longitude": 70.0,
        "depth_m": 10.0,
        "observed_at": "2023-06-15T00:00:00Z",
    }
    x = np.array([vector(row, bundle["climatology"]["policy"])] * 15)
    for v, families in bundle["models"].items():
        result[v] = {}
        for family, artifact in families.items():
            start = perf_counter()
            models = native(artifact)
            load = perf_counter() - start
            times = []
            for _ in range(repeats):
                start = perf_counter()
                predict(artifact, x, models)
                times.append((perf_counter() - start) * 1000)
            result[v][family] = {
                "model_load_ms": load * 1000,
                "batch_points": 15,
                "median_predict_ms": float(np.median(times)),
                "p95_predict_ms": float(np.quantile(times, 0.95)),
                "native_model_count": len(artifact["model_texts"]),
            }
    return result
