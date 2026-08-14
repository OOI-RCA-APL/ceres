.PHONY: *

# Unoptimized by default, as cargo itself is. Distributed wheels build release through
# maturin in `release.yaml`, never through this file, so nothing here needs to.
PROFILE ?= dev
CARGO_PROFILE = $(if $(filter dev,$(PROFILE)),,--release)
CARGO_OUTPUT = $(if $(filter dev,$(PROFILE)),debug,release)

# Exported to every recipe, because a bare `uv run` resyncs, and a sync that disagrees
# with the installed build's configuration rebuilds the extension from scratch.
ifeq ($(PROFILE),dev)
export MATURIN_PEP517_ARGS = --profile dev
endif

build: install
	cd console && make build
	cd console-nuxt && make build
	mkdir -p ceres.__internal__.core.data/scripts
	touch ceres.__internal__.core.data/scripts/.keep
# Built one at a time, because a plain `uv build` builds the wheel from the unpacked sdist
# in a temporary directory, sharing no compiled artifacts with the install above.
	uv build --sdist
	uv build --wheel
install:
	uv sync
	cd console && make install
	cd console-nuxt && make install
	cd rust && cargo build $(CARGO_PROFILE) -p ceres-cli
	ln -sf ../../rust/target/$(CARGO_OUTPUT)/ceres .venv/bin/ceres
update:
	uv update
	cd console && make update
	cd console-nuxt && make update
# Distributed across cores, which needs the capture that `-s` in the pytest options turns
# off. A bare `pytest` still runs serially, where `-s` is what makes a single test readable.
test:
	uv run pytest -n auto --capture=fd
	cd rust && cargo test && cargo test -p ceres-core
	cd console && make test
	cd console-nuxt && make test
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
	cd console-nuxt && make lint
	cd rust && cargo fmt --check && cargo clippy --all-targets -- -D warnings
	cd rust && cargo clippy -p ceres-core --all-targets -- -D warnings
fix:
	uv run sh -c "ruff check --fix . && ruff format ."
	cd console && make fix
	cd console-nuxt && make fix
	cd rust && cargo fmt && cargo clippy --fix --allow-dirty --allow-staged --all-targets
	cd rust && cargo stubs
build-docs: install-docs
	uv run mkdocs build
install-docs:
	uv sync --only-group docs
