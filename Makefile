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
	poetry run sh -c "black --check . && ruff check . && pyright ."
	cd console && make lint
fix:
	poetry run sh -c "black . && ruff check --fix ."
	cd console && make fix
clean:
	rm -rf ./*/**/__pycache__
	rm -rf ./*/**/.mypy_cache
	rm -rf ./*/**/.pytest_cache
	rm -rf ./dist
	rm -rf ./ceres/static
	cd console && make clean
