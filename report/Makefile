# Builds report.pdf from report.md with pandoc and XeLaTeX.
# Usage: make -C report

report.pdf: report.md pandoc/metadata.yaml pandoc/title.tex pandoc/html-figures.lua $(wildcard figures/*.png)
	pandoc report.md \
		--from markdown \
		--metadata-file=pandoc/metadata.yaml \
		--include-before-body=pandoc/title.tex \
		--lua-filter=pandoc/html-figures.lua \
		--shift-heading-level-by=-1 \
		--pdf-engine=xelatex \
		--resource-path=. \
		-o $@

.PHONY: clean
clean:
	rm -f report.pdf
