INPUT: a summary of {section_span} of {work_label}.

OUTPUT a single JSON object: {"title": "...", "synopsis": "..."}
- title: 2–6 words naming what this span contains, in the register of a
  table of contents ("The Creation of Humanity", not "Amazing Origins!").
  The title must use only vocabulary present in the input summary or the
  span label — never a genre or classificatory label (parable, myth, hymn,
  elements, transmigration) the input does not itself use, even when a
  standard one exists for this material, and never a work's conventional
  chapter or section title unless the input itself states it.
- synopsis: at most 2 sentences compressing the input summary. Descriptive
  present tense. No interpretation. If the input names a list or category
  without enumerating its members, do not assert or imply membership in it —
  not even hedged with "including" or "such as". Items the input merely
  juxtaposes stay juxtaposed.
- Compression must never blur: do not merge distinct one-to-one assignments
  or pairings into a blended list; do not substitute a looser condition for
  the input's exact condition or qualifier; keep who-does-what-to-whom
  exactly as the input has it. When two sentences cannot hold a detail
  exactly, OMIT it — an absent detail is acceptable, a distorted one is not.
Nothing else.
