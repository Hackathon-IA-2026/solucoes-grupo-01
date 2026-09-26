# CurtailLess v5

Protótipo B2B para análise de exposição a curtailment, comparação de janelas de manutenção e triagem de bateria sobre a perda residual.

## Executar

```bash
npm install
npm run dev
```

## Verificar

```bash
npm run typecheck
npm run lint
npm test
npm run build
npm run test:e2e
```

A demonstração usa histórico real identificado do ONS e fixtures sintéticas claramente rotuladas. O frontend não acessa diretamente o bucket público do ONS e não recalcula fórmulas de negócio.
