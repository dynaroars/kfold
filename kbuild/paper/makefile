BIBFILTER = grep -v -E "^Warning--(empty (publisher|address)|page numbers missing|no number and no volume)" || true

LATEX = pdflatex -interaction=nonstopmode -halt-on-error

paper:
	$(LATEX) paper
bib:
	bibtex paper | $(BIBFILTER)
all:
	$(LATEX) paper
	-bibtex paper | $(BIBFILTER)
	$(LATEX) paper
	$(LATEX) paper
clean:
	rm -f *.aux *.bbl *.blg *.log *.out *.toc *.lof *.lot *.acn *.bcf *.glo *.ist *.nav *.run.xml *.snm *.pdf texput.log *.fls *.fdb_latexmk
view:
	okular paper.pdf
