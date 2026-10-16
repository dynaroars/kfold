# kfold paper (PLDI 2027)

Format: `acmart`, `acmsmall`, `review,anonymous,nonacm` (single column, 10 pt).
Limit: 20 pages of text, excluding Data-Availability Statement, references,
and supplementary material; the AI Use section counts. Double blind.
Submission deadline: 12 Nov 2026 AoE. Call: https://pldi27.sigplan.org/track/pldi-2027-papers

## Build

```bash
make all      # pdflatex, bibtex, pdflatex x2
make clean
```

| File | Role |
|------|------|
| `paper.tex` | Main document |
| `paper.sty` | Shared preamble / macros |
| `paper.bib` | Bibliography |
| `makefile` | Build targets |
| `figure/` | Figures |
