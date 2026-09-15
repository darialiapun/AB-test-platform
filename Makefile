.PHONY: install test run

install:
	python3 -m pip install -r requirements.txt

test:
	python3 -m pytest

run:
	python3 -m uvicorn app.main:app --reload
