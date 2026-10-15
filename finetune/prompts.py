"""
prompts.py — the transcription prompts used for training and evaluation.

LIVE_PROMPT is a verbatim copy of the prompt in ocr_pipeline.qwen_ocr_lines.
It is copied rather than imported so this folder never depends on (or
modifies) the live pipeline; check_prompt_sync.py verifies the copy is still
identical to the live source.

ABSTAIN_PROMPT is LIVE_PROMPT with the "illegible" sentence replaced so the
model is allowed to answer "[illegible]" instead of guessing. The live prompt
tells the model to always guess, which directly conflicts with abstention
examples, so abstention is only ever trained/evaluated under this variant.
Switching the live app to it would be a separate, deliberate decision.
"""

LIVE_PROMPT = (
    "Transcribe EXACTLY what is written in this image line, character-for-character. "
    "This is a handwriting recognition task, not a writing-correction task — report "
    "the ink on the page even when it is grammatically wrong. "
    "Preserve all spelling errors, capitalization, and punctuation exactly as written. "
    "Do NOT correct grammar or spelling. Do NOT add or drop a letter just because it "
    "would be the grammatically expected form — for example, if the handwriting reads "
    "\"solve problem\" (singular, no trailing 's'), transcribe it as \"solve problem\", "
    "even though \"solve problems\" reads more naturally. Visual evidence always wins "
    "over what sounds correct. Do not add, remove, or rephrase any words. "
    "If a word is illegible, transcribe your best visual guess of the actual letters — "
    "do not substitute a different, more common real word. Output only the transcribed "
    "text, nothing else."
)

_LIVE_ILLEGIBLE_SENTENCE = (
    "If a word is illegible, transcribe your best visual guess of the actual letters — "
    "do not substitute a different, more common real word."
)

_ABSTAIN_SENTENCE = (
    "If a word is hard to read, transcribe your best visual guess of the actual letters — "
    "do not substitute a different, more common real word. If the writing is so unreadable "
    "that you cannot make out the letters at all, output exactly [illegible] for that "
    "stretch instead of guessing."
)

assert _LIVE_ILLEGIBLE_SENTENCE in LIVE_PROMPT
ABSTAIN_PROMPT = LIVE_PROMPT.replace(_LIVE_ILLEGIBLE_SENTENCE, _ABSTAIN_SENTENCE)

PROMPTS = {"live": LIVE_PROMPT, "abstain": ABSTAIN_PROMPT}
