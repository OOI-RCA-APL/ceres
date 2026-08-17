.PHONY: *
build: install
	npm run build
dev:
	npm run dev
# The lock file is authoritative wherever the built bundle is compared against the
# committed one, and `npm ci` discards `node_modules` first, which is too slow to want
# locally.
install:
	$(if $(CI),npm ci,npm install)
update:
	npm update
test:
	npm run test
lint:
	npm run lint
fix:
	npm run fix
