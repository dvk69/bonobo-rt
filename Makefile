PACKAGE ?= bonobo
PYTHON ?= $(shell which python || echo python)
PYTHON_DIRNAME ?= $(shell dirname $(PYTHON))
PIP ?= $(PYTHON) -m pip
PIP_INSTALL_OPTIONS ?=
PYTEST ?= $(PYTHON_DIRNAME)/pytest
PYTEST_OPTIONS ?= --capture=no --cov=$(PACKAGE) --cov-report html

.PHONY: clean install-dev test format help

install-dev:   ## Installs the project with dev dependencies.
	$(PIP) install $(PIP_INSTALL_OPTIONS) -e ".[dev]"

test: install-dev   ## Runs the test suite.
	$(PYTEST) $(PYTEST_OPTIONS) tests

clean:   ## Cleans up the working copy.
	rm -rf build dist *.egg-info
	find . -name __pycache__ -type d | xargs rm -rf

format:   ## Reformats the whole codebase using our standards (requires black and isort).
	black -l 120 .
	isort -rc -o mondrian -o whistle .

help:   ## Shows available commands.
	@echo "Available commands:"
	@echo
	@grep -E '^[a-zA-Z_-]+:.*?##[\s]?.*$$' --no-filename $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?##"}; {printf "    make \033[36m%-30s\033[0m %s\n", $$1, $$2}'
	@echo
