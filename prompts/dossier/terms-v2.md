INPUT: section-by-section summaries of {work_label}.

OUTPUT a JSON object {"terms": [{"term": "...", "transliteration": null, "gloss": "..."}]}
listing at most 10 technical or transliterated terms a reader must understand
to follow this work.
- term: as used in the input. transliteration: the romanized original-language
  form when the input gives one, otherwise null.
- gloss: ≤25 words, definitional register, stating only what the input
  supports about this term IN THIS WORK.
- If the input names a list or category without enumerating its members, the
  gloss must not supply, infer, or partially attribute members to it — not
  even hedged with "including". A list the input leaves unnamed stays unnamed.
- A term qualifies only if understanding it is required to follow the work —
  not merely because it is foreign or archaic. Order by importance.
Nothing else.
