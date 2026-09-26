#!/usr/bin/env bash
set -euo pipefail

bucket="${1:?uso: scripts/deploy-s3.sh NOME_DO_BUCKET [REGIAO]}"
region="${2:-us-west-2}"

npm run build
aws s3 sync build/client "s3://${bucket}" --delete --region "${region}" \
  --exclude "index.html" --cache-control "public,max-age=31536000,immutable"
aws s3 cp build/client/index.html "s3://${bucket}/index.html" --region "${region}" \
  --content-type "text/html; charset=utf-8" --cache-control "no-cache"

# O website S3 não reescreve rotas SPA para index.html. Publicar o shell em
# cada rota conhecida mantém acesso direto e refresh funcionando.
for route in exposicao manutencao bateria relatorio configuracoes; do
  aws s3 cp build/client/index.html "s3://${bucket}/${route}" --region "${region}" \
    --content-type "text/html; charset=utf-8" --cache-control "no-cache" --only-show-errors
done
