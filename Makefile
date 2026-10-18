.PHONY: install build test lint configure companion status doctor

install:
	cd companion && uv sync
	cd extension && npm install

build:
	cd extension && npm run build

test:
	cd companion && uv run pytest -q
	cd extension && npm test

lint:
	cd companion && uv run ruff check src tests
	cd companion && uv run ruff format --check src tests
	cd extension && npm run typecheck

configure:
	cd companion && uv run snatcher configure

companion:
	cd companion && uv run snatcher serve

status:
	cd companion && uv run snatcher status

doctor:
	@command -v node
	@node --version
	@command -v uv
	@uv --version
	@command -v ffmpeg
	@ffmpeg -version | head -n 1
	@command -v ffprobe

