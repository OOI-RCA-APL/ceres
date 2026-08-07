.PHONY: *

# CI sets `dev`, since nothing it checks needs an optimized build. Distributed wheels build
# release through maturin in `release.yaml`, never through this file.
PROFILE ?= release
CARGO_PROFILE = $(if $(filter dev,$(PROFILE)),,--release)
CARGO_OUTPUT = $(if $(filter dev,$(PROFILE)),debug,release)
MATURIN = $(if $(filter dev,$(PROFILE)),MATURIN_PEP517_ARGS="--profile dev",)

build: install
	cd console && make build
	mkdir -p ceres.__internal__.core.data/scripts
	touch ceres.__internal__.core.data/scripts/.keep
# Built one at a time, because a plain `uv build` builds the wheel from the unpacked sdist
# in a temporary directory, sharing no compiled artifacts with the install above.
	uv build --sdist
	$(MATURIN) uv build --wheel
install:
	$(MATURIN) uv sync
	cd console && make install
	cd rust && cargo build $(CARGO_PROFILE) -p ceres-cli
	ln -sf ../../rust/target/$(CARGO_OUTPUT)/ceres .venv/bin/ceres
update:
	uv update
	cd console && make update
test:
	uv run pytest -vv -s
	cd rust && cargo test && cargo test -p ceres-core
	cd console && make test
test-postgres:
	uv run pytest -vv -s --database postgres
test-turso:
	uv run pytest -vv -s --database turso
coverage:
	uv run ./scripts/update-coverage.py
coverage-check:
	uv run ./scripts/update-coverage.py --check
schema:
	uv run ./scripts/update-schema.py
schema-check:
	uv run ./scripts/update-schema.py --check
reference:
	cd rust && cargo test -p ceres-cli reference::
	uv run ./scripts/update-reference.py
reference-check:
	cd rust && cargo test -p ceres-cli reference::
	uv run ./scripts/update-reference.py --check
release:
	uv run ./scripts/release.py
release-check:
	uv run ./scripts/release.py --dry-run
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
install-docs:
	uv sync --only-group docs
