# make verify / make doctor - see docs/REPRODUCE.md for full setup.
# Auto-detects a Windows-layout venv (.venv/Scripts/python.exe) vs. a
# Unix-layout one (.venv/bin/python) rather than assuming one - this repo
# was built on Windows, but nothing here should require it.

ifneq ($(wildcard .venv/Scripts/python.exe),)
PYTHON := .venv/Scripts/python.exe
else
PYTHON := .venv/bin/python
endif

.PHONY: verify doctor freeze-verify-golden

doctor:
	$(PYTHON) -m rtlverdict.doctor

verify: doctor
	$(PYTHON) scripts/verify.py

# Regenerates benchmarks/verify_golden.json from a live run. Only run this
# after a deliberate, understood change to the ladder/corpus - never to
# make a failing `make verify` go away silently.
freeze-verify-golden:
	$(PYTHON) scripts/verify.py --freeze
