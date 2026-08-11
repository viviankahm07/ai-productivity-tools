# Examples

Drop past cover letters in this directory as `.txt` or `.docx` files. Each
file is one letter.

## Expected format

- One letter per file, `.txt` or `.docx`.
- File contents: just the letter body text (or a normal Word doc) — no
  metadata headers required. `.docx` files are read with python-docx; if
  one turns out to actually be plain text saved under a `.docx` name,
  `src/retrieval.py` falls back to reading it as plain text automatically.
- Role type: filenames are NOT parsed for a role-type prefix. Instead, map
  each filename to a role type in `role_types.json` in this directory
  (keys are exact filenames, values must match
  `src/agents/planner.VALID_ROLE_TYPES`: `"quant_trading"`, `"swe"`, or
  `"markets_and_st"`). A file with no entry in `role_types.json` still
  gets ranked by similarity, it just never receives the role-type boost.

These files are embedded (`src/retrieval.embed_examples()`) and searched
(`src/retrieval.retrieve_similar()`) to find the most similar past letters
for a given job description, boosted by role-type match.
