.PHONY: install test test-perf run

install:
	python3 -m pip install -r requirements.txt

test:
	python3 -m pytest -m "not perf"

test-perf:
	python3 -m pytest -m perf -v

run:
	python3 -m uvicorn app.main:app --reload
