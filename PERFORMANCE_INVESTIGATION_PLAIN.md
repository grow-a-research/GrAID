# What we found when we looked into why grading felt slow

## The starting point

The complaint that kicked this off was simple: clicking "process" on a
submission caused a visible spike in the laptop's CPU, the rented graphics
card on Vast.ai didn't look like it was working very hard, and grading a
single essay took somewhere around 20 to 30 seconds. That felt slow for what
should, in principle, be a quick task — read some handwriting, score it
against a rubric, done.

The first real discovery was that "grading" is actually two completely
separate jobs wearing one name. Scoring the essay against the rubric is a
quick call out to a cloud AI service — it comes back in about a second or
two, every time, and was never the problem. The slow part is entirely the
handwriting-reading step: turning a photo of a student's handwritten answer
into plain text. That step needs a real graphics card, which is exactly why
a rented GPU is involved in the first place. So the whole investigation from
that point on was really about one question: why does reading handwriting
take so long, and what can be done about it?

## Reading several lines at once instead of one at a time

The handwriting-reading AI was working through a page one line at a time,
like a tutor who re-reads the entire assignment instructions before looking
at each individual sentence, over and over, line after line. Every single
line paid the same startup cost before the AI even got to reading it. The
fix was to hand the AI several lines at once and let it read all of them in
a single pass — the same total amount of reading, but without paying that
setup cost again and again for every line.

At the same time, we noticed the rented machine had two graphics cards, but
the handwriting-reading AI is small enough to comfortably fit on just one of
them. Splitting it across both cards wasn't making anything faster — if
anything, it meant the two cards had to keep passing partial work back and
forth to each other, which is pure overhead with no upside. We pinned the
AI to a single card instead.

Put together, these two changes brought the reported time down from around
25 seconds to about 19 seconds in the very first real-world test.

## Straightening the photo without over-cleaning it first

Before any handwriting can be read, the system has to straighten out the
scanned photo — phones rarely take a perfectly flat, perfectly aligned
picture of a piece of paper. To do that straightening, it first has to spot
four small alignment markers printed on the page, a bit like corner
stickers used to line up a picture frame.

It turned out the system was running a fairly heavy photo-cleanup process
across the *entire* full-resolution photo just to make those four small
stickers easier to spot — comparable to giving an entire poster a deep
clean before checking four small corners of it. That cleanup step alone
was taking over five seconds on a real test photo.

The fix was to shrink the photo down first, spot the four markers on that
much smaller copy — which is plenty good enough, since the markers don't
need full resolution to be recognizable — and then use their positions to
straighten the *original, full-quality* photo. Nothing about the actual
handwriting-reading quality changed; only the marker-finding step got
faster. Measured on the same real submission, that step dropped from about
5.4 seconds down to about 1.3 seconds — roughly four times faster.

## Turning the lights on

At some point it became clear that a whole set of diagnostic messages we'd
added — little notes meant to say "this step took this many seconds" — were
never actually showing up anywhere. Digging in, the cause was almost funny:
nothing in the entire project had ever switched on the basic setting that
lets those messages get printed to the screen at all. It's the equivalent
of wiring a whole building with speakers and never actually turning on the
sound system. Once that one setting was flipped, every diagnostic message
that had already been written started showing up properly, which is what
made the rest of this investigation possible in the first place.

## A text-cleanup step was quietly rewriting sentence structure

Handwriting recognition doesn't always cleanly capture where one line of
text ends and a new paragraph begins, so there's a cleanup step that tries
to stitch fragmented lines back into proper paragraphs. Testing on a real
student's essay revealed this step was being overzealous: instead of only
rejoining a sentence that had been awkwardly split across two lines, it was
also merging several separate, complete sentences into one long run-on
paragraph — just because they were all discussing the same general topic.
That's not what it was supposed to do, so its instructions were tightened
to only rejoin text when a line clearly doesn't end in proper punctuation
and is obviously left hanging mid-thought.

## A mistake introduced while fixing the mistake above, caught the same night

While rewording those instructions, one of the example phrases used the
word "become" in a way that unintentionally taught the AI a bad habit: on
the very next real test, it started writing things like "here is the
original text... it becomes... here is the corrected text" directly into
the student's saved answer — essentially stapling together a rough draft
and a final draft and grading the whole stapled mess as if it were the
student's real answer. That inflated the stored text to roughly double its
proper length and produced a grade computed against garbled, duplicated
text rather than what the student actually wrote.

The evidence was concrete: the saved answer, which should have been about
367 characters, had ballooned to 746 — roughly double — and had been scored
a 7 out of a possible total, when the honest score against the real,
unpolluted answer turned out to be 5.

This was caught by directly checking what had actually been saved for that
one essay, tracing it back to the exact wording that triggered it, and
fixing it two ways: rewording the instructions to remove the trigger, and —
more importantly — adding a general safeguard that watches for this whole
*category* of mistake (the cleaned-up text containing the entire original
text buried inside it) rather than just watching for that one specific
phrase. That way, if the AI finds some other way to make the same kind of
mistake in the future, it still gets caught. After the fix, the same essay
was re-processed and came back clean, with the correct score of 5.

## Leaving a setting blank was quietly loading the AI onto the wrong computer

There's a setting that tells the local program where to find the rented
graphics card. Leaving it blank was supposed to simply mean "handwriting
reading isn't available right now" — a safe, harmless state. Instead, it
was quietly loading the *entire* handwriting-reading AI directly onto the
laptop's own, much weaker graphics card, without saying so clearly. That's
a strange thing for a "leave it blank" option to do, and was fixed so that
leaving it blank now genuinely does nothing, exactly as it always should
have.

## The old rental died, so a new — and cheaper — one took its place

Partway through, the originally rented machine became stuck and
unreachable. A new one was rented to replace it — and because of the
one-graphics-card fix described earlier, a machine with a single graphics
card turned out to be just as capable as the old two-card machine for this
particular workload, at close to half the hourly price: about $0.20 an hour
instead of the old $0.36.

## A picture nobody was looking at

Every time the rented machine read a line of handwriting, it was also
drawing a picture showing exactly where it thought each line was, and
sending that picture all the way back over the internet — even though
nothing in the actual grading process ever displayed it. Only one separate,
rarely-used debug page in the app actually shows that picture. That
unnecessary picture-sending was switched off for the real grading process
and left in place only for that debug page. The saving was measured directly:
the round-trip cost sat around 6.0-6.2 seconds before this change and about
5.9 seconds after — only a quarter-second or so of real improvement, but it
was pure waste being removed regardless, and the small size of the saving
turned out to be an important clue for the next section.

## What's left, and why it's being left alone

After all of the above, one cost remained stubbornly constant no matter
what else changed: sending a photo to the rented machine and getting the
result back consistently took around six seconds — 6.2, then 6.1, then 5.9
across three separate real tests — whether the AI had just started up or
had already been running for a while, and whether or not the unnecessary
picture was included in the response. That consistency is actually the
useful finding — it means those six seconds are simply the real, physical
cost of sending data to a computer that lives somewhere else on the
internet and getting an answer back, not a bug hiding somewhere in the
code.

The handwriting-reading step itself told a more interesting story. On the
very first request after the rented machine's AI had just started up, it
took about 12.5 seconds to read just 4 lines of handwriting — roughly 3
seconds per line. On a later request, once the AI had already been running
for a while, it read 14 lines — over three times as much text — in about
7.5 seconds total, only around half a second per line. That's roughly a
six-fold improvement per line once the system was properly warmed up,
confirming that the earlier "read several lines at once" fix was working
correctly all along; the first request after a restart simply pays a
one-time startup cost that later requests don't.

The only way to remove that cost entirely would be to run the whole system
directly on the rented machine, so nothing ever has to travel over the
internet in the first place — but that was tried directly, and it turned
out to be slower overall in practice, on top of introducing a real risk:
it would mean the class and grading data lives on a rented, temporary
machine instead of safely on hand. For those reasons, it's being left as a
known, accepted cost rather than something to keep chasing.

## The numbers, at a glance

| What was measured | Before | After |
|---|---|---|
| Whole-essay processing time (first user-reported test) | ~25 seconds | ~19 seconds |
| Photo-straightening / marker-finding step | ~5.4 seconds | ~1.3 seconds |
| Sending a photo over and getting text back (network cost only) | ~6.1-6.2 seconds | ~5.9 seconds |
| Reading handwriting, per line, right after startup | ~3.1 seconds/line | — |
| Reading handwriting, per line, once warmed up | — | ~0.5 seconds/line |
| Text-cleanup bug's damage on one real essay | text ballooned to 746 characters (from 367); scored 7 | fixed: correct length, correct score of 5 |
| Rental machine cost | ~$0.36/hour (2 graphics cards) | ~$0.20/hour (1 graphics card, same real-world speed) |

## Where things ended up

Reading straightforward handwriting is now noticeably faster and more
reliable than when this investigation started, and two real correctness
bugs were caught and fixed along the way — not just speed problems. What
remains is a roughly six-second, well-understood cost of talking to a
rented computer over the internet, which isn't something further code
changes are likely to remove.
