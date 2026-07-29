.PHONY: *
build: install
	cd console && make build
	cd rust && cargo build --release
	uv build
install:
	uv sync
	cd console && make install
update:
	uv update
	cd console && make update
test:
	uv run pytest -vv -s
	cd rust && cargo test && cargo test -p ceres-core
test-postgres:
	uv run pytest -vv -s --database postgres
test-turso:
	uv run pytest -vv -s --database turso
coverage:
	uv run ./scripts/update-coverage.py
coverage-check:
	uv run ./scripts/update-coverage.py --check
test-all:
	uv run ./scripts/test-all-python-versions.py
lint:
	uv run sh -c "ruff check . && ruff format --check . && pyright"
	cd console && make lint
	cd rust && cargo fmt --check && cargo clippy --all-targets -- -D warnings
	cd rust && cargo clippy -p ceres-core --all-targets -- -D warnings
fix:
	uv run sh -c "ruff check --fix . && ruff format ."
	cd console && make fix
	cd rust && cargo fmt && cargo clippy --fix --allow-dirty --allow-staged --all-targets
	cd rust && cargo stubs
build-docs: install-docs
	uv run mkdocs build
deploy-docs: install-docs
	uv run mkdocs gh-deploy --force
install-docs:
	uv sync --only-group docs
