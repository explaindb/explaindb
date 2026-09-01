# Use Python 3.12 as base image
FROM python:3.12.6

# Install graphviz on OS for dot executables in CI
RUN apt-get update && apt-get install graphviz -y

# Install uv, the project's package manager. uv creates and manages the
# project virtual environment (.venv) itself from pyproject.toml / uv.lock,
# so no manual venv or pipenv setup is required here.
RUN pip install uv==0.11.25
