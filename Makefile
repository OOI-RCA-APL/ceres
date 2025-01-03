.PHONY: *
build: install
	cd console && make build
	uv build
install:
	uv sync
	cd console && make install
update:
	uv update
	cd console && make update
test:
	uv run pytest -vv
lint:
	uv run sh -c "ruff check . && ruff format --check . && pyright ."
	cd console && make lint
fix:
	uv run sh -c "ruff check --fix . && ruff format ."
	cd console && make fix
build-docs: install-docs
	uv run mkdocs build
deploy-docs: install-docs
	uv run mkdocs gh-deploy --force
install-docs:
	uv sync --only-group docs
