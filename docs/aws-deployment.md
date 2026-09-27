# Ambiente AWS reproduzível do CurtaiLess

Este documento permite que outro desenvolvedor provisione, publique e valide o ambiente `dev` sem receber credenciais de outra pessoa. O backend, o pipeline de ingestão e o website S3 são declarados em `template.yaml`. O conteúdo compilado do frontend é publicado separadamente por um script versionado.

## Escopo e limitações

- Conta usada no hackathon: `290278850174`.
- Região oficial: `us-west-2`.
- Stack oficial: `curtailess-dev`.
- O deploy é manual. O GitHub Actions atual executa apenas CI em pull requests.
- As credenciais do workshop são temporárias e nunca devem ser gravadas no Git, no `samconfig.toml` ou na documentação.
- O website usa o endpoint HTTP público do S3. CloudFront e Amplify não fazem parte desta implantação por limitações IAM do workshop.
- Os dados públicos materializados atualmente são históricos do ONS, não previsões.

## Recursos gerenciados pelo SAM

O `template.yaml` provisiona:

- API Gateway HTTP API;
- Lambdas da API, descoberta, cópia e materialização ONS;
- filas SQS e DLQ;
- tabelas DynamoDB;
- bucket privado de dados e artefatos;
- bucket público do frontend com website S3;
- política pública somente para `s3:GetObject` no frontend;
- log groups e agendamento EventBridge;
- outputs para API, bucket e URL do frontend, filas, tabelas e Lambdas.

Os buckets e tabelas relevantes usam retenção para reduzir o risco de perda em remoções ou substituições da stack.

## Pré-requisitos

- AWS CLI;
- AWS SAM CLI;
- Docker disponível para builds que necessitem de contêiner;
- Python 3.12 e `uv`;
- Node.js e npm.

Verifique as ferramentas:

```bash
aws --version
sam --version
uv --version
node --version
npm --version
```

## 1. Autenticação

Cada desenvolvedor deve obter suas próprias credenciais temporárias do workshop e configurar um profile local. Este exemplo usa `hackathon`, mas o nome não é obrigatório:

```bash
export AWS_PROFILE=hackathon
export AWS_REGION=us-west-2
export AWS_DEFAULT_REGION=us-west-2
aws sts get-caller-identity
```

Antes de alterar qualquer recurso, confirme que `Account` é `290278850174`. Se a chamada falhar com token expirado, renove as credenciais pelo procedimento oficial do workshop.

## 2. Instalação e validação local

Na raiz do repositório:

```bash
cd backend
uv sync --dev --locked
uv run pytest
uv run ruff check .
uv run ruff format --check .
cd ..

sam validate
sam build

cd frontend
npm ci
npm run typecheck
npm run lint
npm test -- --run
npm run build
cd ..
```

O `samconfig.toml` centraliza região, stack, capabilities e parâmetros não secretos. O profile AWS permanece local e é lido de `AWS_PROFILE`.

## 3. Provisionamento ou atualização

Na raiz:

```bash
export AWS_PROFILE=hackathon
sam validate
sam build
sam deploy
```

O primeiro deploy cria um novo bucket de frontend gerenciado pela stack. O bucket antigo criado manualmente não é adotado automaticamente pelo CloudFormation e deve permanecer intacto até a validação do novo website.

Acompanhe o estado:

```bash
aws cloudformation describe-stacks \
  --stack-name curtailess-dev \
  --region us-west-2 \
  --query 'Stacks[0].StackStatus' \
  --output text
```

O resultado esperado é `CREATE_COMPLETE` ou `UPDATE_COMPLETE`.

## 4. Publicação do frontend

Depois que a stack estiver concluída:

```bash
cd frontend
AWS_PROFILE=hackathon ./scripts/deploy-s3.sh curtailess-dev us-west-2
cd ..
```

O script consulta os outputs `FrontendBucketName`, `FrontendWebsiteUrl` e `ApiUrl`, injeta a API em `VITE_API_BASE_URL`, compila a SPA e sincroniza `build/client` com o bucket. Também publica o shell da SPA nas rotas conhecidas para permitir acesso direto no website S3.

Consulte os outputs manualmente se necessário:

```bash
aws cloudformation describe-stacks \
  --stack-name curtailess-dev \
  --region us-west-2 \
  --query 'Stacks[0].Outputs' \
  --output table
```

## 5. Materialização dos dados ONS

O agendamento de descoberta é criado pela stack. Para uma execução manual controlada, obtenha o nome da Lambda no output `IngestionDiscoveryFunctionName` e invoque-a:

```bash
FUNCTION_NAME=$(aws cloudformation describe-stacks \
  --stack-name curtailess-dev \
  --region us-west-2 \
  --query "Stacks[0].Outputs[?OutputKey=='IngestionDiscoveryFunctionName'].OutputValue | [0]" \
  --output text)

aws lambda invoke \
  --function-name "$FUNCTION_NAME" \
  --region us-west-2 \
  --cli-binary-format raw-in-base64-out \
  --payload '{}' \
  /tmp/curtailess-ingestion-response.json
```

A ingestão é assíncrona: a descoberta envia mensagens à SQS, que aciona cópia e materialização. Verifique filas, DLQ e logs antes de considerar a execução concluída. A fonte configurada é o bucket público `ons-aws-prod-opendata`, dataset eólico `restricao_coff_eolica_tm`.

## 6. Smoke tests

Obtenha as URLs:

```bash
API_URL=$(aws cloudformation describe-stacks \
  --stack-name curtailess-dev \
  --region us-west-2 \
  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue | [0]" \
  --output text)

FRONTEND_URL=$(aws cloudformation describe-stacks \
  --stack-name curtailess-dev \
  --region us-west-2 \
  --query "Stacks[0].Outputs[?OutputKey=='FrontendWebsiteUrl'].OutputValue | [0]" \
  --output text)

curl --fail --silent --show-error "$API_URL/health"
curl --fail --silent --show-error "$API_URL/openapi.json" >/dev/null
curl --fail --silent --show-error "$API_URL/v1/assets" >/dev/null
curl --fail --silent --show-error "$FRONTEND_URL" >/dev/null
curl --fail --silent --show-error "$FRONTEND_URL/exposicao" >/dev/null
```

Confirme também no navegador que as telas carregam dados da API. As respostas históricas devem continuar identificadas como `ons_materialized` ou equivalente; não as descreva como previsão.

## 7. Rollback

Se o CloudFormation falhar, examine eventos e logs antes de repetir:

```bash
aws cloudformation describe-stack-events \
  --stack-name curtailess-dev \
  --region us-west-2 \
  --max-items 30
```

Para restaurar uma versão anterior:

1. faça checkout do commit estável;
2. execute `sam build && sam deploy`;
3. republique o frontend com `frontend/scripts/deploy-s3.sh`;
4. repita os smoke tests.

Não use `aws cloudformation delete-stack` como rollback rotineiro. Buckets e tabelas retidos podem exigir tratamento manual e contêm dados que não devem ser apagados inadvertidamente.

## 8. Migração do bucket frontend antigo

A stack passa a criar um novo bucket com nome gerado pelo CloudFormation. Procedimento seguro:

1. implantar a stack;
2. publicar no novo bucket;
3. validar API, CORS, páginas e rotas diretas;
4. compartilhar a nova URL com a equipe;
5. manter o bucket antigo durante uma janela de transição;
6. remover o bucket antigo somente após autorização explícita e backup, se necessário.

## Segurança

Nunca versione:

- `AWS_ACCESS_KEY_ID`;
- `AWS_SECRET_ACCESS_KEY`;
- `AWS_SESSION_TOKEN`;
- arquivos `.env` com segredos;
- cookies, tokens ou exportações de sessão.

`samconfig.toml` contém somente configuração operacional não secreta. O deploy depende das credenciais temporárias presentes no profile local do desenvolvedor.
