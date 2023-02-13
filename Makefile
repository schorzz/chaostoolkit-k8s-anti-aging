.PHONY: install
install:
	pip install --upgrade pip setuptools wheel
	pip install -r requirements.txt

.PHONY: install-dev
install-dev: install
	pip install -r requirements-test.txt
	python3 setup.py develop

.PHONY: build
build:
	python3 setup.py build

.PHONY: lint
lint:
	flake8 antiaging/ tests/
	isort --check-only --profile black antiaging/ tests/
	black --check --diff --line-length=120 antiaging/ tests/

.PHONY: format
format:
	isort --profile black antiaging/ tests/
	black --line-length=120 antiaging/ tests/

.PHONY: tests
tests:
	pytest

.PHONY: clean
clean:
	rm -rf build dist
	find . -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -delete
