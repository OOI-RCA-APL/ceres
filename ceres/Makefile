build: install
	poetry build
install:
	poetry install --extras all
update:
	poetry update
lint:
	poetry run sh -c "isort . --check --diff && black --check . && pyright"
test:
	poetry run pytest
format:
	poetry run sh -c "isort . && black ."
clean:
	rm -rf ./*/**/__pycache__
	rm -rf ./*/**/.mypy_cache
	rm -rf ./*/**/.pytest_cache
	rm -rf ./dist
