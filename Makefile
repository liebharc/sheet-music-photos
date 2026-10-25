.DEFAULT_GOAL := help
COUNT ?= 10
HOMR ?= ../homr

scans:  ## add the next COUNT scans from the Internet Archive
	uv run python -m smp.ia add --count $(COUNT)

references:  ## transcribe scans without a reference with homr from HOMR
	uv run python -m smp.reference --homr $(HOMR)

quality:  ## replace scans whose reference has large-scale errors (then: make scans references)
	uv run python -m smp.quality --drop

reproduce:  ## download every source PDF again and compare each page.pdf
	uv run python -m smp.ia reproduce

printable:  ## recreate every print.pdf from its page.pdf
	uv run python -m smp.printable

check:  ## check scans and contributed photos
	uv run python -m smp.check

help:
	@grep -E '^[a-z]+:.*## ' Makefile | sed 's/:.*## /\t/'

.PHONY: scans references quality reproduce printable check help
