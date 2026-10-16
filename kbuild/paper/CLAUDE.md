# Paper writing rules

- Say "challenges", never "obstacles", for the problems this paper addresses (e.g., "three challenges", not "three obstacles").
- Write "e.g." with the `\eg` macro (`\emph{e.g.}`, defined in `paper.sty`), as `\eg,`, never as plain "e.g.". This matches the style of the papers in ~/Resource/submitted. Do not use "i.e." or an `\ie` macro at all; rephrase instead, e.g., with an apposition ("a goal definition, a list such as `obj-y` that names ..."), a "which" clause, or "so".
- Use formal wording: avoid informal words such as "tell" (write "distinguish"), "a lot", "get", or "pretty".
- Use plain verbs: write "formulate X as Y", never "cast X as Y" (and likewise prefer plain wording over figurative verbs).
- When writing new or revised text, state things directly. Do not use the negative contrast construction "X, not Y" (or "rather than", "instead of") to define a claim; say what it is. Leave existing uses elsewhere in the paper alone unless asked.
- Do not use parentheses in section or subsection titles (e.g., "Composite Objects and Built-in Routes", not "Build Semantics (Composites, need-builtin)").
- Keep figure and table captions short: 2 lines on average, 3 at most. State only what the figure shows; all other detail (setup, counts, thresholds, how to read it) belongs in the main prose that cites the figure, and must be checked to actually be there when a caption is shortened.
- To map main text to parts of a figure, label the figure parts with plain parenthesized numbers, (1), (2), ..., and refer to them in the text the same way, e.g., "the worklist (1)". Do not use circled, filled, or badge-style markers.
- Packages, macros, theorem environments, TikZ libraries, listings styles, comment macros, and `\autoref` names live in `paper.sty`, loaded with `\usepackage{paper}` right after `\documentclass` in `paper.tex`. `paper.tex` holds only the document class line, the content, and (once the evaluation exists) the `\input` of the generated `table/numbers.tex`; do not add `\usepackage`, `\newcommand`, or `\newtheorem` to it.
- Refer to figures, tables, equations, sections, appendices, algorithms, algorithm lines, definitions, theorems, lemmas, and propositions with `\autoref{...}` on a label (`fig:`, `tab:`, `eq:`, `sec:`, `app:`, `alg:`, `line:`, `def:`, `thm:`, `lem:`, `prop:`), as in the lab's other papers, never with hard-coded text such as "Figure 1", "line 12", or "Definition~\ref{...}". Use `~\autoref` mid-sentence, e.g., `as shown in~\autoref{fig:overview}`. The names (Fig., Tab., Eq., §, App., Alg., line, Def., Thm., Lem., Prop.) are defined in `paper.sty`, where every theorem-like environment has its own counter; acmart would otherwise number them all with the theorem counter, and `\autoref` would print "Theorem" for each.
- Write notes and to-dos for the author with `\tl{...}` (the author's comment macro, printed in dark blue as "[TL]: ..."; `\hd` is light blue and `\tvn` is red), never with `\todo{...}`. Set the `usecomment` toggle in `paper.sty` to false for a submission build.
- Each TikZ figure lives in its own file `figure/xxx.tex` (containing only the `tikzpicture`), included from `paper.tex` with `\input{figure/xxx}` inside the `figure` environment. Do not define TikZ drawings inline or as macros in `paper.tex`.
- Keep the paper folder clean: build helpers live in `paper/makefile` as targets, never as separate scripts. Rebuild after every edit to `paper.tex` (`make paper`), one LaTeX run at a time (see `../../../CLAUDE.md`).
- `paper/paper.tex` targets PLDI 2027 (call: https://pldi27.sigplan.org/track/pldi-2027-papers): `\documentclass[acmsmall,screen,review,anonymous,nonacm]{acmart}`, at most 20 pages of text excluding the Data-Availability Statement, references, and supplementary material; the AI Use section counts toward the limit. A "Data-Availability Statement" section precedes the references. Submission deadline: 12 November 2026 AoE. Different fonts or text block are grounds for summary rejection. Appendices go in separate supplementary material.
- Double-blind review: no author names, affiliations, acknowledgments, or identifying URLs in the paper or the supplement. Cite the authors' own prior work in the third person; Nguyen and Nguyen (ICSME 2020) is prior work on symbolic execution of Kbuild Makefiles, described neutrally and without implying author continuity. The artifact is referenced as an anonymized archive.
- `archive/` holds the earlier drafts (`OUTLINE.tex`, the FSE outline `OUTLINE.md`, `kfold.tex`, `skbuild.tex`, `NOTES.md`) for reference; the build does not use them, and they are edited only when asked. `related/` holds PDFs of related papers.

# Project-specific rules (kfold)

- Write numbers as plain numbers in the abstract and in running prose; do not wrap each one in a `\N...` macro. Take the value from `table/numbers.tex` and recheck it when the results change. Tables and generated table bodies still come from `table/*.tex`. The next rule is the older macro-based convention, kept for tables.
- Every evaluation number is a macro from `table/numbers.tex`, and every generated table body is a `table/*.tex` file; `../code/experiments/paper_numbers.py` writes both from `../code/results/` (`make numbers`). Never type a result number by hand and never edit these files. When the text needs a number that has no macro, add the macro to `paper_numbers.py` and regenerate.
- When the results change, recheck the prose as well as the numbers: a regenerated macro can make a qualitative sentence false (for example, which compiled objects lie outside the extracted set, or which ablation matters on which subject). Qualitative claims about results must be checked against the result files (`../code/results/agreement/*.json`, `kmax/`, `devtasks/`, `bench_scaling.json`, `timing.json`).
- Terminology follows Linux usage (`Documentation/kbuild/makefiles.rst`): configuration options or symbols (`CONFIG_*`), goal definitions (`obj-y`, `obj-m`, `lib-y`), composite objects, and descending into subdirectories. Use "build condition" for the formula under which a word, directory route, or object is selected, and reserve "guard" for formulas internal to the analysis (guarded words, the ambient guard, directory reachability guards). The developer-facing `why` command reports a "condition chain".
- Relate the analysis to the programming-languages literature with its standard names: folding branch states is state merging (Kuznetsov et al., PLDI 2012); a variable's value is a variational set (Walkingshaw et al., Onward! 2014), a map from words to guards in which the guards of different words may overlap, and the membership of each word is a Boolean value summary in the sense of MultiSE (Sen et al., ESEC/FSE 2015), whose guards over whole values are disjoint; the analysis as a whole is a variability-aware (lifted) interpretation of the Kbuild subset of GNU Make. Kmax (Gazzillo, ESEC/FSE 2017) already describes itself as a family-based interpreter of Kbuild and relates itself to MultiSE, so never claim to be the first lifted analysis of Kbuild.
- Do not overclaim. Never write "sound and complete", "exact", "guarantees", "eliminates all", or "proves" about the implementation or about empirical agreement; agreement on the tested configurations does not establish correctness for unseen configurations. Theorems concern the core calculus and state their assumptions (word order and multiplicity abstracted, only the constructs of the calculus).
- Describe Kmax accurately and neutrally, crediting what it introduced, and compare the tools on measured facts only. Kmax is fast on the generated scaling benchmark, so the scaling comparison separates per-word guards from path forking; it does not separate kfold from Kmax.

# Content and style (distilled from advisor \tvn comments in the lab's papers)

## Introduction and framing
- Introduce our work early: "In this paper, we ..." appears within the first few paragraphs of the Introduction. Summarize prior work in a few sentences focused on the limitation we address; details belong in Related Work.
- Write for a reader outside the subfield: define every technical term in plain words at first use (e.g., Kconfig, Kbuild, tristate option, goal definition, composite object, SMT). Do not assume the reader knows Linux build or variability jargon.
- Expand every acronym at first use. Do not use `\gls` glossary links heavily.
- Cite or soften every claim that something is a challenge, is demanded, is important, or is common practice.
- Make contributions concrete: the approach or algorithm is one contribution, its implementation and evaluation another. Claim "first" only when no prior work defined the same thing, and present standard practice (e.g., translating Kconfig to propositional constraints, sampling configurations for testing) as standard, with citations to tools that already do it.

## Technical sections
- Open every section, definition, theorem, and lemma with a sentence on its purpose: whether it is our contribution or background, and why the reader needs it.
- Formalism must earn its space: when we formalize, state and prove properties and connect the theorems to the algorithm; otherwise cut the formalism in favor of intuition and examples. A short foundational contribution beats many experiments.
- Follow formal steps with an "Intuitively, ..." explanation in plain terms, and justify every design choice (why this operation, why these features) so that nothing looks like magic or a cherry-picked example.
- Define every symbol before use; remove notation and concepts that are never used later.
- Proofs: give a short proof or proof sketch in the body (PLDI reviewers need not read the supplementary material) and put the full proof in a well-marked appendix referenced with `~\autoref`.
- Algorithms: describe the steps by referring to their line numbers with `~\autoref{line:...}`, and typeset algorithms without "end if" / "end while" lines (algorithm2e `noend` option).
- When a point was made earlier, refer back with `~\autoref{sec:...}` instead of restating it; delete sentences that repeat earlier ones.

## Motivating example
- Keep the motivating example short. Use the concrete instance in place of the general case, finish the example before comparing with other tools, and close with a short paragraph stating the key point.

## Evaluation
- Open the Evaluation with the research questions, then describe the subjects, baselines, and metrics that answer them.
- Justify every number and setting (configurations, timeouts, benchmark sizes, sample sizes, seeds): if it affects results, say how; if it does not, remove it, since unexplained settings read as cherry-picking.
- Prefer established subjects and benchmarks (Linux and BusyBox are the subjects of Kmax's evaluation); when creating new ones, such as the generated scaling Makefiles, give a clear reason and avoid weak phrasing such as "intractable" or "generally".
- Report what affects fairness and reproducibility: the machine, tool versions, thread counts, how times and memory are measured, deviations from stock builds, and the implementation (language, dependencies, anonymized artifact).
- Make every number traceable to a table, figure, or computation. Expand the main result; do not spend text defending small gains or disparaging baselines.
- Do not raise limitations or restrictions that invite questions we cannot answer unless we address them.
- Keep the Evaluation from dominating the paper, and avoid walls of dense text.

## Conclusion and limitations
- The Conclusion gives concluding remarks, insights, implications, and future directions, citing the work that inspires the future directions; it does not re-summarize the results.
- The Limitations section names real assumptions and limits a user of the work should know, and how we mitigate them; no filler paragraphs.

## Presentation
- Introduce and explain every figure and table in the text, and place it near the text that discusses it.
- In the compiled PDF, the last line of a paragraph must contain at least two words. Citations such as "[3]" or "[2]–[4]" do not count as words; an inline equation `$...$` counts as one word. If a paragraph ends with fewer than two words on its last line, rephrase the paragraph (or tie the last words with `~`) and rebuild to check (`make lastline` lists candidates).
- Split long paragraphs into normal paragraphs (not `\paragraph{}` headings), and split long sentences.
- Avoid generic, weak, or meaningless sentences; be specific about which configurations, which constructs, which limits.
- Use LaTeX dashes (`--`, `---`), never pasted Unicode dashes. Cite the latest version of each work (e.g., the journal version of a conference paper when it supersedes it, or the newest arXiv version) and prefer recent citations.
