# CurtaiLess

O CurtaiLess é uma plataforma B2B que ajuda usinas eólicas e solares a reduzir perdas por curtailment. O produto combina dados públicos do ONS, cenários demonstrativos e análises assistidas por IA para identificar a exposição de cada usina, sugerir janelas de manutenção e avaliar o uso de baterias.

Ao deslocar manutenções para períodos com maior risco de corte, a usina pode preservar mais dias produtivos e aumentar a energia disponível para comercialização.

## Demonstração

- [Acessar o CurtaiLess](http://curtailess-dev-frontendbucket-vohqs0b1wbic.s3-website-us-west-2.amazonaws.com)

## Funcionalidades

- análise histórica de curtailment e qualidade dos dados por usina;
- cenário demonstrativo de exposição para os próximos 60 dias;
- ranking e agendamento demonstrativo de janelas de manutenção;
- estimativa técnica e econômica de sistemas de armazenamento por bateria;
- explicações geradas com Amazon Bedrock a partir de métricas calculadas pelo backend.

## Tecnologias

O frontend usa React, React Router e TypeScript. O backend usa Python 3.12, FastAPI e DuckDB. A infraestrutura serverless é definida com AWS SAM e inclui Lambda, API Gateway, S3, SQS, DynamoDB, EventBridge e Amazon Bedrock.

## Execução local

Pré-requisitos: Python 3.12, `uv`, Node.js 22 e npm.

```bash
# Backend
cd backend
uv sync --dev --locked
uv run uvicorn curtailess.main:app --app-dir src --reload

# Frontend, em outro terminal
cd frontend
npm ci
npm run dev
```

As instruções de implantação estão em [`docs/aws-deployment.md`](./docs/aws-deployment.md). Pull requests executam testes, análise estática e builds do backend, frontend e template AWS SAM. O deploy permanece manual.

## Limitações da demonstração

Os dados históricos vêm do ONS. As previsões, sugestões de manutenção e estimativas de bateria são demonstrativas e não usam telemetria privada em tempo real. O CurtaiLess não substitui a aprovação operacional do ONS.

## Licença

Este projeto está sob a licença MIT. Consulte o arquivo [LICENSE](./LICENSE).
