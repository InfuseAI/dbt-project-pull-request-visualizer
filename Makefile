.PHONY: build start-api start stop

build:
	sam build

start: start-api local-sqs-runner

stop:
	@echo "[Stop local stack]"
	@docker stop dynamodb-local
	@docker stop sqs-local
	@docker stop sqs-runner || true

start-api: local-sqs local-dynamodb build
	@echo "[Start api]"
	bash -c "trap '$(MAKE) stop' EXIT; sam local start-api --env-vars lambda/dev_env.json"

local-dynamodb:
	@echo "[Start dynamodb-local]"
	@docker run --rm -d -p 8000:8000 --name dynamodb-local amazon/dynamodb-local

local-sqs:
	@echo "[Start sqs-local]"
	@docker run --rm -d -p 9324:9324 --name sqs-local vsouza/sqs-local

local-sqs-runner:
	@echo "[Start sqs-runner]"
	docker run --rm -d --name sqs-runner -e LOCALHOST=host.docker.internal -e DEBUG=true -v $(HOME)/.aws/credentials:/root/.aws/credentials -v $(PWD)/results:/function/results --entrypoint python analysistaskreceiverfunction:latest -m lambda.dev.sqs_runner

# local-invoke by sam-cli
local-invoke-receiver: build
	sam local invoke --event lambda/events/receiver_api_gateway_event.json AnalysisTaskReceiverFunction

local-invoke-processor: build
	sam local invoke --event lambda/events/processor_sqs_event.json AnalysisTaskProcessorFunction

local-invoke-status-checker: build
	sam local invoke --event lambda/events/receiver_api_gateway_event.json AnalysisTaskStatusCheckerFunction

# Deploy
deploy: build
	sam deploy --no-confirm-changeset
