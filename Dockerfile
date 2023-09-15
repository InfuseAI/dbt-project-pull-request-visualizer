# Define custom function directory
ARG FUNCTION_DIR="/function"

FROM python:3.10-slim

# Include global arg in this stage of the build
ARG FUNCTION_DIR
# Set working directory to function root directory
WORKDIR ${FUNCTION_DIR}

RUN apt-get update && apt-get install -y git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir awslambdaric boto3

# Copy in the built dependencies
RUN mkdir -p ${FUNCTION_DIR}
COPY requirements.txt ${FUNCTION_DIR}
COPY setup.py ${FUNCTION_DIR}
COPY lambda ${FUNCTION_DIR}/lambda
COPY core ${FUNCTION_DIR}/core
COPY README.md ${FUNCTION_DIR}
COPY LICENSE ${FUNCTION_DIR}
COPY hack ${FUNCTION_DIR}/hack

RUN pip install --no-cache-dir -e .

RUN bash ${FUNCTION_DIR}/hack/patch.sh

# Set runtime interface client as default command for the container runtime
ENTRYPOINT [ "/usr/local/bin/python", "-m", "awslambdaric" ]
# Pass the name of the function handler as an argument to the runtime
CMD [ "lambda.app.receiver" ]
