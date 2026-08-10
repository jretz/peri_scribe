.PHONY: feed-config
feed-config: .venv
	@mise exec -- uv run --locked src/peri_scribe/main.py feed-config

.PHONY: fetch
fetch: .venv
	@mise exec -- uv run --locked src/peri_scribe/main.py --log-level debug fetch

.PHONY: test
test: .venv
	@.venv/bin/py.test --no-header

.PHONY: upgrade-tools
upgrade-tools:
	@mise upgrade --local --minimum-release-age 3d

.PHONY: install-tools
install-tools:
	@mise install

mise.lock: mise.toml install-tools
	@mise lock

lint: .venv
	@mise exec -- uv run ruff check --fix

typecheck: .venv
	@mise exec -- uv run ty check

.venv: mise.toml pyproject.toml uv.lock
	@make install-tools
	@mise exec -- uv sync && touch $@

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
	echo "*.gpkg" >> $@
