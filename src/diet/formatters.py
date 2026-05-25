"""Display formatters for intake decisions and energy balance.

Pure functions; no I/O. The 7 labels mirror ``IntakeDecision.label`` exactly so
adding a new label in ``diet.intake`` forces a corresponding case here (or the
``ValueError`` fallback fires at runtime).
"""
from diet.intake import IntakeDecision


def format_intake_display(d: IntakeDecision) -> str:
    """Render an IntakeDecision as a single human-readable line (spec §5)."""
    label = d.label
    if label == "recorded_authoritative":
        return f"摂取 {d.intake_kcal:,} kcal (記録)"
    if label == "recorded_partial_high":
        return f"摂取 {d.intake_kcal:,} kcal (部分入力、過去平均超え)"
    if label == "estimated_avg_supplement":
        return (
            f"摂取 推定 {d.intake_kcal:,} kcal "
            f"(記録 {d.recorded_part:,} + 平均補完 {d.supplement_part:,}、N={d.n_samples})"
        )
    if label == "estimated_baseline_supplement":
        return (
            f"摂取 推定 {d.intake_kcal:,} kcal "
            f"(記録 {d.recorded_part:,} + baseline 補完 {d.supplement_part:,})"
        )
    if label == "recorded_no_baseline":
        return f"摂取 記録 {d.intake_kcal:,} kcal (cold start、baseline 未設定)"
    if label == "estimated_avg":
        return (
            f"摂取 推定 {d.intake_kcal:,} kcal "
            f"(過去 14 日 complete day 平均, N={d.n_samples})"
        )
    if label == "estimated_baseline":
        return (
            f"摂取 推定 {d.intake_kcal:,} kcal "
            f"(init baseline、N={d.n_samples} < SAMPLE_FLOOR)"
        )
    if label == "unconfirmed":
        return "摂取量未確定 (記録なし、過去データ不足、baseline 未設定)"
    raise ValueError(f"unknown label: {label}")


def format_balance(
    intake_kcal: int | None,
    bmr: float,
    exercise_kcal: int,
    steps: int,
    distance_km: float,
    weight_kg: float,
) -> str:
    """Render today's energy balance line.

    balance = (BMR + exercise) - intake  (= burn - intake)
      balance < 0 → intake > burn → 赤字 (over consumed)
      balance > 0 → burn > intake → 黒字 (calorie deficit, weight loss territory)
    """
    if intake_kcal is None:
        return "(収支算出不可: 摂取量未確定)"
    burn = bmr + exercise_kcal
    balance = int(burn) - intake_kcal
    bmr_i = int(bmr)
    if balance < 0:
        deficit = -balance  # how much intake exceeds burn
        # ~0.035 kcal/step is a common rough estimate for a 70kg adult walking.
        extra_steps = int(deficit / 0.035) if weight_kg else 0
        extra_km = deficit / 60.0
        return (
            f"摂取 {intake_kcal:,} vs 消費 (BMR {bmr_i:,} + 運動 {exercise_kcal:,}) "
            f"= {balance:+,} kcal (赤字)\n"
            f"    黒字化まで あと約 {extra_steps:,} 歩 (または 走 {extra_km:.1f}km)"
        )
    return (
        f"摂取 {intake_kcal:,} vs 消費 (BMR {bmr_i:,} + 運動 {exercise_kcal:,}) "
        f"= {balance:+,} kcal (黒字)"
    )
