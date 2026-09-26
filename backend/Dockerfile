FROM public.ecr.aws/lambda/python:3.12-x86_64

COPY pyproject.toml README.md ${LAMBDA_TASK_ROOT}/
COPY src ${LAMBDA_TASK_ROOT}/src

RUN pip install --no-cache-dir ${LAMBDA_TASK_ROOT}

CMD ["curtailess.main.handler"]
