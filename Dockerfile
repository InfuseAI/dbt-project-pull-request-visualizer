FROM python:3.10-bookworm

ADD README.md README.md
ADD requirements.txt requirements.txt
ADD dbt_project_visualizer.py dbt_project_visualizer.py
ADD setup.py setup.py
ADD LICENSE LICENSE

ADD core core

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

ENTRYPOINT ["dbt-project-visualizer"]

