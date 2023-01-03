build: install
	cd ../ceres-console && make build
	poetry build
install:
	poetry install --extras all
update:
	poetry update
test:
	poetry run pytest
lint:
	poetry run sh -c "isort . --check --diff && black --check . && pyright"
format:
	poetry run sh -c "isort . && black ."
clean:
	rm -rf ./*/**/__pycache__
	rm -rf ./*/**/.mypy_cache
	rm -rf ./*/**/.pytest_cache
	rm -rf ./dist
	rm -rf ./ceres/static
