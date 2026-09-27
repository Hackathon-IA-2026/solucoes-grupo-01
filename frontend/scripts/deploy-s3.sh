#!/usr/bin/env bash
set -euo pipefail

stack="${1:-curtailess-dev}"
region="${2:-us-west-2}"
profile="${AWS_PROFILE:-}"
aws_args=(--region "${region}")
if [[ -n "${profile}" ]]; then
  aws_args+=(--profile "${profile}")
fi

stack_output() {
  local key="$1"
  aws cloudformation describe-stacks \
    --stack-name "${stack}" \
    "${aws_args[@]}" \
    --query "Stacks[0].Outputs[?OutputKey=='${key}'].OutputValue | [0]" \
    --output text
}

bucket="$(stack_output FrontendBucketName)"
api_url="$(stack_output ApiUrl)"
website_url="$(stack_output FrontendWebsiteUrl)"

if [[ -z "${bucket}" || "${bucket}" == "None" ]]; then
  echo "A stack ${stack} não expõe FrontendBucketName." >&2
  exit 1
fi
if [[ -z "${api_url}" || "${api_url}" == "None" ]]; then
  echo "A stack ${stack} não expõe ApiUrl." >&2
  exit 1
fi

VITE_API_BASE_URL="${api_url}" npm run build
aws s3 sync build/client "s3://${bucket}" --delete "${aws_args[@]}" \
  --exclude "index.html" --cache-control "public,max-age=31536000,immutable"
aws s3 cp build/client/index.html "s3://${bucket}/index.html" "${aws_args[@]}" \
  --content-type "text/html; charset=utf-8" --cache-control "no-cache"

# O website S3 não reescreve rotas SPA para index.html. Publicar o shell em
# cada rota conhecida mantém acesso direto e refresh funcionando.
for route in exposicao manutencao bateria relatorio configuracoes; do
  aws s3 cp build/client/index.html "s3://${bucket}/${route}" "${aws_args[@]}" \
    --content-type "text/html; charset=utf-8" --cache-control "no-cache" --only-show-errors
done

echo "Frontend publicado em ${website_url}"
