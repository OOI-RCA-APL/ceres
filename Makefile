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

build: install console
	mkdir -p ceres.__internal__.core.data/scripts
	touch ceres.__internal__.core.data/scripts/.keep
# Built one at a time, because a plain `uv build` builds the wheel from the unpacked sdist
# in a temporary directory, sharing no compiled artifacts with the install above.
	uv build --sdist
	uv build --wheel
install: | ceres/static/console
	uv sync
	cd console && make install
	cd rust && cargo build $(CARGO_PROFILE) -p ceres-cli
	ln -sf ../../rust/target/$(CARGO_OUTPUT)/ceres .venv/bin/ceres
# The bundle is a build artifact rather than a committed file, so a fresh clone has none
# until something builds one. An order-only prerequisite, so a bundle already there is left
# alone and only its absence costs a build.
ceres/static/console:
	cd console && npm install && npm run build
update:
	uv update
	cd console && make update
# Distributed across cores, which needs the capture that `-s` in the pytest options turns
# off. A bare `pytest` still runs serially, where `-s` is what makes a single test readable.
test:
	uv run pytest -n auto --capture=fd
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
# The dependencies come from `install`, which every path here has already run, so this
# builds rather than reinstalling them once per target that wants a bundle.
console:
	cd console && npm run build
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
# Regenerated before the formatters run, the generator's output not being formatted to the
# rules `make lint` then holds it to.
	cd rust && cargo stubs
	uv run sh -c "ruff check --fix . && ruff format ."
	cd console && make fix
	cd rust && cargo fmt && cargo clippy --fix --allow-dirty --allow-staged --all-targets
build-docs: install-docs
	uv run mkdocs build
install-docs:
	uv sync --only-group docs
