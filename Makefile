.PHONY: run test eval docker-build docker-up

run:
	PYTHONPYCACHEPREFIX=/tmp/signalwatch-pycache python3 app.py

test:
	PYTHONPYCACHEPREFIX=/tmp/signalwatch-pycache python3 -m unittest discover -s tests -v

eval:
	PYTHONPYCACHEPREFIX=/tmp/signalwatch-pycache python3 scripts/evaluate.py

eval-ai:
	PYTHONPYCACHEPREFIX=/tmp/signalwatch-pycache python3 scripts/evaluate.py --use-ai --output-dir outputs/ai-evaluation

eval-holdout:
	PYTHONPYCACHEPREFIX=/tmp/signalwatch-pycache python3 scripts/evaluate.py --dataset eval/holdout.jsonl --output-dir outputs/holdout-rules

docker-build:
	docker compose build

docker-up:
	docker compose up -d
