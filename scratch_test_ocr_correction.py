import sys
sys.path.insert(0, '.')
import ai_grader

raw_text = """AI text generators Using AI tools like ChatGPT for schoolwork can violate academic integrity, but it really depends on how it's used. Academic integrity means doing your own thinking and giving credits for ideas that aren't yours. If a student copies an AI-written essay and submits it as their own work, that's dishonest because it doesn't reflect the student's real understanding or effort. It's similar to copying from a classmate or the internet However, AI isn't automatically bad. If a student uses it to brainstorm ideas, check grammar, or understand a difficult topic that's more like using a tutor or study tool, which is generally acceptable. The line is crossed when the AI does the actual thinking or writing for the student.

In short, AI itself isn't the problem. It's how honestly a student uses it. Schools should focus on teaching responsible use rather than banning it completely, since honesty and effort are what academic integrity is really about."""

print("RAW INPUT:")
print(raw_text)
print()
print("=" * 80)
print()
corrected = ai_grader.correct_ocr_text(raw_text)
print("CORRECTED OUTPUT:")
print(corrected)
print()
print("=" * 80)
print()
print("Same text?", raw_text.strip() == corrected.strip())
