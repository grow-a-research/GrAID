"""
few_shot_examples.py — builds the worked-example prompt section from 4
real, professor-graded exemplar essays (one per band: Poor/Fair/Good/
Excellent), each with a condensed, contrastive rationale explaining why it
sits where it does relative to its neighboring band(s).

Source rationale: written by a professor per-criterion, tied directly to
the GRAID-RUBRICS.pdf level descriptions. Condensed here to keep prompt
token cost manageable — this is real human reasoning, not AI-generated,
which is the whole point (see the conversation this came from: an AI's own
justification would just be circular, reinforcing whatever it already
believes).
"""

from __future__ import annotations

from .dress_pipeline import load_dress_bulk

# essay_id -> condensed rationale (kept short deliberately; full essay text
# is pulled in separately so the model sees real writing, not just a
# description of it)
_RATIONALE = {
    "DRESS-2151": (
        "POOR (38.7%). Content 2.4/5, Organization 1.6/5, Language 1.8/5. "
        "Organization is the real failure: paragraphs mix multiple unrelated "
        "sub-points (e.g. a price complaint and a taste complaint in one "
        "paragraph) rather than having one controlling idea each — this is "
        "the 'paragraphs mix multiple ideas' failure mode (level 2), not a "
        "random-order collapse (level 1). Content is comparatively strong "
        "(concrete numbers, on-topic) but isolated — that alone can't lift "
        "Organization into 'generally well-structured' territory, so this "
        "essay sits well clear of Fair, not borderline."
    ),
    "DRESS-1781": (
        "FAIR (60.0%). Content 3.2/5, Organization 3.0/5 (all 5 raters agreed "
        "exactly), Language 2.8/5. All three criteria sit flatly in level-3: "
        "an argument is present but reasons stay at assertion level without "
        "real elaboration; structure is discernible but uneven (a statistic "
        "gets mixed with an unmarked rebuttal); language has real recurring "
        "errors ('deviding', 'indivisualism', 'stressness') that pull toward "
        "level 2 without quite reaching it. Nothing here clears level 4's "
        "'under-elaborated only in places' bar, but nothing collapses to "
        "level 1-2 either — uniformly mediocre-but-functional, not borderline "
        "in either direction."
    ),
    "DRESS-1449": (
        "GOOD (68.0%). Content 3.6/5, Organization 3.4/5, Language 3.2/5. "
        "Content earns level 4 through genuine first-person reflection "
        "('I thought that the test make students to study before, but when I "
        "became a college student, I changed my mind') — real personal "
        "grounding, not just a listed assertion. Organization is clear and "
        "easy to follow with only one minor lapse (an unplanned new idea "
        "tacked onto the closing). Not Excellent: no criterion makes a "
        "level-5 case — Content's reflection never gets concretely "
        "illustrated, Organization's lapse is real (level 5 requires none), "
        "and Language shows a genuinely wide rater split reflecting real "
        "inconsistency, not the 'correct throughout' standard Excellent needs."
    ),
    "DRESS-567": (
        "EXCELLENT (81.3%). Content 4.2/5, Organization 4.8/5 (four raters "
        "gave 5), Language 3.2/5. Organization earns level 5 specifically "
        "because of a self-aware closing that acknowledges real complexity "
        "('there can be many other problems... we need to think about this "
        "topic in various aspects') rather than just restating the thesis — "
        "that reflective quality is what separates level 5 from level 4. "
        "Content backs this with a concretely elaborated example, not just "
        "an assertion. Language is a genuine level-3 case (frequent, varied "
        "errors: verb agreement, verb form, articles, spelling) — normally "
        "that alone would suggest Fair/Good, but Organization's near-perfect "
        "score mathematically carries the total past the Excellent floor. "
        "This essay shows a composite score CAN mask real unevenness at the "
        "criterion level — worth the model noticing that one strong "
        "criterion doesn't mean every criterion is strong."
    ),
}

# Ordered Poor -> Excellent so the model sees the scale progress logically
_ORDER = ["DRESS-2151", "DRESS-1781", "DRESS-1449", "DRESS-567"]


def build_few_shot_block() -> str:
    """Builds the full worked-examples prompt section, essay text + rationale."""
    bulk = load_dress_bulk()
    bulk = bulk.set_index("essay_id")

    lines = [
        "Worked examples — 4 real essays, one per performance level, each "
        "with the reasoning for why it sits where it does relative to the "
        "next level. Use these to calibrate your own judgment, especially "
        "at the boundaries between adjacent levels:",
        "",
    ]
    for essay_id in _ORDER:
        essay_text = bulk.loc[essay_id, "essay_text"]
        lines.append(f"--- Example: {essay_id} ---")
        lines.append(f'"{essay_text}"')
        lines.append("")
        lines.append(_RATIONALE[essay_id])
        lines.append("")

    return "\n".join(lines)


# Optional add-on, appended separately by callers who want to test it —
# NOT included in build_few_shot_block() by default, so existing behavior
# (and the 200-essay dataset already graded with it) is unaffected.
#
# Motivated by a measured pattern in the full 200-essay run: AI scores
# compress toward the middle relative to professor scores (Poor essays
# scored ~12pts too high on average, Excellent essays ~6pts too low).
ANTI_COMPRESSION_NOTE = """

One more calibration point, based on a pattern observed in past grading
batches: scores tend to compress toward the middle of the scale — genuinely
weak essays get scored a bit too generously, and genuinely strong essays
get scored a bit too conservatively. Resist this tendency. Score each
criterion strictly against the rubric level it actually matches: a weak
essay should receive a low score even if that feels harsh, and an
excellent essay should receive a high score even if that feels generous.
Do not let one essay's score be pulled toward the middle just because it
is easier to defend a moderate score than an extreme one."""
