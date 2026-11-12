# Frontend do eyeWatcher

Vue 3, TypeScript, Vite, Pinia, Chart.js e Three.js. Em produção quem serve é o nginx
do container, na porta 8080, encaminhando `/api` e `/ws` para a API.

## Desenvolvimento

Com a API rodando em `localhost:8000`:

```bash
npm install
npm run dev
```

## Onde fica cada coisa

- `src/views/`: uma página por rota
- `src/stores/live.ts`: WebSocket e último valor de cada dispositivo
- `src/stores/session.ts`: login e papéis
- `src/three/twin.ts`: cena 3D, que lê o store dentro do laço de animação
- `src/three/layout.ts`: posição 3D de cada dispositivo, indexada pelo id do cadastro
