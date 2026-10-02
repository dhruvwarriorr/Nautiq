"""Train-only climatology and exploratory grouped scientific benchmarks."""

import math

import numpy as np
from lightgbm import LGBMRegressor
from sklearn.covariance import LedoitWolf
from sklearn.decomposition import PCA
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error

SPLITS = ("train", "tune", "calibration", "test")


def features(rows):
    day = np.array([r["day_of_year"] for r in rows]) / 365.25 * 2 * np.pi
    return np.column_stack(
        (
            [r["latitude"] / 30 for r in rows],
            [r["longitude"] / 100 for r in rows],
            [r["depth_m"] / 2000 for r in rows],
            np.sin(day),
            np.cos(day),
            np.sin(2 * day),
            np.cos(2 * day),
        )
    )


class Climatology:
    """Depth-specific ridge harmonic reference with smooth spatial covariates."""

    def fit(self, x, y):
        self.models = {}
        for depth in np.unique(x[:, 2]):
            take = x[:, 2] == depth
            if take.sum() >= 12:
                self.models[depth] = Ridge(alpha=1).fit(
                    np.delete(x[take], 2, axis=1), y[take]
                )
        return self

    def predict(self, x):
        result = np.full(len(x), np.nan)
        for depth, model in self.models.items():
            take = x[:, 2] == depth
            result[take] = model.predict(np.delete(x[take], 2, axis=1))
        return result


def metrics(y, predicted, rows):
    if not len(y):
        return None
    errors = predicted - y
    grouped = {}
    for profile in sorted({r["profile_key"] for r in rows}):
        mask = np.array([r["profile_key"] == profile for r in rows])
        grouped[profile] = float(np.abs(errors[mask]).mean())
    profile_maes = np.array(list(grouped.values()))
    rng = np.random.default_rng(42)
    bootstrap = [rng.choice(profile_maes, len(profile_maes)).mean() for _ in range(200)]
    return {
        "rows": len(y),
        "profiles": len(grouped),
        "mae": float(mean_absolute_error(y, predicted)),
        "rmse": float(np.sqrt(mean_squared_error(y, predicted))),
        "bias": float(errors.mean()),
        "median_absolute_error": float(np.median(np.abs(errors))),
        "profile_weighted_mae": float(profile_maes.mean()),
        "profile_bootstrap_mae_95_interval": np.quantile(
            bootstrap, [0.025, 0.975]
        ).tolist(),
    }


def conformal_offset(scores, alpha=0.2):
    scores = np.asarray(scores, dtype=float)
    if (
        not 0 < alpha < 1
        or scores.ndim != 1
        or not len(scores)
        or not np.isfinite(scores).all()
    ):
        raise ValueError("invalid_calibration_scores")
    rank = math.ceil((len(scores) + 1) * (1 - alpha))
    if rank > len(scores):
        return None
    return max(0.0, float(np.sort(scores)[rank - 1]))


def complete_profiles(rows, residuals, depths):
    by_key = {}
    for row, residual in zip(rows, residuals, strict=True):
        if row["depth_m"] in depths:
            profile = by_key.setdefault(
                row["profile_key"], {"split": row["split"], "values": {}}
            )
            if row["split"] != profile["split"]:
                raise ValueError("profile_split_leakage")
            if row["depth_m"] in profile["values"]:
                raise ValueError("duplicate_profile_depth")
            profile["values"][row["depth_m"]] = residual
    result = {split: [] for split in SPLITS}
    for profile in by_key.values():
        if len(profile["values"]) == len(depths):
            result[profile["split"]].append([profile["values"][z] for z in depths])
    return {
        key: np.array(value, dtype=float).reshape(-1, len(depths))
        for key, value in result.items()
    }


def profile_experiment(rows, residuals, variable, config):
    depths = [z for z in config["standard_depths_m"] if z <= 500]
    groups = complete_profiles(rows, residuals, depths)
    result = {
        "method": "weighted-discrete-FPCA-prototype-v1",
        "depths_m": depths,
        "complete_profiles": {key: len(value) for key, value in groups.items()},
        "limitations": [
            "Complete-case 10–500m prototype; not a sparse functional-data model.",
            "No expert labels or validated quiet periods; false-alert rate and event recall unknown.",
        ],
    }
    train, cal, test = groups["train"], groups["calibration"], groups["test"]
    if len(train) < 20 or len(cal) < 10 or not len(test):
        return result | {"status": "insufficient_complete_profiles"}
    scale = np.maximum(
        train.std(axis=0, ddof=1), 0.05 if variable == "temperature_c" else 0.01
    )
    centered = train.mean(axis=0)
    z = np.array(depths)
    widths = np.diff(z)
    weights = np.r_[widths[0] / 2, (widths[:-1] + widths[1:]) / 2, widths[-1] / 2]
    weights /= weights.sum()

    def standardized(values):
        return (values - centered) / scale

    covariance = LedoitWolf().fit(standardized(train))
    pca = PCA(n_components=min(3, len(depths)), svd_solver="full").fit(
        standardized(train) * np.sqrt(weights)
    )

    def score(values):
        s = standardized(values)
        weighted = s * np.sqrt(weights)
        reconstruction = pca.inverse_transform(pca.transform(weighted))
        return {
            "depth_weighted_squared_residual": np.sum(s**2 * weights, axis=1),
            "shrinkage_mahalanobis_squared": covariance.mahalanobis(s),
            "fpca_reconstruction_error": np.sum(
                (weighted - reconstruction) ** 2, axis=1
            ),
        }

    cal_scores, test_scores = score(cal), score(test)
    # Sensitivity diagnostic only, not scientifically labelled event recall.
    perturbation = test.copy()
    perturbation[:, :5] += 1.0 if variable == "temperature_c" else 0.2
    perturbed = score(perturbation)
    result.update(
        status="exploratory",
        scale_floor=0.05 if variable == "temperature_c" else 0.01,
        explained_variance_ratio=pca.explained_variance_ratio_.tolist(),
        test_scores={
            name: {
                "median": float(np.median(value)),
                "median_calibration_percentile": float(
                    np.median([100 * (cal_scores[name] <= v).mean() for v in value])
                ),
                "synthetic_layer_perturbation_median_change": float(
                    np.median(perturbed[name] - value)
                ),
            }
            for name, value in test_scores.items()
        },
    )
    return result


def benchmark(rows, config):
    # Stable scientific profiles cannot appear in multiple partitions, including revisions.
    assignments = {}
    for row in rows:
        if assignments.setdefault(row["profile_key"], row["split"]) != row["split"]:
            raise ValueError("profile_split_leakage")
    report = {
        "status": "exploratory_only",
        "seed": config["seed"],
        "variables": {},
        "limitations": [
            "Convenience pilot sample, not a representative training census or model release.",
            "Temporal partitions may share platforms; independent platform/spatial audits required before promotion.",
            "Bootstrap groups profiles, not floats; serial dependence may make intervals optimistic.",
            "No bathymetry/coast-distance source validated; those features are omitted.",
            "No automatic promotion or adaptive calibration release.",
        ],
    }
    for variable in ("temperature_c", "practical_salinity"):
        selected = [r for r in rows if r["variable"] == variable]
        x, y = features(selected), np.array([r["value"] for r in selected])
        masks = {s: np.array([r["split"] == s for r in selected]) for s in SPLITS}
        counts = {
            s: len({r["profile_key"] for r in selected if r["split"] == s})
            for s in SPLITS
        }
        if not all(counts[s] >= (20 if s == "train" else 10) for s in SPLITS):
            report["variables"][variable] = {
                "status": "insufficient_split_profiles",
                "profile_counts": counts,
            }
            continue
        reference = Climatology().fit(x[masks["train"]], y[masks["train"]])
        clim = reference.predict(x)
        eligible = np.isfinite(clim)
        selected = [r for r, take in zip(selected, eligible, strict=True) if take]
        x, y, clim = x[eligible], y[eligible], clim[eligible]
        masks = {s: np.array([r["split"] == s for r in selected]) for s in SPLITS}
        supported_counts = {
            s: len({r["profile_key"] for r in selected if r["split"] == s})
            for s in SPLITS
        }
        if not all(supported_counts[s] >= (20 if s == "train" else 10) for s in SPLITS):
            report["variables"][variable] = {
                "status": "insufficient_supported_depths",
                "profile_counts": counts,
                "supported_profile_counts": supported_counts,
            }
            continue
        residual = y - clim
        models, candidates = {"climatology": clim}, {}
        for family in ("hgbr", "lightgbm"):
            choices = []
            for leaves in (7, 15):
                if family == "hgbr":
                    model = HistGradientBoostingRegressor(
                        max_iter=60,
                        max_leaf_nodes=leaves,
                        min_samples_leaf=20,
                        l2_regularization=1,
                        early_stopping=False,
                        random_state=config["seed"],
                    )
                else:
                    model = LGBMRegressor(
                        n_estimators=60,
                        num_leaves=leaves,
                        min_child_samples=20,
                        reg_lambda=1,
                        random_state=config["seed"],
                        n_jobs=1,
                        verbosity=-1,
                        deterministic=True,
                        force_col_wise=True,
                    )
                model.fit(x[masks["train"]], residual[masks["train"]])
                predicted = clim + model.predict(x)
                score = metrics(
                    y[masks["tune"]],
                    predicted[masks["tune"]],
                    [r for r in selected if r["split"] == "tune"],
                )["profile_weighted_mae"]
                choices.append((score, leaves, predicted))
            best = min(choices, key=lambda c: c[0])
            candidates[family] = {"num_leaves": best[1], "tuning_profile_mae": best[0]}
            models[family] = best[2]
        evaluation = {}
        test_rows = [r for r in selected if r["split"] == "test"]
        for name, predicted in models.items():
            evaluation[name] = metrics(
                y[masks["test"]], predicted[masks["test"]], test_rows
            )
            evaluation[name]["subgroups"] = {}
            for group in ("arabian", "bay_bengal", "0-100m", "100-500m", "500m+"):
                mask = masks["test"] & np.array(
                    [
                        (
                            r["longitude"] < 80
                            if group == "arabian"
                            else r["longitude"] >= 80
                            if group == "bay_bengal"
                            else r["depth_m"] <= 100
                            if group == "0-100m"
                            else 100 < r["depth_m"] <= 500
                            if group == "100-500m"
                            else r["depth_m"] > 500
                        )
                        for r in selected
                    ]
                )
                evaluation[name]["subgroups"][group] = metrics(
                    y[mask],
                    predicted[mask],
                    [r for r, take in zip(selected, mask, strict=True) if take],
                )
        quantiles = []
        for quantile in (0.1, 0.5, 0.9):
            model = LGBMRegressor(
                objective="quantile",
                alpha=quantile,
                n_estimators=60,
                num_leaves=candidates["lightgbm"]["num_leaves"],
                min_child_samples=20,
                reg_lambda=1,
                random_state=config["seed"],
                n_jobs=1,
                verbosity=-1,
                deterministic=True,
                force_col_wise=True,
            )
            model.fit(x[masks["train"]], residual[masks["train"]])
            quantiles.append(clim + model.predict(x))
        q = np.column_stack(quantiles)
        crossing = float(np.any(np.diff(q, axis=1) < 0, axis=1).mean())
        q.sort(axis=1)  # Deterministic rearrangement applied before calibration.
        cal_scores = {}
        for i, row in enumerate(selected):
            if row["split"] == "calibration":
                score = max(q[i, 0] - y[i], y[i] - q[i, 2], 0)
                cal_scores[row["profile_key"]] = max(
                    cal_scores.get(row["profile_key"], 0), score
                )
        offset = conformal_offset(list(cal_scores.values()))
        uncertainty = {
            "nominal_coverage": 0.8,
            "calibration_unit": "maximum_score_per_profile",
            "calibration_profiles": len(cal_scores),
            "crossing_rate_before_rearrangement": crossing,
            "offset": offset,
            "interpretation": "Predictive variability of observations around fixed normal, not confidence in the climatological mean; dependent profiles invalidate an unconditional coverage guarantee.",
        }
        if offset is not None:
            test = masks["test"]
            inside = (y >= q[:, 0] - offset) & (y <= q[:, 2] + offset)
            uncertainty.update(
                test_row_coverage=float(inside[test].mean()),
                test_mean_width=float((q[test, 2] - q[test, 0] + 2 * offset).mean()),
                test_simultaneous_profile_coverage=float(
                    np.mean(
                        [
                            inside[
                                np.array([r["profile_key"] == p for r in selected])
                            ].all()
                            for p in {r["profile_key"] for r in test_rows}
                        ]
                    )
                ),
            )
        report["variables"][variable] = {
            "status": "exploratory",
            "profile_counts": counts,
            "supported_profile_counts": supported_counts,
            "unsupported_depth_rows": int((~eligible).sum()),
            "selected_on_tuning_only": candidates,
            "test_metrics": evaluation,
            "uncertainty": uncertainty,
            "profile_anomaly": profile_experiment(
                selected, y - models["lightgbm"], variable, config
            ),
        }
    return report
