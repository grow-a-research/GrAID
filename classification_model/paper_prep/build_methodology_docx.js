const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
} = require("docx");

const FONT = "Times New Roman";
const PAGE = { size: { width: 12240, height: 15840 } }; // US Letter, DXA
const MARGINS = { top: 1440, bottom: 1440, left: 1800, right: 1440 }; // 1" all, 1.25" left (binding)

function body(text, opts = {}) {
  return new Paragraph({
    spacing: { after: 200, line: 480, lineRule: "auto" }, // double-spaced
    alignment: AlignmentType.JUSTIFIED,
    children: [new TextRun({ text, font: FONT, size: 24, ...opts })],
  });
}

function h(text, level) {
  return new Paragraph({
    heading: level,
    spacing: { before: 360, after: 200 },
    children: [new TextRun({ text, font: FONT, bold: true, size: level === HeadingLevel.HEADING_1 ? 28 : 24 })],
  });
}

function bullet(text) {
  return new Paragraph({
    numbering: { reference: "bullet-list", level: 0 },
    spacing: { after: 120, line: 480, lineRule: "auto" },
    children: [new TextRun({ text, font: FONT, size: 24 })],
  });
}

function cell(text, opts = {}) {
  return new TableCell({
    width: { size: opts.width || 2000, type: WidthType.DXA },
    shading: opts.header ? { type: ShadingType.CLEAR, fill: "D9E1F2" } : undefined,
    children: [new Paragraph({
      children: [new TextRun({ text, font: FONT, size: 22, bold: !!opts.header })],
    })],
  });
}

const rubricTable = new Table({
  columnWidths: [1400, 2600, 2600, 2600],
  rows: [
    new TableRow({ children: [
      cell("Level", { header: true, width: 1400 }),
      cell("Content", { header: true, width: 2600 }),
      cell("Organization", { header: true, width: 2600 }),
      cell("Language", { header: true, width: 2600 }),
    ]}),
    new TableRow({ children: [
      cell("5", { width: 1400 }),
      cell("Well-developed, clearly relevant argument; strong, specific reasons and examples throughout", { width: 2600 }),
      cell("Very effective structure, easy to follow, strong coherence devices, one main idea per paragraph", { width: 2600 }),
      cell("Sophisticated, varied vocabulary and collocations; grammar/spelling/punctuation correct throughout", { width: 2600 }),
    ]}),
    new TableRow({ children: [
      cell("4", { width: 1400 }),
      cell("Mostly developed and relevant; reasons/examples present but under-elaborated in places", { width: 2600 }),
      cell("Generally well-structured and easy to follow; minor coherence or paragraph-focus lapses", { width: 2600 }),
      cell("Good vocabulary range; occasional minor errors that don't impede understanding", { width: 2600 }),
    ]}),
    new TableRow({ children: [
      cell("3", { width: 1400 }),
      cell("Argument present but development is inconsistent; some reasons/examples generic or thin", { width: 2600 }),
      cell("Structure discernible but uneven; some ideas hard to follow or paragraphs mix multiple ideas", { width: 2600 }),
      cell("Adequate vocabulary; noticeable errors, occasionally distracting", { width: 2600 }),
    ]}),
    new TableRow({ children: [
      cell("2", { width: 1400 }),
      cell("Argument unclear or weakly related to the prompt; few or unconvincing supporting reasons/examples", { width: 2600 }),
      cell("Weak structure; confusing sequencing of ideas; coherence devices rare or misused", { width: 2600 }),
      cell("Limited vocabulary; frequent errors that sometimes obscure meaning", { width: 2600 }),
    ]}),
    new TableRow({ children: [
      cell("1", { width: 1400 }),
      cell("Little to no relevant argument; supporting reasons/examples missing or off-topic", { width: 2600 }),
      cell("Little discernible structure; ideas appear disconnected or randomly ordered", { width: 2600 }),
      cell("Very limited vocabulary; pervasive errors that significantly impede understanding", { width: 2600 }),
    ]}),
  ],
});

const doc = new Document({
  numbering: {
    config: [{
      reference: "bullet-list",
      levels: [{ level: 0, format: "bullet", text: "\u2022", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 720, hanging: 360 } } } }],
    }],
  },
  sections: [{
    properties: { page: { ...PAGE, margin: MARGINS } },
    children: [
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 400 },
        children: [new TextRun({ text: "Essay Rubric-Band Classification Model", font: FONT, bold: true, size: 28 })],
      }),

      h("Overview and Purpose", HeadingLevel.HEADING_1),
      body(
        "In addition to the AI-based rubric grading engine described in the preceding sections, the "
        + "system incorporates an explicit, computable classification model that predicts an essay's "
        + "overall performance level \u2014 Poor, Fair, Good, or Excellent \u2014 from the outputs already "
        + "produced by the AI grader. This model was developed to provide a transparent, statistically "
        + "grounded complement to the AI grader's rubric-based scoring: whereas the AI grader produces a "
        + "numeric score through a single language-model call, the classification model is a small, "
        + "fully interpretable formula whose coefficients and decision thresholds can be reported, "
        + "inspected, and evaluated independently of the underlying language model."
      ),
      body(
        "The classification model does not replace or alter the AI grader's scoring procedure. It "
        + "operates downstream, consuming three quantities already produced during rubric-based grading "
        + "\u2014 the essay's overall score percentage, the AI grader's self-reported confidence, and the "
        + "spread (disagreement) across the essay's per-criterion scores \u2014 and maps them to a "
        + "performance-band prediction."
      ),

      h("Classification Model Design", HeadingLevel.HEADING_1),
      body(
        "An ordinal logistic regression was selected as the classification model. This choice reflects "
        + "the inherent structure of the target variable: the four performance bands (Poor, Fair, Good, "
        + "Excellent) have a natural order, and an ordinal model respects that ordering during estimation "
        + "and prediction, unlike a generic multi-class classifier that would treat the four categories "
        + "as unrelated. The model was implemented using the OrderedModel class from the Python "
        + "statsmodels library, fit by maximum likelihood estimation with a logit link function."
      ),
      body(
        "The model takes the following functional form. A continuous latent score z is computed as a "
        + "weighted linear combination of the three predictors:"
      ),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 120, after: 120 },
        children: [new TextRun({
          text: "z = \u03B21\u00B7score_pct + \u03B22\u00B7confidence + \u03B23\u00B7spread",
          font: FONT, italics: true, size: 24,
        })],
      }),
      body(
        "The latent score z is then compared against three estimated threshold parameters "
        + "(\u03C41 < \u03C42 < \u03C43) to determine the predicted band: Poor if z is below \u03C41, Fair if z "
        + "falls between \u03C41 and \u03C42, Good if z falls between \u03C42 and \u03C43, and Excellent if z "
        + "meets or exceeds \u03C43. All six parameters (\u03B21, \u03B22, \u03B23, \u03C41, \u03C42, \u03C43) are "
        + "estimated directly from the training data rather than fixed in advance, allowing the model to "
        + "learn the mapping between the AI grader's outputs and the true performance level empirically."
      ),

      h("Input Features", HeadingLevel.HEADING_1),
      body(
        "The three predictors are derived directly from the AI grader's structured, per-criterion "
        + "grading output for a given essay, without any additional processing or manual annotation:"
      ),
      bullet("score_pct \u2014 the essay's total AI-assigned score, expressed as a percentage of the maximum achievable score across all rubric criteria."),
      bullet("confidence \u2014 the AI grader's self-reported certainty in its own scoring, averaged across the individual criteria; the grading prompt instructs the model to consider both text legibility and how clear-cut the rubric-level judgment is."),
      bullet("spread \u2014 the difference between the highest and lowest per-criterion score percentages assigned to the essay, capturing the degree of internal disagreement across the rubric's Content, Organization, and Language criteria."),

      h("Grading Procedure and Rubric", HeadingLevel.HEADING_1),
      body(
        "All essays used for training and evaluating the classification model were graded using the "
        + "system's structured (analytic) grading procedure, in which the AI grader scores each rubric "
        + "criterion independently in a single call and the total score is computed programmatically as "
        + "the sum of the individual criterion scores, rather than trusted from any total the model might "
        + "report on its own. A holistic alternative, in which the AI grader assigns a single overall "
        + "score without a per-criterion breakdown, was evaluated separately (see Section [Evaluation of "
        + "Grading Modality]) and was not adopted, as the analytic approach preserved the spread feature "
        + "and the per-criterion transparency needed to explain a grade to an evaluator, at only a modest "
        + "cost in raw score correlation."
      ),
      body(
        "The rubric used throughout consists of three criteria \u2014 Content, Organization, and Language "
        + "\u2014 each scored on a five-point scale with explicit level descriptions, summarized in Table "
        + "[X]."
      ),
      rubricTable,
      body(""),
      body(
        "For each criterion, the grading prompt supplies the level descriptions together with their "
        + "corresponding numeric bands (derived by taking the midpoint between adjacent level scores), "
        + "instructing the model to first identify which level's description best matches the response and "
        + "then select a specific score within that level's numeric band."
      ),

      h("Dataset and Ground Truth", HeadingLevel.HEADING_1),
      body(
        "The classification model was trained and evaluated on a set of 200 essays drawn from DREsS_New "
        + "(Yoo et al., 2025), a publicly available corpus of English-as-a-Foreign-Language essays "
        + "authored by undergraduate students and independently scored by English-education experts. "
        + "DREsS_New essays were selected over locally collected handwritten submissions for this "
        + "component specifically because they required no optical character recognition step, allowing "
        + "the classification model's development to proceed independently of, and in parallel with, "
        + "handwriting-recognition data collection, and to isolate evaluation of the AI grader's scoring "
        + "logic from any handwriting-transcription accuracy concerns."
      ),
      body(
        "Ground truth for the 200 essays was established by five General Education faculty members from "
        + "the researchers' institution, who scored each essay against the same three-criterion rubric "
        + "used by the AI grader. Fifteen of the 200 essays were scored independently by all five "
        + "evaluators; the remaining 185 were divided into five non-overlapping subsets of approximately "
        + "37 essays each, with each subset assigned to a single evaluator. Each evaluator's subset was "
        + "itself stratified to include a proportional mix of essays across the full range of DREsS_New's "
        + "own score distribution, so that no single evaluator's subset was skewed toward any particular "
        + "quality range. Where multiple evaluators scored the same essay, the ground-truth score was "
        + "taken as the mean of their per-criterion scores."
      ),
      body(
        "An earlier design used DREsS_New's own published expert scores directly as ground truth, "
        + "avoiding the need for local faculty grading. This was discontinued after a direct comparison, "
        + "on a shared subset of essays scored by both DREsS_New's own raters and the institution's own "
        + "faculty, found only moderate agreement between the two rater populations (Pearson r "
        + "\u2248 0.54), with the institution's evaluators applying a consistently stricter standard by "
        + "roughly 22 percentage points on average. DREsS_New's own scores were judged not to be a valid "
        + "proxy for the target evaluator population, motivating the shift to direct faculty scoring "
        + "described above."
      ),

      h("Performance Band Definition", HeadingLevel.HEADING_1),
      body(
        "Performance bands (Poor, Fair, Good, Excellent) were defined using the quartiles of the "
        + "ground-truth score distribution across the 200-essay dataset, rather than a fixed, externally "
        + "defined scale. Essays falling in the bottom quartile of scores were labeled Poor, the second "
        + "quartile Fair, the third quartile Good, and the top quartile Excellent. This approach was "
        + "adopted after an externally defined scale (adapted from DREsS_New's own scoring convention) "
        + "was found to be unsuitable for the institution's evaluators' scoring distribution, under which "
        + "the highest attainable band would have been empirically unreachable. Defining bands from the "
        + "quartiles of the actual ground-truth distribution ensures that all four performance levels are "
        + "populated and approximately balanced, which both reflects the evaluators' own grading behavior "
        + "and avoids a degenerate classification problem in which one or more bands contain no cases."
      ),

      h("Prompt Refinement", HeadingLevel.HEADING_1),
      body(
        "Two refinements were made to the AI grader's prompt specifically for essays without an OCR "
        + "step (i.e., DREsS_New essays), applied only when the input is known to be clean, digitally "
        + "typed text; the grading prompt used for real, scanned student submissions is unaffected by "
        + "either change. First, since the confidence instruction in the base prompt asks the model to "
        + "weigh both text legibility and rubric-judgment clarity, an additional note instructs the model "
        + "to disregard text legibility entirely for clean-text input and to base confidence solely on "
        + "how clear-cut the rubric-level judgment is. Second, an explicit calibration instruction was "
        + "added directing the model not to default to the middle of the scale out of excess caution, and "
        + "to assign top- or bottom-level scores confidently when an essay's quality clearly warrants it "
        + "\u2014 addressing an observed tendency of the grading model to avoid the extreme ends of the "
        + "rubric's scoring bands."
      ),
      body(
        "A further refinement incorporated four worked examples directly into the grading prompt for "
        + "DREsS_New essays: one real, faculty-scored essay per performance band, each accompanied by a "
        + "faculty-written rationale explaining why the essay was scored as it was and, specifically, why "
        + "it did not qualify for the adjacent band above or below. The four exemplar essays were chosen "
        + "as the essay closest to the numerical center of its band's score range, to avoid anchoring the "
        + "model's judgment on an ambiguous or borderline case. This refinement was motivated by the "
        + "observation that the AI grader's own generated justifications, being a product of the same "
        + "judgment process being calibrated, could not supply new corrective information; genuine, "
        + "independent human reasoning was used instead."
      ),

      h("Training and Evaluation Procedure", HeadingLevel.HEADING_1),
      body(
        "The ordinal logistic regression was fit on the full 200-essay dataset to obtain the final "
        + "reported coefficients and thresholds. Model performance was assessed using stratified 5-fold "
        + "cross-validation: the dataset was partitioned into five folds preserving the overall band "
        + "distribution, and for each fold the model was refit on the remaining four folds and used to "
        + "predict the held-out fold, so that every essay's predicted band came from a model that had not "
        + "seen that essay during training. This procedure avoids the optimistic bias of evaluating a "
        + "model on the same data used to fit it."
      ),
      body(
        "Three metrics were computed from the cross-validated predictions: exact-match accuracy (the "
        + "proportion of essays whose predicted band matched their ground-truth band exactly), adjacent-"
        + "band agreement (the proportion of essays whose predicted band was either exact or one band "
        + "away, given the four bands' natural ordering), and a full confusion matrix. Cross-validated "
        + "accuracy was additionally compared against a majority-class baseline \u2014 the accuracy "
        + "obtainable by always predicting the single most frequent band in the dataset, independent of "
        + "any input features \u2014 to establish whether the trained model provides genuine predictive "
        + "value beyond the dataset's class distribution alone. Finally, the statistical significance of "
        + "each of the three input features' coefficients was assessed via the Wald test p-values reported "
        + "by statsmodels, to determine which of the three inputs contribute genuine, non-random predictive "
        + "signal to the fitted model."
      ),
    ],
  }],
});

Packer.toBuffer(doc).then((buf) => {
  require("fs").writeFileSync(
    "C:\\Users\\ASUS\\OneDrive\\Desktop\\Files\\John\\GrAID-Repo\\classification_model\\paper_prep\\Classification_Model_Methodology.docx",
    buf
  );
  console.log("Wrote Classification_Model_Methodology.docx");
});
