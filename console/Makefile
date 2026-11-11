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
# The download is skipped when this Playwright's browser is already there. A CI runner also
# lacks the system libraries the browser links.
e2e:
	npx playwright install $(if $(CI),--with-deps) chromium
	npm run e2e
lint:
	npm run lint
fix:
	npm run fix
