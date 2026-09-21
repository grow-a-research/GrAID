"""
run_essay_agreement.py — computes every AI-vs-professor essay agreement
number the paper reports, from the final 200-essay dataset.

This exists because the agreement figures quoted in earlier drafts
(QWK, the professor-pairwise benchmark, the leave-one-professor-out
comparison) were computed ad hoc and never saved, so nothing in the
repository could reproduce them. Everything here is derived from files
on disk and is re-runnable.

Two QWK binnings are reported side by side on purpose:

  * half-point units (0.0, 0.5, ... 15.0) — the definition written into
    the Methodology chapter
  * whole-point units (0, 1, ... 15)      — the binning used for the
    figures quoted in earlier drafts

They are not guaranteed to agree, and the paper's stated success
criterion ("AI-professor kappa should not be lower than the professors'
mean pairwise kappa by more than .10") has a thin enough margin that the
binning can decide whether it is met. Reporting both makes that visible
instead of hiding it behind one number.

Aggregate results go to a committed markdown file; the per-essay table
stays in dress_data/, which is gitignored, because per-essay DREsS
scores are not ours to publish.

Run from repo root:

    python -m classification_model.run_essay_agreement
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .dress_pipeline import MAX_TOTAL_POINTS

DATA_DIR = Path(__file__).resolve().parent / "dress_data"
COMBINED_PATH = DATA_DIR / "final_200_combined.csv"
# Per-professor scores arrive in two pieces: the original cohort and the 28
# freshly-graded replacements. _raw_professor_scores.pkl holds the original
# 200 INCLUDING the 28 that were later replaced, so it covers only 172 of the
# essays in the final dataset on its own. The combined CSV concatenates both
# (228 rows, per-criterion scores as JSON lists) and is also readable across
# pandas versions, which the pickles are not.
RAW_SCORES_CSV = DATA_DIR / "_raw_professor_scores_combined.csv"
RAW_SCORES_PKL = DATA_DIR / "_raw_professor_scores.pkl"
REPLACEMENT_PKL = DATA_DIR / "_replacement_28_raw.pkl"
PER_ESSAY_OUT = DATA_DIR / "essay_agreement_per_essay.csv"
RESULTS_OUT = Path(__file__).resolve().parent / "essay_agreement_results.md"

AGREEMENT_THRESHOLD_PCT = 10.0   # Methodology: "normalized difference at most 10%"
QWK_ABSOLUTE_TARGET = 0.70       # Methodology: Williamson et al. (2012)
QWK_MAX_GAP = 0.10               # Methodology: gap below professors' mean pairwise
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 42
BAND_ORDER = ["Poor", "Fair", "Good", "Excellent"]


def round_half_up(x: np.ndarray) -> np.ndarray:
    """
    Round .5 away from zero.

    numpy rounds halves to even, which silently reassigns any score
    landing exactly on a boundary — the same class of bug that put six
    essays in the wrong band in build_final_200_dataset.py. Scores here
    are non-negative, so floor(x + 0.5) is enough.
    """
    return np.floor(np.asarray(x, dtype=float) + 0.5)


def to_units(scores: np.ndarray, unit: float) -> np.ndarray:
    """Snap 0-15 scores onto a grid of the given step."""
    return np.round(round_half_up(np.asarray(scores, dtype=float) / unit) * unit, 3)


def categories_for(unit: float) -> np.ndarray:
    """Every category on the rating scale, whether or not it was used."""
    return np.round(np.arange(0.0, MAX_TOTAL_POINTS + unit, unit), 3)


def qwk(rater_a: np.ndarray, rater_b: np.ndarray, unit: float) -> float:
    """
    Quadratic weighted kappa, written out as the Methodology chapter
    states it rather than pulled from a library, so the reported number
    and the printed formula cannot drift apart.

        QWK = 1 - sum(w_ij * O_ij) / sum(w_ij * E_ij)
        w_ij = (i - j)^2 / (k - 1)^2

    E is the outer product of the two raters' marginals. Categories come
    from the full defined scale, so unused categories contribute zero
    rather than changing k.
    """
    cats = categories_for(unit)
    index = {value: position for position, value in enumerate(cats)}
    k = len(cats)
    n = len(rater_a)

    a = to_units(rater_a, unit)
    b = to_units(rater_b, unit)

    observed = np.zeros((k, k))
    for x, y in zip(a, b):
        observed[index[x], index[y]] += 1
    observed /= n

    marginal_a = observed.sum(axis=1)
    marginal_b = observed.sum(axis=0)
    expected = np.outer(marginal_a, marginal_b)

    positions = np.arange(k)
    weights = (positions[:, None] - positions[None, :]) ** 2 / (k - 1) ** 2

    denominator = (weights * expected).sum()
    if denominator == 0:
        return float("nan")
    return 1.0 - (weights * observed).sum() / denominator


def load_raw_professor_scores() -> pd.DataFrame:
    """
    Per-criterion scores for every professor, as columns of 5-element lists.

    Reads the CSV form first. Falling back to the pickle only works when
    the running pandas is new enough to deserialize it; when it is not,
    the pickle raises NotImplementedError rather than anything readable,
    so the failure is translated into an actionable message.
    """
    if RAW_SCORES_CSV.exists():
        raw = pd.read_csv(RAW_SCORES_CSV)
        for column in ("content", "org", "lang"):
            raw[column] = raw[column].apply(json.loads)
        return raw

    try:
        pieces = [pd.read_pickle(RAW_SCORES_PKL)]
        if REPLACEMENT_PKL.exists():
            pieces.append(pd.read_pickle(REPLACEMENT_PKL))
        return pd.concat(pieces, ignore_index=True)
    except (NotImplementedError, ValueError, AttributeError) as exc:
        raise SystemExit(
            f"{RAW_SCORES_PKL.name} was written by a different pandas than this one "
            f"(running {pd.__version__}) and cannot be read: {exc}\n"
            f"Regenerate {RAW_SCORES_CSV.name} with the interpreter that wrote the "
            "pickle, converting content/org/lang to JSON lists."
        ) from exc


def load_data() -> tuple[pd.DataFrame, np.ndarray]:
    """
    Returns the merged per-essay frame and a (n_essays, 5) matrix of each
    professor's 0-15 total, in the dataset's essay order.
    """
    combined = pd.read_csv(COMBINED_PATH)
    raw = load_raw_professor_scores()

    merged = combined.merge(raw, on="essay_id", how="inner", validate="one_to_one")
    if len(merged) != len(combined):
        raise SystemExit(
            f"{len(combined) - len(merged)} of {len(combined)} essays have no raw "
            "professor scores — the two files are out of sync, stop and reconcile them."
        )

    # zip() would silently truncate a row whose three criteria disagree on
    # rater count, quietly dropping a professor from that essay's consensus.
    rater_counts = {
        len(row[column]) for _, row in merged.iterrows() for column in ("content", "org", "lang")
    }
    if len(rater_counts) != 1:
        raise SystemExit(
            f"Essays disagree on how many professors scored them: {sorted(rater_counts)}. "
            "Reconcile the raw scores before computing agreement."
        )

    per_professor = np.array([
        [c + o + l for c, o, l in zip(row["content"], row["org"], row["lang"])]
        for _, row in merged.iterrows()
    ], dtype=float)

    merged["ai_total"] = merged["score_pct"] / 100.0 * MAX_TOTAL_POINTS
    merged["prof_total"] = per_professor.mean(axis=1)
    merged["prof_total_from_csv"] = merged["prof_score_pct"] / 100.0 * MAX_TOTAL_POINTS
    merged["signed_diff_pct"] = merged["score_pct"] - merged["prof_score_pct"]
    merged["abs_diff_pct"] = merged["signed_diff_pct"].abs()

    return merged, per_professor


def bootstrap_gaps(
    ai_total: np.ndarray,
    per_professor: np.ndarray,
    unit: float,
) -> dict:
    """
    Resample essays to get confidence intervals on the professor-vs-AI
    kappa gap, and the share of resamples meeting the paper's <= .10 rule.

    Both framings are bootstrapped. The consensus gap compares the AI
    against the five-rater mean; the individual gap compares it against
    single professors, which is the like-for-like match to professors
    being judged pairwise and is the one with the thin margin. A point
    estimate that close to the threshold says very little on its own.
    """
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n_essays = len(ai_total)
    n_professors = per_professor.shape[1]
    pairs = list(itertools.combinations(range(n_professors), 2))
    consensus_gaps, individual_gaps = [], []

    for _ in range(BOOTSTRAP_N):
        pick = rng.integers(0, n_essays, n_essays)
        resampled = per_professor[pick]
        ai_resampled = ai_total[pick]

        pair_mean = float(np.mean([
            qwk(resampled[:, i], resampled[:, j], unit) for i, j in pairs
        ]))
        consensus_gaps.append(pair_mean - qwk(ai_resampled, resampled.mean(axis=1), unit))
        individual_gaps.append(pair_mean - float(np.mean([
            qwk(ai_resampled, resampled[:, j], unit) for j in range(n_professors)
        ])))

    def summarize(values: list[float]) -> dict:
        finite = np.array([v for v in values if np.isfinite(v)])
        return {
            "ci_low": float(np.percentile(finite, 2.5)),
            "ci_high": float(np.percentile(finite, 97.5)),
            "share_within_criterion": float((finite <= QWK_MAX_GAP).mean()),
        }

    return {
        "consensus": summarize(consensus_gaps),
        "individual": summarize(individual_gaps),
    }


def analyse(merged: pd.DataFrame, per_professor: np.ndarray) -> dict:
    ai_total = merged["ai_total"].to_numpy()
    prof_total = merged["prof_total"].to_numpy()
    ai_pct = merged["score_pct"].to_numpy()
    prof_pct = merged["prof_score_pct"].to_numpy()
    n_professors = per_professor.shape[1]
    pairs = list(itertools.combinations(range(n_professors), 2))

    results: dict = {
        "n_essays": len(merged),
        "n_professors": n_professors,
        "reconstruction_max_delta": float(
            (merged["prof_total"] - merged["prof_total_from_csv"]).abs().max()
        ),
    }

    pearson = stats.pearsonr(ai_pct, prof_pct)
    spearman = stats.spearmanr(ai_pct, prof_pct)
    results["pearson_r"] = float(pearson.statistic)
    results["pearson_p"] = float(pearson.pvalue)
    results["spearman_rho"] = float(spearman.statistic)

    within = merged["abs_diff_pct"] <= AGREEMENT_THRESHOLD_PCT
    results["agreement_within_threshold_pct"] = float(within.mean() * 100)
    results["mean_abs_diff_pct"] = float(merged["abs_diff_pct"].mean())
    results["mean_signed_diff_pct"] = float(merged["signed_diff_pct"].mean())
    results["sd_signed_diff_pct"] = float(merged["signed_diff_pct"].std(ddof=1))

    results["by_unit"] = {}
    for label, unit in (("half_point", 0.5), ("whole_point", 1.0)):
        ai_vs_consensus = qwk(ai_total, prof_total, unit)
        pair_kappas = [
            qwk(per_professor[:, i], per_professor[:, j], unit) for i, j in pairs
        ]
        ai_vs_individual = [
            qwk(ai_total, per_professor[:, j], unit) for j in range(n_professors)
        ]
        prof_pairwise_mean = float(np.mean(pair_kappas))
        gap_consensus = prof_pairwise_mean - ai_vs_consensus
        gap_individual = prof_pairwise_mean - float(np.mean(ai_vs_individual))
        boot = bootstrap_gaps(ai_total, per_professor, unit)

        results["by_unit"][label] = {
            "unit": unit,
            "n_categories": len(categories_for(unit)),
            "ai_vs_consensus": ai_vs_consensus,
            "prof_pairwise_mean": prof_pairwise_mean,
            "prof_pairwise_min": float(np.min(pair_kappas)),
            "prof_pairwise_max": float(np.max(pair_kappas)),
            "ai_vs_individual_mean": float(np.mean(ai_vs_individual)),
            "ai_vs_individual_all": [float(x) for x in ai_vs_individual],
            "gap_consensus": gap_consensus,
            "gap_individual": gap_individual,
            "meets_absolute_target": bool(ai_vs_consensus >= QWK_ABSOLUTE_TARGET),
            "meets_gap_criterion": bool(gap_consensus <= QWK_MAX_GAP),
            "meets_gap_criterion_individual": bool(gap_individual <= QWK_MAX_GAP),
            "bootstrap": boot,
        }

    # Leave-one-professor-out: is the AI further from a held-out consensus
    # than a real professor is? This is the fairest like-for-like read.
    loo = []
    for j in range(n_professors):
        others = per_professor[:, [i for i in range(n_professors) if i != j]].mean(axis=1)
        loo.append({
            "professor": j + 1,
            "professor_vs_others_r": float(stats.pearsonr(per_professor[:, j], others).statistic),
            "ai_vs_others_r": float(stats.pearsonr(ai_total, others).statistic),
        })
    results["leave_one_out"] = loo
    results["loo_professor_mean_r"] = float(np.mean([d["professor_vs_others_r"] for d in loo]))
    results["loo_ai_mean_r"] = float(np.mean([d["ai_vs_others_r"] for d in loo]))

    band_rows = []
    for band in BAND_ORDER:
        subset = merged[merged["gt_band"] == band]
        if subset.empty:
            continue
        band_rows.append({
            "band": band,
            "n": int(len(subset)),
            "mean_signed_diff_pct": float(subset["signed_diff_pct"].mean()),
            "mean_abs_diff_pct": float(subset["abs_diff_pct"].mean()),
            "within_threshold_pct": float(
                (subset["abs_diff_pct"] <= AGREEMENT_THRESHOLD_PCT).mean() * 100
            ),
        })
    results["by_band"] = band_rows

    abs_err = merged["abs_diff_pct"].to_numpy()
    results["confidence_vs_error_r"] = float(stats.pearsonr(merged["confidence"], abs_err).statistic)
    results["spread_vs_error_r"] = float(stats.pearsonr(merged["spread"], abs_err).statistic)

    # Both raters' distributions, which the Methodology requires alongside QWK.
    results["distributions"] = {
        "ai": pd.Series(to_units(ai_total, 1.0)).value_counts().sort_index().to_dict(),
        "professor": pd.Series(to_units(prof_total, 1.0)).value_counts().sort_index().to_dict(),
    }
    return results


def render(results: dict) -> str:
    half = results["by_unit"]["half_point"]
    whole = results["by_unit"]["whole_point"]

    def tick(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    lines: list[str] = []
    add = lines.append

    add("# Essay Agreement Results — AI vs. Professor Consensus")
    add("")
    raw_source = RAW_SCORES_CSV if RAW_SCORES_CSV.exists() else RAW_SCORES_PKL
    add(f"Generated by `classification_model/run_essay_agreement.py` from "
        f"`{COMBINED_PATH.name}` and `{raw_source.name}`.")
    add("")
    add(f"- Essays: **{results['n_essays']}**, each scored by "
        f"**{results['n_professors']}** professors on Content / Organization / Language (0-15 total)")
    add(f"- Consensus reconstruction check: largest disagreement with the stored "
        f"consensus is **{results['reconstruction_max_delta']:.6f}** points")
    add("")
    add("Aggregate statistics only — no essay text or per-essay scores appear in this file.")
    add("")

    add("## 1. Score agreement")
    add("")
    add("| Measure | Value |")
    add("|---|---|")
    add(f"| Pearson r (AI vs. professor mean) | **{results['pearson_r']:.4f}** (p = {results['pearson_p']:.3g}) |")
    add(f"| Spearman rho | {results['spearman_rho']:.4f} |")
    add(f"| Essay Score Agreement (within {AGREEMENT_THRESHOLD_PCT:.0f}%) | **{results['agreement_within_threshold_pct']:.1f}%** |")
    add(f"| Mean absolute normalized difference | {results['mean_abs_diff_pct']:.2f}% |")
    add(f"| Mean signed difference (AI - professor) | {results['mean_signed_diff_pct']:+.2f}% |")
    add(f"| SD of signed difference | {results['sd_signed_diff_pct']:.2f}% |")
    add("")

    add("## 2. Quadratic weighted kappa, both binnings")
    add("")
    add("| | Half-point units (paper) | Whole-point units |")
    add("|---|---|---|")
    add(f"| Categories (k) | {half['n_categories']} | {whole['n_categories']} |")
    add(f"| AI vs. professor consensus | **{half['ai_vs_consensus']:.4f}** | **{whole['ai_vs_consensus']:.4f}** |")
    add(f"| Professor pairwise mean | {half['prof_pairwise_mean']:.4f} | {whole['prof_pairwise_mean']:.4f} |")
    add(f"| Professor pairwise range | {half['prof_pairwise_min']:.4f}–{half['prof_pairwise_max']:.4f} | {whole['prof_pairwise_min']:.4f}–{whole['prof_pairwise_max']:.4f} |")
    add(f"| AI vs. individual professor (mean) | {half['ai_vs_individual_mean']:.4f} | {whole['ai_vs_individual_mean']:.4f} |")
    add("")

    add("## 3. Methodology success criteria")
    add("")
    add("| Criterion | Target | Half-point | Whole-point |")
    add("|---|---|---|---|")
    add(f"| Absolute QWK | >= {QWK_ABSOLUTE_TARGET:.2f} | {half['ai_vs_consensus']:.4f} ({tick(half['meets_absolute_target'])}) | {whole['ai_vs_consensus']:.4f} ({tick(whole['meets_absolute_target'])}) |")
    add(f"| Gap below professor pairwise mean | <= {QWK_MAX_GAP:.2f} | {half['gap_consensus']:.4f} ({tick(half['meets_gap_criterion'])}) | {whole['gap_consensus']:.4f} ({tick(whole['meets_gap_criterion'])}) |")
    add(f"| Same gap, AI vs. individual professors | <= {QWK_MAX_GAP:.2f} | {half['gap_individual']:.4f} ({tick(half['meets_gap_criterion_individual'])}) | {whole['gap_individual']:.4f} ({tick(whole['meets_gap_criterion_individual'])}) |")
    add("")
    add(f"Bootstrap on the gap ({BOOTSTRAP_N} resamples of essays, seed {BOOTSTRAP_SEED}):")
    add("")
    add(f"| Gap | Binning | 95% CI | Resamples meeting <= {QWK_MAX_GAP:.2f} |")
    add("|---|---|---|---|")
    for label, block in (("Half-point", half), ("Whole-point", whole)):
        for framing in ("consensus", "individual"):
            boot = block["bootstrap"][framing]
            add(f"| vs. {framing} | {label} | [{boot['ci_low']:.4f}, {boot['ci_high']:.4f}] | "
                f"**{boot['share_within_criterion'] * 100:.1f}%** |")
    add("")
    add("The comparison against individual professors is the like-for-like one: a mean "
        "of five raters is less noisy than any single rater, so holding the AI to the "
        "consensus while professors are judged pairwise understates the AI.")
    add("")

    add("## 4. Leave-one-professor-out")
    add("")
    add("Each professor, and the AI, correlated against the mean of the remaining four.")
    add("")
    add("| Held out | Professor vs. others | AI vs. same others |")
    add("|---|---|---|")
    for row in results["leave_one_out"]:
        add(f"| Professor {row['professor']} | {row['professor_vs_others_r']:.4f} | {row['ai_vs_others_r']:.4f} |")
    add(f"| **Mean** | **{results['loo_professor_mean_r']:.4f}** | **{results['loo_ai_mean_r']:.4f}** |")
    add("")

    add("## 5. Difference by professor-assigned band")
    add("")
    add("| Band | n | Mean signed diff | Mean absolute diff | Within threshold |")
    add("|---|---|---|---|---|")
    for row in results["by_band"]:
        add(f"| {row['band']} | {row['n']} | {row['mean_signed_diff_pct']:+.2f}% | "
            f"{row['mean_abs_diff_pct']:.2f}% | {row['within_threshold_pct']:.1f}% |")
    add("")

    add("## 6. Do the AI's own uncertainty signals predict its error?")
    add("")
    add("| Signal | Correlation with absolute error |")
    add("|---|---|")
    add(f"| Self-reported confidence | {results['confidence_vs_error_r']:.4f} |")
    add(f"| Per-criterion spread | {results['spread_vs_error_r']:.4f} |")
    add("")

    add("## 7. Score distributions (whole points, 0-15)")
    add("")
    add("| Score | AI | Professor consensus |")
    add("|---|---|---|")
    all_scores = sorted(set(results["distributions"]["ai"]) | set(results["distributions"]["professor"]))
    for score in all_scores:
        add(f"| {score:g} | {results['distributions']['ai'].get(score, 0)} | "
            f"{results['distributions']['professor'].get(score, 0)} |")
    add("")
    return "\n".join(lines)


def main() -> None:
    if not COMBINED_PATH.exists():
        raise SystemExit(f"Missing required input: {COMBINED_PATH}")
    if not RAW_SCORES_CSV.exists() and not RAW_SCORES_PKL.exists():
        raise SystemExit(
            f"Missing raw professor scores: expected {RAW_SCORES_CSV} or {RAW_SCORES_PKL}"
        )

    merged, per_professor = load_data()
    results = analyse(merged, per_professor)

    merged[[
        "essay_id", "score_pct", "prof_score_pct", "ai_total", "prof_total",
        "signed_diff_pct", "abs_diff_pct", "confidence", "spread", "gt_band",
    ]].to_csv(PER_ESSAY_OUT, index=False)

    RESULTS_OUT.write_text(render(results), encoding="utf-8")

    half = results["by_unit"]["half_point"]
    whole = results["by_unit"]["whole_point"]
    print(f"n = {results['n_essays']} essays, {results['n_professors']} professors")
    print(f"consensus reconstruction max delta: {results['reconstruction_max_delta']:.6f}")
    print(f"Pearson r                : {results['pearson_r']:.4f}")
    print(f"Essay Score Agreement    : {results['agreement_within_threshold_pct']:.1f}% within {AGREEMENT_THRESHOLD_PCT:.0f}%")
    print()
    print(f"{'':28s} {'half-point':>12s} {'whole-point':>12s}")
    print(f"{'AI vs consensus QWK':28s} {half['ai_vs_consensus']:12.4f} {whole['ai_vs_consensus']:12.4f}")
    print(f"{'Professor pairwise mean':28s} {half['prof_pairwise_mean']:12.4f} {whole['prof_pairwise_mean']:12.4f}")
    print(f"{'Gap (criterion <= 0.10)':28s} {half['gap_consensus']:12.4f} {whole['gap_consensus']:12.4f}")
    print(f"{'  meets gap criterion':28s} {str(half['meets_gap_criterion']):>12s} {str(whole['meets_gap_criterion']):>12s}")
    print(f"{'  meets >= 0.70 target':28s} {str(half['meets_absolute_target']):>12s} {str(whole['meets_absolute_target']):>12s}")
    print()
    print(f"wrote {RESULTS_OUT}")
    print(f"wrote {PER_ESSAY_OUT}  (gitignored — per-essay DREsS scores)")


if __name__ == "__main__":
    main()
