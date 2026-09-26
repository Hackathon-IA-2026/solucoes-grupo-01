# Nome do Projeto

> Descrição curta (1-2 frases): o que o projeto faz e qual problema ele resolve.

## Demo

- **Link da demo:** (se houver, ex: Vercel, Netlify, etc.)

## Tecnologias utilizadas

- Linguagem: (ex: Python, JavaScript, Go...)
- Framework(s): (ex: React, Flask, Node...)
- Banco de dados: 
- APIs / Serviços externos: (se houver)

## Como rodar o projeto

```bash
# Clone o repositório
git clone https://github.com/usuario/repo.git
cd repo

# Instale as dependências
# (ex: npm install / pip install -r requirements.txt)

# Rode o projeto
# (ex: npm run dev / python app.py)
```

## Pré-requisitos

Liste aqui o que precisa estar instalado antes de rodar o projeto (ex: Node 18+, Python 3.10+, Docker, etc.)

## Integração contínua

Pull requests executam o workflow `.github/workflows/ci.yml`, com verificações independentes para:

- backend: dependências com `uv`, testes, Ruff e formatação;
- infraestrutura: validação e build do template AWS SAM;
- frontend: instalação reproduzível, tipos, lint, testes e build.

O workflow concede apenas permissão de leitura ao conteúdo e não recebe credenciais AWS. Deploy automático não faz parte deste CI. A adoção de CD deve ser avaliada separadamente, porque a conta do workshop usa credenciais temporárias e políticas IAM limitadas.

## Licença

Este projeto está sob a licença MIT — veja o arquivo [LICENSE](./LICENSE) para mais detalhes.
