INPUT: a summary of {section_span} of {work_label}.

OUTPUT a single JSON object: {"title": "...", "synopsis": "..."}
- title: 2–6 words naming what this span contains, in the register of a
  table of contents ("The Creation of Humanity", not "Amazing Origins!").
- synopsis: at most 2 sentences compressing the input summary. Descriptive
  present tense. No interpretation.
- Compression must never blur: do not merge distinct one-to-one assignments
  or pairings into a blended list; do not substitute a looser condition for
  the input's exact condition or qualifier; keep who-does-what-to-whom
  exactly as the input has it. When two sentences cannot hold a detail
  exactly, OMIT it — an absent detail is acceptable, a distorted one is not.
Nothing else.
