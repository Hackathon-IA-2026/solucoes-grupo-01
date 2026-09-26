# AWS CLI, Bedrock Opus 5 e Hermes no Windows

Este guia configura, no Windows PowerShell:

- AWS CLI v2;
- credenciais temporarias do ambiente AWS Workshop do hackathon;
- acesso ao Amazon Bedrock em `us-east-1`;
- Claude Opus 5 pelo perfil de inferencia `us.anthropic.claude-opus-5`;
- Hermes Agent usando o provider nativo do AWS Bedrock.

> Nao existe API key da Anthropic neste fluxo. O Hermes usa as credenciais AWS do
> profile local `hackathon` por meio da cadeia de credenciais do SDK AWS (`boto3`).

## 1. Acessar o ambiente do hackathon

1. Abra o link do AWS Workshop enviado pela organizacao.
2. Entre com o mesmo e-mail informado na inscricao do evento.
3. No painel do evento, use **Get AWS CLI credentials**.
4. Deixe essa pagina aberta. Serao necessarios estes tres valores temporarios:
   - `AWS_ACCESS_KEY_ID`;
   - `AWS_SECRET_ACCESS_KEY`;
   - `AWS_SESSION_TOKEN`.

Para a CLI, nao use a tela comum de login de usuario IAM e nao execute `aws login`.
O ambiente do Workshop fornece uma sessao AWS temporaria propria.

Cada participante deve usar o acesso associado ao seu proprio e-mail. Nao envie
credenciais por chat, e-mail ou commit. Caso o e-mail do desenvolvedor nao tenha
acesso ao evento, solicite a liberacao a organizacao.

## 2. Instalar a AWS CLI v2

Abra o **PowerShell** ou o **Windows Terminal** e execute:

```powershell
irm https://awscli.amazonaws.com/v2/install.ps1 | iex
```

Feche e abra o PowerShell novamente. Verifique a instalacao:

```powershell
aws --version
```

O resultado deve comecar com `aws-cli/2`.

Se a politica do Windows bloquear o instalador, use o MSI para o usuario atual:

```powershell
msiexec.exe /i https://awscli.amazonaws.com/AWSCLIV2-User.msi
```

Depois da instalacao via MSI, abra um novo PowerShell antes de continuar.

## 3. Criar o profile AWS `hackathon`

Copie os tres valores da opcao **Get AWS CLI credentials** no painel do Workshop.
Execute o bloco abaixo. Ele solicita os valores sem grava-los no historico do
PowerShell:

```powershell
$ProfileName = "hackathon"

$AccessKeyId = Read-Host "AWS_ACCESS_KEY_ID"
$SecretAccessKeySecure = Read-Host "AWS_SECRET_ACCESS_KEY" -AsSecureString
$SessionTokenSecure = Read-Host "AWS_SESSION_TOKEN" -AsSecureString

$SecretAccessKey = [System.Net.NetworkCredential]::new("", $SecretAccessKeySecure).Password
$SessionToken = [System.Net.NetworkCredential]::new("", $SessionTokenSecure).Password

aws configure set aws_access_key_id $AccessKeyId --profile $ProfileName
aws configure set aws_secret_access_key $SecretAccessKey --profile $ProfileName
aws configure set aws_session_token $SessionToken --profile $ProfileName
aws configure set region us-east-1 --profile $ProfileName
aws configure set output json --profile $ProfileName

Remove-Variable AccessKeyId, SecretAccessKey, SecretAccessKeySecure, SessionToken, SessionTokenSecure
```

O mecanismo padrao da AWS grava o profile fora do repositorio, em
`$HOME\.aws\credentials`. O arquivo contem credenciais e nao deve ser copiado para
o projeto.

Ative esse profile na sessao atual do PowerShell:

```powershell
$env:AWS_PROFILE = "hackathon"
$env:AWS_REGION = "us-east-1"
$env:AWS_DEFAULT_REGION = "us-east-1"
```

Confirme a identidade AWS:

```powershell
aws sts get-caller-identity --profile hackathon
```

O comando deve retornar `Account`, `Arn` e `UserId`. Nao publique essa saida.

## 4. Testar o Claude Opus 5 no Bedrock

Execute no PowerShell. O caractere de continuacao de linha do PowerShell e a
crase `` ` ``, e nao a barra invertida `\` usada em Bash.

```powershell
aws bedrock-runtime converse `
  --profile hackathon `
  --region us-east-1 `
  --model-id us.anthropic.claude-opus-5 `
  --messages '[{"role":"user","content":[{"text":"Responda somente: CurtaiLess conectado ao Claude Opus 5."}]}]' `
  --inference-config '{"maxTokens":512}' `
  --query 'output.message.content[?text].text | [0]' `
  --output text
```

Nao adicione `temperature` ao teste: esse parametro foi descontinuado para este
modelo no ambiente disponibilizado.

### O que e `us.anthropic.claude-opus-5`

Esse identificador ja e um **perfil de inferencia geografico gerenciado pela AWS**:

- `anthropic.claude-opus-5`: ID base do modelo;
- `us.anthropic.claude-opus-5`: perfil de inferencia cross-region para a geografia
  dos Estados Unidos;
- `global.anthropic.claude-opus-5`: perfil global, quando habilitado pela conta.

Para o hackathon, use o ID com prefixo `us.`. Nao e necessario criar um
Application Inference Profile, endpoint dedicado, API key ou recurso adicional.
O perfil cross-region distribui a inferencia entre regioes AWS compativeis e e o
formato aceito para invocacao on-demand desse modelo.

## 5. Instalar ou atualizar o Hermes Agent

Se `hermes --version` ja funcionar, nao reinstale. Atualize a instalacao para
garantir o suporte ao provider Bedrock e siga para a dependencia:

```powershell
hermes update
hermes --version
```

Para instalar nativamente no Windows:

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

Abra um novo PowerShell e confira:

```powershell
hermes --version
```

O instalador oficial normalmente usa `%LOCALAPPDATA%\hermes` como `HERMES_HOME`.

### Instalar o suporte ao Bedrock no ambiente do Hermes

Execute:

```powershell
$HermesHome = $env:HERMES_HOME
if ([string]::IsNullOrWhiteSpace($HermesHome)) {
  $HermesHome = Join-Path $env:LOCALAPPDATA "hermes"
}

Push-Location (Join-Path $HermesHome "hermes-agent")
python -c "import pm; pm.sync_venv(['bedrock'], explicit=True)"
Pop-Location
```

Esse comando instala no ambiente gerenciado do Hermes as dependencias do provider
Bedrock, incluindo `boto3`.

## 6. Conectar o Hermes ao Opus 5

Em cada novo PowerShell usado para iniciar o Hermes, estas variaveis podem ser
definidas antes do primeiro teste:

```powershell
$env:AWS_PROFILE = "hackathon"
$env:AWS_REGION = "us-east-1"
$env:AWS_DEFAULT_REGION = "us-east-1"
```

Teste diretamente, sem alterar ainda o modelo padrao:

```powershell
hermes chat --provider bedrock --model us.anthropic.claude-opus-5
```

Se o chat abrir e responder, torne o Bedrock o provider padrao:

```powershell
hermes model
```

No seletor do Hermes:

1. Escolha **More providers...**.
2. Escolha **AWS Bedrock**.
3. Escolha a regiao `us-east-1`.
4. Selecione ou informe `us.anthropic.claude-opus-5`.

Depois, valide toda a configuracao:

```powershell
hermes doctor
hermes chat
```

## 7. Configuracao manual do Hermes

Use esta opcao somente se o Opus 5 nao aparecer no seletor interativo. Localize e
abra o `config.yaml`:

```powershell
$HermesHome = $env:HERMES_HOME
if ([string]::IsNullOrWhiteSpace($HermesHome)) {
  $HermesHome = Join-Path $env:LOCALAPPDATA "hermes"
}

notepad (Join-Path $HermesHome "config.yaml")
```

Preserve as demais secoes do arquivo e ajuste apenas os blocos `model` e `bedrock`
para:

```yaml
model:
  provider: bedrock
  default: us.anthropic.claude-opus-5

bedrock:
  region: us-east-1
  profile: hackathon
```

Nao coloque `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` nem `AWS_SESSION_TOKEN` no
arquivo do Hermes. Com `profile: hackathon`, o Hermes le o profile da AWS CLI.

Feche qualquer processo do Hermes que esteja aberto, inicie novamente e execute:

```powershell
hermes doctor
hermes chat
```

## 8. Renovar as credenciais quando expirarem

As credenciais do AWS Workshop sao temporarias. Quando aparecer `ExpiredToken`,
`The security token included in the request is expired` ou erro semelhante:

1. Volte ao painel do evento.
2. Abra **Get AWS CLI credentials** novamente.
3. Obtenha os tres valores novos.
4. Execute novamente todo o bloco da secao **3**.
5. Feche e reabra o Hermes.
6. Teste com:

```powershell
aws sts get-caller-identity --profile hackathon
hermes doctor
```

E obrigatorio substituir os tres valores, inclusive `AWS_SESSION_TOKEN`. O acesso
tambem deixa de funcionar quando o ambiente temporario do evento for encerrado.

## 9. Solucao de problemas

### `aws` ou `hermes` nao e reconhecido

Feche e abra o PowerShell para recarregar o `PATH`. Depois verifique:

```powershell
Get-Command aws
Get-Command hermes
```

### `ExpiredToken`

Renove as credenciais seguindo a secao **8**.

### `No AWS credentials` no Hermes

Confirme o profile e execute o Hermes no mesmo PowerShell:

```powershell
$env:AWS_PROFILE = "hackathon"
$env:AWS_REGION = "us-east-1"
aws sts get-caller-identity
hermes doctor
```

### `No module named boto3`

Repita a instalacao da dependencia da secao **5** e reinicie o Hermes.

### `Invocation ... with on-demand throughput isn't supported`

O ID base foi usado por engano. Use exatamente:

```text
us.anthropic.claude-opus-5
```

### `AccessDeniedException` ou erro de AWS Marketplace

Primeiro confirme que o profile e a conta temporaria corretos estao ativos:

```powershell
aws sts get-caller-identity --profile hackathon
```

Se a identidade estiver correta, o modelo pode nao estar habilitado naquele
ambiente ou a sessao pode ter perdido a elegibilidade. Tente novamente apos alguns
minutos. Como contingencia, teste o modelo que tambem foi validado no evento:

```text
us.anthropic.claude-sonnet-5
```

### Hermes continua usando DeepSeek

Confira o modelo ativo e execute novamente o seletor:

```powershell
hermes model
```

Se necessario, aplique a configuracao manual da secao **7** e reinicie o processo
do Hermes.

## 10. Cuidados de seguranca

- Nunca adicione credenciais AWS ao repositorio, `.env` do frontend ou codigo
  React.
- Nunca exponha credenciais `AWS_*` em codigo executado no navegador.
- Use apenas o profile temporario e restrito `hackathon`; nao conecte ao Hermes um
  profile pessoal ou de producao.
- O Hermes tera as mesmas permissoes AWS concedidas ao profile. Revise comandos de
  shell e alteracoes de infraestrutura antes de autoriza-los.
- Nao publique o link privado, o codigo de acesso do evento ou saidas que identifiquem
  a conta AWS.

## Referencias oficiais

- [Instalar AWS CLI v2 no Windows](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- [Aspas e JSON da AWS CLI no PowerShell](https://docs.aws.amazon.com/cli/latest/userguide/cli-usage-parameters-quoting-strings.html)
- [Claude Opus 5 no Amazon Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5.html)
- [Guia AWS Bedrock do Hermes Agent](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/guides/aws-bedrock.md)
- [Providers do Hermes Agent](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/integrations/providers.md#aws-bedrock)
- [Instalacao do Hermes Agent](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/getting-started/quickstart.md)
