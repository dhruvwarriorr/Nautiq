"""Train-only shrinkage covariance and weighted discrete FPCA; safe JSON models."""

import json
import math
from collections import defaultdict
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.stats import spearmanr
from sklearn.covariance import LedoitWolf
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest

from ..argo.evidence import canonical
from ..argo.storage import digest
from ..climatology.grid import VARIABLES
from ..climatology.model import predict as reference_predict, region
from ..expected_state.features import validate_profiles
from ..uncertainty.quantiles import native
from ..uncertainty.serving import infer as interval_infer
from . import METHOD

SCORES = (
    "weighted_squared_residual",
    "mahalanobis_squared",
    "fpca_distance_squared",
    "fpca_reconstruction_error",
    "climatology_z_squared",
    "isolation_forest",
)
LIMITATIONS = [
    "Complete-case weighted discrete PCA prototype; sparse functional inference is unavailable.",
    "Quantile half-width is predictive variability in physical units, not Gaussian sigma, measurement error or mean confidence.",
    "Raw train-fitted quantiles determine scale; CQR corrections never fit the basis or covariance.",
    "Historical empirical percentiles are descriptive ranks, not event probabilities or calibrated alert thresholds.",
    "Expert event labels, quiet-period false-alert rates, untouched and independent audits remain unavailable.",
    "Synthetic sensitivity and resampling stability do not establish event recall or scientific approval.",
    "PCA modes have arbitrary orientation across releases; oceanographic labels require reviewed loadings.",
]


def load_policy(path):
    p = json.loads(Path(path).read_bytes())
    validate_policy(p)
    return p


def validate_policy(p):
    if (
        p["schema_version"] != 1
        or p["method_version"] != METHOD
        or p["depths_m"] != [10, 20, 30, 50, 75, 100, 150, 200, 300, 400, 500]
        or p["coverage_policy"] != "complete_10_500m_per_variable"
        or p["scale_estimator"]
        != "train_fitted_rearranged_quantile_half_interdecile_width"
        or p["scale_floor"] != {"temperature_c": 0.05, "practical_salinity": 0.01}
        or p["hierarchy"] != ["region", "global"]
        or p["components"] != 3
        or p["release_approved"] is not False
        or p["scientific_review"]
        != {
            "expert_events": False,
            "quiet_period_false_alerts": False,
            "untouched_audit": False,
            "independence": False,
            "source_coverage": False,
        }
        or not 20 <= p["min_train_profiles"] <= 2000
        or not 20 <= p["min_calibration_profiles"] <= 2000
        or not 2 <= p["isolation_trees"] <= 128
        or not 2 <= p["isolation_max_samples"] <= 256
        or not 1 <= len(p["stability_seeds"]) <= 20
        or not 1 <= p["max_profiles"] <= 2000
        or not 1 <= p["max_rows"] <= 32000
        or not 1 < p["max_covariance_condition"] <= 1e8
        or not 0 < p["max_predict_p95_ms"] <= 1000
    ):
        raise ValueError("unsupported_anomaly_policy")


def weights(depths):
    gap = np.diff(depths)
    w = np.r_[gap[0] / 2, (gap[:-1] + gap[1:]) / 2, gap[-1] / 2]
    return w / w.sum()


def loaded_parent(parent):
    return {
        v: native(f[parent["variables"][v]["selected_family"]])
        for v, f in parent["models"].items()
    }


def prepare(rows, parent, p, loaded=None):
    """Preserve nullable depth evidence; refuse incomplete aggregate vectors."""
    if [r["depth_m"] for r in rows] != p["depths_m"]:
        raise ValueError("anomaly_grid_mismatch")
    meta = ("latitude", "longitude", "observed_at")
    if any(any(r[k] != rows[0][k] for k in meta) for r in rows):
        raise ValueError("anomaly_profile_metadata_mismatch")
    predicted = interval_infer(rows, parent, loaded)["rows"]
    answer = {}
    for v in VARIABLES:
        points = []
        bounds = parent["climatology"]["policy"]["physical_bounds"][v]
        for r, prediction in zip(rows, predicted, strict=True):
            value, q = r[v], prediction[v]
            if value is not None and (
                not math.isfinite(value) or not bounds[0] <= value <= bounds[1]
            ):
                raise ValueError("invalid_anomaly_observation")
            mean = q["expected_mean"]
            width = (q["q90"] - q["q10"]) / 2 if q["q10"] is not None else None
            scale = max(width, p["scale_floor"][v]) if width is not None else None
            residual = value - mean if value is not None and mean is not None else None
            baseline = reference_predict(r, v, parent["climatology"])
            z = (
                (value - baseline["expected_mean"]) / baseline["spread"]
                if value is not None and baseline["expected_mean"] is not None
                else None
            )
            reason = (
                "missing_observation"
                if value is None
                else "unsupported_expected_mean"
                if mean is None
                else "unsupported_quantile_scale"
                if scale is None
                else None
            )
            points.append(
                {
                    "depth_m": r["depth_m"],
                    "observed": value,
                    "expected_mean": mean,
                    "residual": residual,
                    "scale": scale,
                    "scale_floored": width is not None and width < p["scale_floor"][v],
                    "standardized_residual": residual / scale
                    if residual is not None and scale is not None
                    else None,
                    "climatology_z": z,
                    "covered": reason is None,
                    "reason": reason,
                }
            )
        answer[v] = {"points": points, "complete": all(x["covered"] for x in points)}
    return answer


def average_path(n):
    return (
        0.0
        if n <= 1
        else 1.0
        if n == 2
        else 2 * (math.log(n - 1) + np.euler_gamma) - 2 * (n - 1) / n
    )


def export_forest(model):
    trees = []
    for estimator in model.estimators_:
        t = estimator.tree_
        trees.append(
            {
                "left": t.children_left.tolist(),
                "right": t.children_right.tolist(),
                "feature": t.feature.tolist(),
                "threshold": t.threshold.tolist(),
                "samples": t.n_node_samples.tolist(),
            }
        )
    return {"trees": trees, "max_samples": int(model.max_samples_)}


def forest_score(x, forest):
    # sklearn tree traversal converts observations to float32. No executable pickle.
    x = np.asarray(x, dtype=np.float32)
    paths = []
    for t in forest["trees"]:
        node, length = 0, 0
        for _ in range(len(t["left"])):
            if t["left"][node] == -1:
                paths.append(length + average_path(t["samples"][node]))
                break
            node = (
                t["left"][node]
                if x[t["feature"][node]] <= t["threshold"][node]
                else t["right"][node]
            )
            length += 1
        else:
            raise ValueError("invalid_anomaly_tree")
    return float(2 ** (-np.mean(paths) / average_path(forest["max_samples"])))


def basis_fit(x, p):
    center = x.mean(axis=0)
    centered = x - center
    cov = LedoitWolf(assume_centered=True).fit(centered)
    condition = float(np.linalg.cond(cov.covariance_))
    if not math.isfinite(condition) or condition > p["max_covariance_condition"]:
        raise ValueError("unstable_anomaly_covariance")
    w = weights(p["depths_m"])
    pc = PCA(n_components=p["components"], svd_solver="full").fit(centered * np.sqrt(w))
    if min(pc.explained_variance_) <= 1e-10:
        raise ValueError("insufficient_anomaly_rank")
    components = pc.components_.copy()
    for component in components:
        if component[np.argmax(np.abs(component))] < 0:
            component *= -1
    return {
        "center": center.tolist(),
        "precision": cov.precision_.tolist(),
        "covariance": cov.covariance_.tolist(),
        "shrinkage": float(cov.shrinkage_),
        "condition": condition,
        "weights": w.tolist(),
        "pca_mean": pc.mean_.tolist(),
        "components": components.tolist(),
        "eigenvalues": pc.explained_variance_.tolist(),
        "explained_variance_ratio": pc.explained_variance_ratio_.tolist(),
        "basis_loadings": (components / np.sqrt(w)).tolist(),
        "sign_rule": "largest_absolute_loading_positive",
    }


def score(x, z, model):
    s = np.asarray(x) - model["center"]
    w = np.asarray(model["weights"])
    precision = np.asarray(model["precision"])
    weighted = s * np.sqrt(w) - model["pca_mean"]
    components = np.asarray(model["components"])
    coefficients = components @ weighted
    reconstruction = coefficients @ components + model["pca_mean"]
    error = s - reconstruction / np.sqrt(w)
    contributions = s * (
        precision @ s
    )  # Signed covariance terms sum to squared distance.
    squared = s * s * w
    component_distance = coefficients**2 / np.asarray(model["eigenvalues"])
    result = {
        "scores": {
            "weighted_squared_residual": float(squared.sum()),
            "mahalanobis_squared": float(contributions.sum()),
            "fpca_distance_squared": float(component_distance.sum()),
            "fpca_reconstruction_error": float((error * error * w).sum()),
            "climatology_z_squared": float(np.sum(np.asarray(z) ** 2 * w)),
            "isolation_forest": forest_score(s, model["forest"]),
        },
        "centered_residuals": s.tolist(),
        "weighted_contributions": squared.tolist(),
        "mahalanobis_contributions": contributions.tolist(),
        "component_scores": coefficients.tolist(),
        "component_distance_contributions": component_distance.tolist(),
        "reconstruction": (reconstruction / np.sqrt(w) + model["center"]).tolist(),
        "reconstruction_errors": error.tolist(),
        "dominant_component": int(np.argmax(component_distance)) + 1,
    }
    if any(not math.isfinite(v) for v in result["scores"].values()):
        raise ValueError("nonfinite_anomaly_score")
    return result


def percentiles(scores, group, model, p):
    references = model["percentile_reference"]
    requested = "region:" + group
    selected = (
        requested
        if len(references.get(requested, {}).get(SCORES[0], []))
        >= p["min_calibration_profiles"]
        else "global"
    )
    reference = references.get(selected, {})
    n = len(reference.get(SCORES[0], []))
    return {
        "requested_group": requested,
        "group": selected if n >= p["min_calibration_profiles"] else None,
        "fallback": selected != requested,
        "profiles": n,
        "resolution_percent": 100 / n if n else None,
        "reason": None
        if n >= p["min_calibration_profiles"]
        else "insufficient_matched_calibration_profiles",
        "values": {
            k: 100 * sum(v <= scores[k] for v in reference[k]) / n
            if n >= p["min_calibration_profiles"]
            else None
            for k in SCORES
        },
    }


def fit(grid, parent, p):
    validate_policy(p)
    validate_profiles(
        grid,
        {
            "baseline": {"start_year": 2005, "end_year": 2024},
            "splits": {"train_end": 2016, "tune_end": 2019, "calibration_end": 2021},
        },
    )
    grouped = defaultdict(list)
    for row in grid:
        if row["depth_m"] in p["depths_m"]:
            grouped[row["profile_id"]].append(row)
    if len(grid) > p["max_rows"] or len(grouped) > p["max_profiles"]:
        raise ValueError("anomaly_fit_budget")
    loaded = loaded_parent(parent)
    records = []
    for pid, rows in sorted(grouped.items()):
        rows.sort(key=lambda r: r["depth_m"])
        prepared = prepare(rows, parent, p, loaded)
        records.append(
            {
                "profile_id": pid,
                "split": rows[0]["split"],
                "region": region(rows[0], parent["climatology"]["policy"]),
                "variables": prepared,
            }
        )
    models, variables = {}, {}
    for v in VARIABLES:
        eligible = [r for r in records if r["variables"][v]["complete"]]
        counts = {
            s: sum(r["split"] == s for r in eligible)
            for s in ("train", "tune", "calibration", "test")
        }
        info = {
            "complete_profiles": counts,
            "excluded_profiles": {
                s: sum(r["split"] == s for r in records) - counts[s] for s in counts
            },
            "qualified": False,
            "qualification_reasons": [
                "unreviewed_anomaly_release",
                "missing_expert_and_quiet_period_audits",
                "previously_inspected_historical_test",
            ],
        }
        if not parent["variables"][v]["coverage_gate"]["qualified"]:
            info["qualification_reasons"].append("unqualified_parent_uncertainty")
        variables[v] = info
        if counts["train"] < p["min_train_profiles"]:
            info.update(
                status="unsupported", reason="insufficient_complete_training_profiles"
            )
            continue

        def vector(r):
            return [x["standardized_residual"] for x in r["variables"][v]["points"]]

        def zscores(r):
            return [x["climatology_z"] for x in r["variables"][v]["points"]]

        train = [r for r in eligible if r["split"] == "train"]
        x = np.asarray([vector(r) for r in train])
        try:
            model = basis_fit(x, p)
        except ValueError as error:
            info.update(status="unsupported", reason=str(error))
            continue
        forest = IsolationForest(
            n_estimators=p["isolation_trees"],
            max_samples=min(p["isolation_max_samples"], len(train)),
            random_state=p["seed"],
            n_jobs=1,
        ).fit(x - model["center"])
        model["forest"] = export_forest(forest)
        # Round-trip parity ensures safe exported inference matches fitted sklearn trees.
        exported = [forest_score(row - model["center"], model["forest"]) for row in x]
        if not np.allclose(
            exported, -forest.score_samples(x - model["center"]), atol=1e-12
        ):
            raise ValueError("isolation_export_mismatch")
        references = defaultdict(lambda: {k: [] for k in SCORES})
        calibration = [r for r in eligible if r["split"] == "calibration"]
        for r in calibration:
            result = score(vector(r), zscores(r), model)["scores"]
            for group in ("global", "region:" + r["region"]):
                for name, value in result.items():
                    references[group][name].append(value)
        model["percentile_reference"] = {
            g: {k: sorted(values) for k, values in reference.items()}
            for g, reference in references.items()
        }
        info.update(
            status="diagnostic",
            reason=None,
            fit_profile_ids_sha256=digest(
                canonical(sorted(r["profile_id"] for r in train))
            ),
            calibration_profile_ids_sha256=digest(
                canonical(sorted(r["profile_id"] for r in calibration))
            ),
            covariance_condition=model["condition"],
            covariance_shrinkage=model["shrinkage"],
            explained_variance_ratio=model["explained_variance_ratio"],
            basis_loadings=model["basis_loadings"],
            comparison_groups={
                g: {
                    "profiles": len(a[SCORES[0]]),
                    "resolution_percent": 100 / len(a[SCORES[0]]),
                }
                for g, a in model["percentile_reference"].items()
            },
        )
        info["evaluation"] = {}
        for split in counts:
            selected = [r for r in eligible if r["split"] == split]
            values = [score(vector(r), zscores(r), model)["scores"] for r in selected]
            ranks = [
                percentiles(a, r["region"], model, p)
                for a, r in zip(values, selected, strict=True)
            ]
            info["evaluation"][split] = {
                "profiles": len(selected),
                "percentile_supported_profiles": sum(
                    a["reason"] is None for a in ranks
                ),
                "median_scores": {
                    k: float(np.median([a[k] for a in values])) if values else None
                    for k in SCORES
                },
                "median_percentiles": {
                    k: float(
                        np.median(
                            [
                                a["values"][k]
                                for a in ranks
                                if a["values"][k] is not None
                            ]
                        )
                    )
                    if any(a["values"][k] is not None for a in ranks)
                    else None
                    for k in SCORES
                },
            }
        test = [r for r in eligible if r["split"] == "test"]
        changes = []
        for r in test:
            original = np.asarray(vector(r))
            delta = np.array(
                [
                    (1 if v == "temperature_c" else 0.2) / x["scale"]
                    if x["depth_m"] <= 100
                    else 0
                    for x in r["variables"][v]["points"]
                ]
            )
            before, after = (
                score(original, zscores(r), model)["scores"],
                score(original + delta, zscores(r), model)["scores"],
            )
            changes.append(
                {
                    k: after[k] - before[k]
                    for k in SCORES
                    if k != "climatology_z_squared"
                }
            )
        info["synthetic_layer_sensitivity"] = {
            "perturbation": "add 1°C / 0.2 PSS-78 at 10–100m; sensitivity only",
            "profiles": len(test),
            "median_score_change": {
                k: float(np.median([a[k] for a in changes])) if changes else None
                for k in SCORES
                if k != "climatology_z_squared"
            },
        }
        held = [r for r in eligible if r["split"] == "tune"]
        stability = []
        for seed in p["stability_seeds"]:
            resampled = x[np.random.default_rng(seed).integers(0, len(x), len(x))]
            try:
                variant = {**basis_fit(resampled, p), "forest": model["forest"]}
                correlations = {}
                for k in (
                    "mahalanobis_squared",
                    "fpca_distance_squared",
                    "fpca_reconstruction_error",
                ):
                    before = [
                        score(vector(r), zscores(r), model)["scores"][k] for r in held
                    ]
                    after = [
                        score(vector(r), zscores(r), variant)["scores"][k] for r in held
                    ]
                    rho = (
                        float(spearmanr(before, after).statistic)
                        if len(before) > 2 and np.ptp(before) > 0 and np.ptp(after) > 0
                        else None
                    )
                    correlations[k] = (
                        rho if rho is not None and math.isfinite(rho) else None
                    )
                stability.append(
                    {
                        "seed": seed,
                        "status": "diagnostic",
                        "tune_profiles": len(held),
                        "rank_correlations": correlations,
                    }
                )
            except ValueError as error:
                stability.append(
                    {"seed": seed, "status": "unavailable", "reason": str(error)}
                )
        info["resampling_stability"] = stability
        models[v] = model
    return {
        "models": models,
        "variables": variables,
        "depths_m": p["depths_m"],
        "weights": weights(p["depths_m"]).tolist(),
        "coverage_policy": p["coverage_policy"],
        "scale_estimator": p["scale_estimator"],
        "limitations": LIMITATIONS,
        "release_approved": False,
    }


def infer(rows, bundle, loaded=None):
    p, parent = bundle["policy"], bundle["uncertainty"]
    prepared = prepare(rows, parent, p, loaded)
    output = {}
    for v, coverage in prepared.items():
        model = bundle["models"].get(v)
        info = {
            **coverage,
            "status": "unavailable",
            "reason": None,
            "qualified": False,
            "score_evidence": None,
            "percentiles": None,
        }
        output[v] = info
        if not model:
            info["reason"] = bundle["variables"][v].get("reason", "unsupported_model")
        elif not coverage["complete"]:
            info["reason"] = "incomplete_matched_depth_vector"
        else:
            points = coverage["points"]
            scored = score(
                [x["standardized_residual"] for x in points],
                [x["climatology_z"] for x in points],
                model,
            )
            ranked = percentiles(
                scored["scores"],
                region(rows[0], parent["climatology"]["policy"]),
                model,
                p,
            )
            for i, point in enumerate(points):
                point.update(
                    {
                        "training_center": model["center"][i],
                        "centered_standardized_residual": scored["centered_residuals"][
                            i
                        ],
                        "weighted_contribution": scored["weighted_contributions"][i],
                        "mahalanobis_contribution": scored["mahalanobis_contributions"][
                            i
                        ],
                        "reconstructed_standardized_residual": scored["reconstruction"][
                            i
                        ],
                        "reconstruction_error": scored["reconstruction_errors"][i],
                    }
                )
            maximum = max(points, key=lambda x: abs(x["standardized_residual"]))
            largest = max(points, key=lambda x: x["weighted_contribution"])
            info.update(
                status="diagnostic" if ranked["reason"] is None else "scores_only",
                reason=ranked["reason"],
                score_evidence=scored,
                percentiles=ranked,
                max_signed_standardized_residual=maximum["standardized_residual"],
                maximum_departure_depth_m=maximum["depth_m"],
                largest_contribution_depth_m=largest["depth_m"],
                depth_bands=[
                    {
                        "start_m": a if a else 10,
                        "end_m": b,
                        "weighted_contribution": sum(
                            x["weighted_contribution"]
                            for x in points
                            if a < x["depth_m"] <= b
                        ),
                        "signed_mean_residual": float(
                            np.mean(
                                [x["residual"] for x in points if a < x["depth_m"] <= b]
                            )
                        ),
                    }
                    for a, b in ((0, 100), (100, 500))
                ],
            )
    supported = sum(v["score_evidence"] is not None for v in output.values())
    return {
        "method_version": METHOD,
        "status": "diagnostic"
        if supported == 2
        else "partial"
        if supported
        else "unavailable",
        "supported_variables": supported,
        "variables": output,
        "coverage_policy": p["coverage_policy"],
        "depths_m": p["depths_m"],
        "scale_estimator": p["scale_estimator"],
        "release_approved": False,
    }


def benchmark_latency(bundle):
    result = {}
    for v, model in bundle["models"].items():
        elapsed = []
        for _ in range(100):
            start = perf_counter()
            score(model["center"], np.zeros(len(bundle["depths_m"])), model)
            elapsed.append((perf_counter() - start) * 1000)
        result[v] = {
            "p95_score_ms": float(np.quantile(elapsed, 0.95)),
            "scope": "score algebra and safe forest; excludes parent inference, RPC and storage",
        }
    return result
