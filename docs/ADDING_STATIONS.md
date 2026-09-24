# Add original practice stations with Codex

The bank is `data/stations.json`, a JSON array. Each station uses the existing schema:

```json
{
  "title": "A descriptive internal title",
  "category": "teamwork",
  "difficulty": "medium",
  "scenario": "A concrete, original situation the candidate can read in 60 seconds.",
  "questions": ["Question one?", "Question two?", "Question three?", "Question four?"],
  "model_answers": ["Answer one", "Answer two", "Answer three", "Answer four"],
  "rubric_focus": ["listening", "fairness", "proportionate action"],
  "source_type": "original_ai_reviewed"
}
```

The short example answers above are placeholders; production answers must each contain 90–120 English words. The `source_type` is an internal synthetic-content label, not independent expert certification. Existing titles and scenarios should be preserved because changing them can change generated station IDs.

## Suggested Codex prompt

> Extend this project's original MMI practice bank from 30 toward 100 stations in batches of 8–16. Read `data/stations.json`, `tests/test_station_bank.py`, and the app's normalization code first. Keep all existing stations unchanged. Use the existing eight category keys and allocate additions so category counts differ by at most one. For each station, write a concrete scenario and exactly four connected questions with distinct purposes, followed by four natural spoken-English reference answers of 90–120 words each. Answer only the current question, with at most two developed points; avoid repeating one answer across all four questions. Include interpersonal, reflective, ethical, and non-clinical situations. Do not require specialist medical knowledge or invent laws/statistics. Make stakes, candidate role, and available information clear. Use original wording and scenarios, not confidential interview recalls or commercial question-bank content. Review for duplicate scenarios, cultural stereotypes, implausible authority, overpromising, and dense checklist answers. Run the existing station tests and the full test suite. Report the added themes and any questions requiring human review. Do not alter the UI, scoring logic, existing history, or API settings.

## Review before merging

- Can the scenario be understood within the reading time?
- Does each question ask for something distinguishable: action, reasoning, changed circumstances, reflection, or outcome?
- Can each answer be spoken comfortably in a minute, without rushing through a checklist?
- Are alternatives and reasonable disagreement possible?
- Does the candidate act within their stated role, respect confidentiality, and avoid guarantees beyond their control?
- Are culturally sensitive examples respectful and specific rather than stereotyped?
- Are any factual medical/legal claims verified or replaced with a reasoning-focused formulation?
- Are category counts balanced, and are titles/scenarios sufficiently distinct from existing entries?

Run `python -m pytest -q` after editing. Automated checks verify shape, word counts, and category distribution; human review is still needed for educational quality. Grow in reviewed batches rather than generating seventy stations and assuming that all are good.
