VENDOR := vendor/gearhead-1
BIN    := $(VENDOR)/gharena

.PHONY: all bootstrap engine run headless clean venv test test-only test-api test-perf playtest

all: bootstrap engine venv

# Clone GH1. ~15 MB one-time pull, shallow.
bootstrap: $(VENDOR)/.git
$(VENDOR)/.git:
	@echo "==> fetching gearhead-1 into vendor/ (~15 MB, one time)"
	@mkdir -p vendor
	git clone --depth=1 https://github.com/jwvhewitt/gearhead-1.git $(VENDOR)

# Build console-mode GH1 with FPC. No -dSDLMODE → console path.
# fpc writes the binary next to the source (gharena.pas → gharena).
engine: $(BIN)
$(BIN): $(VENDOR)/.git
	@echo "==> compiling gharena (console mode)"
	cd $(VENDOR) && fpc -viwne gharena.pas
	@test -x $(BIN) || { echo "build failed"; exit 1; }
	@echo "==> built $(BIN) ($$(stat -c%s $(BIN)) bytes)"

venv: .venv/bin/python
.venv/bin/python:
	python3 -m venv .venv
	.venv/bin/pip install -e .

run: venv $(BIN)
	.venv/bin/python gearhead.py

headless: venv $(BIN)
	.venv/bin/python gearhead.py --headless --agent 8770

# Full QA suite — TUI + API + perf.
test: venv $(BIN)
	.venv/bin/python -m tests.qa
	.venv/bin/python -m tests.api_qa
	.venv/bin/python -m tests.perf

# Subset of scenarios by pattern.
test-only: venv $(BIN)
	.venv/bin/python -m tests.qa $(PAT)

test-api: venv $(BIN)
	.venv/bin/python -m tests.api_qa

test-perf: venv $(BIN)
	.venv/bin/python -m tests.perf

# Real-binary playtest via pexpect — spawn, navigate menu, quit.
playtest: venv $(BIN)
	.venv/bin/python -m tests.playtest

clean:
	rm -f $(VENDOR)/*.o $(VENDOR)/*.ppu $(BIN) 2>/dev/null || true
