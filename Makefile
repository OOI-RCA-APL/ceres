build:
	cd ./ceres && make build
install:
	cd ./ceres && make install
	cd ./ceres-console && make install
update:
	cd ./ceres && make update
	cd ./ceres-console && make update
lint:
	cd ./ceres && make lint
	cd ./ceres-console && make lint
format:
	cd ./ceres && make format
	cd ./ceres-console && make format
test:
	cd ./ceres && make test
