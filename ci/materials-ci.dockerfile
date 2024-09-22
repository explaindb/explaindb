# Use Python 3.12 as base image
FROM python:3.12.6

# Create and activate venv
ENV VIRTUAL_ENV /venv
WORKDIR $VIRTUAL_ENV
RUN python -m venv $VIRTUAL_ENV
ENV PATH "$VIRTUAL_ENV/bin:$PATH"

# Install pipenv
RUN pip install pipenv black[jupyter]
