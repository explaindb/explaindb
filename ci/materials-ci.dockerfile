# Use Python 3.12 as base image
FROM python:3.12.6

# Install graphviz on OS for dot executables in CI
RUN apt-get update && apt-get install graphviz -y

# Create and activate venv
ENV VIRTUAL_ENV /venv
WORKDIR $VIRTUAL_ENV
RUN python -m venv $VIRTUAL_ENV
ENV PATH "$VIRTUAL_ENV/bin:$PATH"

# Install pipenv and black for jupyter. Note that we install a specific, old version of pipenv, since we encoutered
# weird issues caused by installing graphviz and pydantic when using the most recent version of pipenv
RUN pip install pipenv==2023.12.1 black[jupyter]
