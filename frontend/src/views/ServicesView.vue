<script setup lang="ts">
const LINKS = [
  {
    name: 'Documentação da API',
    url: '/api/docs',
    note: 'Swagger do FastAPI, na mesma porta da aplicação.',
  },
  {
    name: 'RabbitMQ',
    url: 'http://127.0.0.1:15672',
    note: 'Usuário admin. Filas, exchanges e mensagens por dentro.',
  },
  {
    name: 'InfluxDB',
    url: 'http://127.0.0.1:8086',
    note: 'Usuário eyewatcher. Buckets telemetry (ao vivo) e lab (sintético).',
  },
  {
    name: 'PostgreSQL (Adminer)',
    url: 'http://127.0.0.1:8081',
    note: 'Servidor postgres, usuário e banco eyewatcher.',
  },
]
</script>

<template>
  <div class="page">
    <header class="page-head">
      <div>
        <h1>Serviços</h1>
        <p>
          Interfaces para explorar os dados em aula. Só abrem nesta máquina (127.0.0.1), e as senhas
          ficam em <code>secrets/CREDENCIAIS.txt</code>.
        </p>
      </div>
    </header>
    <section class="grid">
      <a v-for="link in LINKS" :key="link.url" class="panel panel-body card" :href="link.url" target="_blank" rel="noopener">
        <h2>{{ link.name }}</h2>
        <span class="mono muted">{{ link.url }}</span>
        <p class="note">{{ link.note }}</p>
      </a>
    </section>
  </div>
</template>

<style scoped>
.card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  color: inherit;
  text-decoration: none;
}

.card:hover {
  border-color: var(--line-strong);
}

.card h2 {
  font-size: 16px;
}

.card span {
  font-size: 12px;
}
</style>
