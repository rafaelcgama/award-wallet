# Shortcuts for working on Award Wallet. Run `make` to list them.
.DEFAULT_GOAL := help
.PHONY: help setup test lint format check app dmg clean

help: ## List the commands
	@grep -E "^[a-z]+:.*## " $(MAKEFILE_LIST) | awk -F ":.*## " '{printf "  make %-8s %s\n", $$1, $$2}'

setup: ## Install everything, including the Mac app extras
	uv sync --extra desktop

test: ## Run the tests
	uv run pytest

lint: ## Look for mistakes and style problems
	uv run ruff check .
	uv run ruff format --check .

format: ## Fix formatting and import order
	uv run ruff check --fix .
	uv run ruff format .

check: lint test ## Everything CI runs

app: ## Run the app from this branch's code, without installing it
	uv run --extra desktop python -m award_wallet.desktop

dmg: ## Build build/Award Wallet.dmg
	bash build_dmg.sh

clean: ## Remove build output and caches (never your data)
	rm -rf build .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
