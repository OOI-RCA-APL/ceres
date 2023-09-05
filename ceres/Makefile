.PHONY: *
build: install
	cd ../ceres-console && make build
	poetry build
install:
	poetry install
update:
	poetry update
test:
	poetry run pytest -vv
lint:
	poetry run sh -c "black --check . && ruff check . && pyright ."
fix:
	poetry run sh -c "black . && ruff check --fix ."
clean:
	rm -rf ./*/**/__pycache__
	rm -rf ./*/**/.mypy_cache
	rm -rf ./*/**/.pytest_cache
	rm -rf ./dist
	rm -rf ./ceres/static
