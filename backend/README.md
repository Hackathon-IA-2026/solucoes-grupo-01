# CurtaiLess API

Backend da POC em Python 3.12 e FastAPI. A mesma aplicacao roda localmente com
Uvicorn e na AWS Lambda por meio do adaptador Mangum.

## Desenvolvimento local

```bash
cd backend
uv sync --dev
uv run uvicorn curtailess.main:app --app-dir src --reload
```

A API fica disponivel em `http://localhost:8000` e a documentacao OpenAPI em
`http://localhost:8000/docs`.

## Testes e qualidade

```bash
cd backend
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

## Variaveis de ambiente

Copie os nomes de `.env.example` para um arquivo `.env` local. O arquivo `.env`
nao deve ser versionado. Na AWS, os valores sao definidos pelo template SAM.

## Container Lambda

```bash
docker build -t curtailess-api ./backend
```

O handler da imagem e `curtailess.main.handler`.
