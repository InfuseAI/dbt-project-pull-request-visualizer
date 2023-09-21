# DBT Project Visualizer

DBT Project Visualizer is designed to make it easy for data teams to visualize their DBT projects.
With this tool, you can understand how different models are interconnected and gain insights into the overall
architecture of your data transformation workflows.

## Getting Started

### Prerequisites

Ensure you have the following installed:

- Python 3.8+
- AWS CLI
- Docker (required for local development)

### Setup

1. Clone the repository
2. Setup virtual environment
    ```shell
    python3 -m venv venv
    source venv/bin/activate
    ```

3. Install the Python packages
    ```shell
    pip install -r requirements.txt
    ```

## Local Development

To start the local development environment, simply run:

```shell
make start
```

This will launch the local environment, allowing you to run and test your Lambda functions as if they were deployed to
AWS.

## Deployment

Create GitHub Release with the tag `vX.X.X` and the release will be automatically deployed to AWS by
our [circleci](https://app.circleci.com/pipelines/github/InfuseAI/dbt-project-pull-request-visualizer) deploy pipeline.
