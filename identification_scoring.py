"""
Identification scoring — exact match against teacher-defined accepted answers.

The teacher stores every answer they will accept in ExamQuestion.correct_answer,
separated by "|" (e.g. "Rizal | Jose Rizal | Dr. Jose Rizal"). A student answer
gets full credit if it matches any one of them, otherwise zero — no fuzzy
matching and no partial credit, so the system never decides on its own what
counts as correct.

Before comparing, both sides have leading/trailing whitespace trimmed and
internal runs of whitespace collapsed to a single space. Case is ignored
unless the teacher marked the question case-sensitive. Nothing else (hyphens,
punctuation, spelling) is normalized — variants the teacher wants to accept
must be listed explicitly.
"""
from __future__ import annotations

import re

ACCEPTED_ANSWER_SEP = "|"

# A letter directly touching a digit ("D130be", "c9") — typical of OCR
# misreading handwriting, rare in real identification answers.
_LETTER_DIGIT_MIX = re.compile(r"[^\W\d_]\d|\d[^\W\d_]")

# The printed "Q<n>." label that sits to the left of the answer box, pulled
# into the crop when a page warped from two ArUco markers drifts sideways.
# A student's own answer never opens with it.
_QUESTION_LABEL = re.compile(r"^Q\s*\d+\s*[.:)]", re.I)


def parse_accepted_answers(correct_answer: str | None) -> list[str]:
    """Split the stored correct_answer into its non-empty accepted answers."""
    if not correct_answer:
        return []
    return [a.strip() for a in correct_answer.split(ACCEPTED_ANSWER_SEP) if a.strip()]


def _normalize(text: str, case_sensitive: bool) -> str:
    collapsed = " ".join(text.split())
    return collapsed if case_sensitive else collapsed.casefold()


def score_identification(
    correct_answer: str | None,
    given: str | None,
    max_points: float,
    case_sensitive: bool,
) -> tuple[float, str]:
    """
    Return (score, feedback) for one identification answer.

    Feedback keeps the "Expected: X. Your answer: Y. <verdict>" shape the
    Results page parses.
    """
    accepted = parse_accepted_answers(correct_answer)
    given = (given or "").strip()
    expected_label = f" {ACCEPTED_ANSWER_SEP} ".join(accepted)

    given_norm = _normalize(given, case_sensitive)
    matched = bool(given) and any(
        _normalize(a, case_sensitive) == given_norm for a in accepted
    )

    if matched:
        score, verdict = max_points, "Exact match."
    elif case_sensitive and given and any(
        _normalize(a, False) == _normalize(given, False) for a in accepted
    ):
        score, verdict = 0.0, "Incorrect (capitalization does not match — this question is case-sensitive)."
    else:
        score, verdict = 0.0, "Incorrect."

    return score, f"Expected: {expected_label}. Your answer: {given}. {verdict}"


def looks_unreadable(correct_answer: str | None, given: str | None) -> bool:
    """
    Rule-based check for OCR text that is probably a misread, not the
    student's real answer. Only used to route a wrong answer to teacher
    review — it never changes the score.

    Flags text that:
      - is empty, or
      - spans several lines (the answer box holds one line, so extra lines
        are picked-up noise), or
      - opens with the printed "Q<n>." label, unless one of the teacher's
        accepted answers opens that way itself, or
      - has a letter directly touching a digit ("D130be", "c9"), unless one
        of the teacher's accepted answers contains that pattern itself.
    """
    text = (given or "").strip()
    if not text or "\n" in text:
        return True
    if _QUESTION_LABEL.match(text):
        return not any(
            _QUESTION_LABEL.match(a) for a in parse_accepted_answers(correct_answer)
        )
    if _LETTER_DIGIT_MIX.search(text):
        return not any(
            _LETTER_DIGIT_MIX.search(a) for a in parse_accepted_answers(correct_answer)
        )
    return False
