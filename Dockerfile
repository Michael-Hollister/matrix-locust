# Build layer to clone the repository and install dependencies
FROM python:3.11-alpine as builder

# Install git, gcc, and other build tools
RUN apk add --no-cache curl git gcc libffi-dev musl-dev openssl-dev poetry python3-dev make

# Set the working directory
WORKDIR /usr/src/app

# Clone the repository into the working directory
RUN git clone https://github.com/Michael-Hollister/matrix-locust.git .

# circles setup
RUN git checkout circles_registration
RUN git submodule init
RUN git submodule update
# RUN poetry install --with circles


# Fix externally-managed-envrionment errors: https://stackoverflow.com/a/76641565
# RUN rm /usr/lib/python3.11/EXTERNALLY-MANAGED

# Install the dependencies using Poetry without creating a virtual environment
# RUN poetry config virtualenvs.in-project true && \
#     poetry install --with circles --no-ansi --no-root

# RUN poetry config virtualenvs.create false && \
#     poetry install --only main --no-root --with circles

RUN pip install locust=="2.17.0"
RUN pip install matrix-nio=="0.21.2"
RUN pip install cffi=="1.16.0"

# circles setup
WORKDIR /usr/src/app/matrix_locust/bsspeke
# RUN cd matrix_locust/bsspeke
# RUN echo $(pwd)

RUN make
# RUN cd python
WORKDIR /usr/src/app/matrix_locust/bsspeke/python
RUN python ./bsspeke_build.py
# RUN poetry run python ./bsspeke_build.py
# RUN cd ../../../

# Main image
# FROM python:3.11-alpine

# Set the working directory
WORKDIR /usr/src/app

# Copy the cloned repository from the builder layer
# COPY --from=builder /usr/src/app .

# Copy the installed Python packages from the builder layer
# COPY --from=builder /usr/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages/
# COPY --from=builder /usr/bin /usr/bin

# Update the PATH environment variable to include the cloned repository directory
ENV PATH="/usr/src/app:${PATH}"

# Expose web UI running from container
EXPOSE 8089

# No entrypoint, this line is kept to keep the container running to launch commands
CMD ["tail", "-f", "/dev/null"]
