.PHONY: *

# Unoptimized by default, as cargo itself is. Distributed wheels build release through
# maturin in `release.yaml`, never through this file, so nothing here needs to.
PROFILE ?= dev
CARGO_PROFILE = $(if $(filter dev,$(PROFILE)),,--release)
WORDS = cameras?|camctrl|nereus

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
# The bundle is a build artifact rather than a committed file, so a fresh clone has none
# until something builds one. An order-only prerequisite, so a bundle already there is left
# alone and only its absence costs a build.
ceres/static/console:
	cd console && npm install && npm run build
update:
	uv update
	cd console && make update
# One target per suite, so `make -j test` runs them side by side.
test: test-python test-rust test-console test-e2e
# Distributed across cores, which needs the capture that `-s` in the pytest options turns
# off. A bare `pytest` still runs serially, where `-s` is what makes a single test readable.
test-python:
	uv run pytest -n auto --capture=fd
test-rust:
	cd rust && cargo test && cargo test -p ceres-core
test-console:
	cd console && make test
# Drives the bundle in `ceres/static/console` through the installed `ceres`, so a console
# change needs `make console` first.
test-e2e:
	cd console && make e2e
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
models:
	cd rust && cargo models
models-check:
	cd rust && cargo models
	git diff --exit-code -- ceres/__internal__/models
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
# One target per language, so `make -j lint` checks them side by side.
lint: words-check lint-python lint-console lint-rust
lint-python:
	uv run sh -c "ruff check . && ruff format --check . && pyright"
lint-console:
	cd console && make lint
# Unlike a workspace build, a workspace check includes `ceres-core` without the output
# filename collision `default-members` avoids, so one pass covers every crate.
lint-rust:
	cd rust && cargo fmt --check && cargo clippy --workspace --all-targets -- -D warnings
# Ceres names no project built on it or that project's domain, in code, text, or docs.
# Released changelog entries stay as published, so only the unreleased section is read.
words-check:
# A search exits 1 when it finds nothing, so any other status fails, an error included.
	git grep --untracked -n -I -i -w -E '$(WORDS)' -- . ':!COVERAGE.md' ':!CHANGELOG.md' \
		':!Makefile'; test $$? -eq 1
	sed -n '/^## \[Unreleased\]/,/^## \[[0-9]/p' CHANGELOG.md | grep -n -i -w -E '$(WORDS)'; \
		test $$? -eq 1
fix:
# Regenerated before the formatters run, the generator's output not being formatted to the
# rules `make lint` then holds it to.
	cd rust && cargo stubs
	uv run sh -c "ruff check --fix . && ruff format ."
	cd console && make fix
	cd rust && cargo fmt && cargo clippy --fix --allow-dirty --allow-staged --workspace --all-targets
build-docs: install-docs
	uv run mkdocs build
install-docs:
	uv sync --only-group docs
