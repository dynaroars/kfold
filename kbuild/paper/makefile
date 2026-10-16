BIBFILTER = grep -v -E "^Warning--(empty (publisher|address)|page numbers missing|no number and no volume)" || true

paper:
	pdflatex paper
bib:
	bibtex paper | $(BIBFILTER)
all:
	pdflatex paper
	-bibtex paper | $(BIBFILTER)
	pdflatex paper
	pdflatex paper
clean:
	rm -f *.aux *.bbl *.blg *.log *.out *.toc *.lof *.lot *.acn *.bcf *.glo *.ist *.nav *.run.xml *.snm *.pdf texput.log *.fls *.fdb_latexmk
view:
	okular paper.pdf
