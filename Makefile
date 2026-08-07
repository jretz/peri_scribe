.PHONY: run
run: .venv
	@uv run --locked src/peri_scribe/main.py

lint: .venv
	@uv run ruff check --fix

typecheck: .venv
	@uv run ty check

.venv: pyproject.toml uv.lock
	@uv sync && touch $@

uv.lock:

.PHONY: .gitignore
.gitignore:
	gitnr create \
		tt:Python \
		tt:linux \
		tt:macOS \
		tt:VisualStudioCode \
	> $@
	echo ".codewhale" >> $@
