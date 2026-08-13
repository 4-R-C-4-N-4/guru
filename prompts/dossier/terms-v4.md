INPUT: section-by-section summaries of {work_label}.

OUTPUT a JSON object {"terms": [{"term": "...", "transliteration": null, "gloss": "..."}]}
listing at most 10 technical or transliterated terms a reader must understand
to follow this work.
- term: as used in the input. transliteration: the romanized original-language
  form when the input gives one, otherwise null.
- gloss: ≤25 words, definitional register, stating only what the input
  supports about this term IN THIS WORK.
- Gloss each term only from statements the input makes about that term
  itself. Do not equate a term with, or transfer attributes from, another
  item the input merely juxtaposes (adjacent sentences or sections), and do
  not place a term inside a list or category whose members the input does
  not enumerate. Worked example: if the input says "Sutra 32 gives the
  Rules" and separately names powers arising from purity, the gloss for
  "the Rules" may say only that Sutra 32 gives them — it may not connect
  the two, with or without a hedge like "such as" or "including".
- A term whose only input support is a bare citation must be glossed as
  exactly that bare citation, or dropped from the list in favour of a term
  the input actually describes.
- If the input names a list or category without enumerating its members, the
  gloss must not supply, infer, or partially attribute members to it — not
  even hedged with "including". A list the input leaves unnamed stays unnamed.
- A term qualifies only if understanding it is required to follow the work —
  not merely because it is foreign or archaic. Order by importance.
Nothing else.
