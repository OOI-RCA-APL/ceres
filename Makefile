.PHONY: *
build: install
	cd console && make build
	poetry build
install:
	poetry install
	cd console && make install
update:
	poetry update
	cd console && make update
test:
	poetry run pytest -vv
lint:
	poetry run sh -c "ruff check . && ruff format --check . && pyright ."
	cd console && make lint
fix:
	poetry run sh -c "ruff check --fix . && ruff format ."
	cd console && make fix
build-docs: install-docs
	poetry run mkdocs build
deploy-docs: install-docs
	poetry run mkdocs gh-deploy --force
install-docs:
	poetry install --only docs
clean:
	rm -rf ./*/**/__pycache__
	rm -rf ./*/**/.mypy_cache
	rm -rf ./*/**/.pytest_cache
	rm -rf ./ceres/static
	rm -rf ./dist
	rm -rf ./site
	cd console && make clean
