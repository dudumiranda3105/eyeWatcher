<script setup lang="ts">
import { computed } from 'vue'
import type { RackStatus } from '@/types/api'
import { formatDecimal, formatRelative } from '@/utils/format'
import { humidityStatus, temperatureStatus, THRESHOLDS } from '@/utils/thresholds'

const props = defineProps<{
  status: RackStatus
  online: boolean
  /** Sem leitura recente, mesmo com o dispositivo marcado como online. */
  stale: boolean
  lastReadingTime: string | null
  /** Relógio do store, para o texto relativo acompanhar o tempo. */
  now: number
  temperature: number | null
  humidity: number | null
  /** A API não respondeu: o painel não sabe nada sobre o rack. */
  apiDown: boolean
}>()

const bannerStatus = computed<string>(() =>
  props.online && !props.apiDown ? props.status : 'offline',
)

const headline = computed<string>(() => {
  if (props.apiDown) return 'Sem contato com a API'
  if (!props.lastReadingTime) return 'Aguardando a primeira leitura do sensor'
  if (!props.online) return 'Dispositivo offline'
  if (props.status === 'critical') return 'Condição crítica no rack'
  if (props.status === 'warning') return 'Rack em faixa de alerta'
  return 'Rack em operação normal'
})

const detail = computed<string>(() => {
  if (props.apiDown) {
    return 'O painel está no ar, mas o backend não devolveu leituras. As tentativas continuam a cada 10 s.'
  }
  if (!props.lastReadingTime) {
    return 'O ESP32 ainda não publicou telemetria neste rack.'
  }
  if (!props.online) {
    return props.stale
      ? 'O sensor parou de publicar. Verifique a alimentação e o Wi-Fi do ESP32.'
      : 'O broker MQTT registrou o dispositivo como offline.'
  }
  if (props.status === 'ok') {
    return 'Temperatura e umidade dentro dos limiares definidos no contrato.'
  }

  const causes: string[] = []
  const temp = props.temperature
  const hum = props.humidity

  if (temp !== null && temperatureStatus(temp) !== 'ok') {
    const limit = temp >= THRESHOLDS.TEMP_CRIT ? THRESHOLDS.TEMP_CRIT : THRESHOLDS.TEMP_WARN
    causes.push(`temperatura em ${formatDecimal(temp)} °C, acima de ${limit} °C`)
  }
  if (hum !== null && humidityStatus(hum) !== 'ok') {
    causes.push(`umidade em ${formatDecimal(hum)} %, fora da faixa de 30 % a 70 %`)
  }

  const joined = causes.join(' e ')
  const cause = joined ? `${joined.charAt(0).toUpperCase()}${joined.slice(1)}. ` : ''
  return props.status === 'critical'
    ? `${cause}Acione a refrigeração e confirme o fluxo de ar.`
    : `${cause}Acompanhe a tendência antes que chegue ao limite crítico.`
})

const badge = computed<string>(() => {
  if (props.apiDown) return 'Sem API'
  if (!props.lastReadingTime) return 'Sem dados'
  if (!props.online) return 'Offline'
  if (props.status === 'critical') return 'Crítico'
  if (props.status === 'warning') return 'Alerta'
  return 'Normal'
})
</script>

<template>
  <section class="banner" :data-status="bannerStatus" role="status" aria-live="polite">
    <span class="banner__badge mono">{{ badge }}</span>

    <div class="banner__text">
      <h2 class="banner__headline">{{ headline }}</h2>
      <p class="banner__detail">{{ detail }}</p>
    </div>

    <div class="banner__meta mono">
      <span class="banner__dot" :class="{ 'banner__dot--live': online }" aria-hidden="true" />
      <span>{{ online ? 'Transmitindo' : 'Sem sinal' }}</span>
      <span class="banner__sep" aria-hidden="true">/</span>
      <span>última leitura {{ formatRelative(lastReadingTime, now) }}</span>
    </div>
  </section>
</template>

<style scoped>
.banner {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 14px 20px;
  background: var(--status-wash);
  border: 1px solid var(--line);
  border-left: 10px solid var(--status);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  transition: background-color 300ms ease, border-color 300ms ease;
}

.banner__badge {
  flex: none;
  padding: 7px 12px;
  background: var(--status);
  color: var(--on-status);
  border-radius: var(--radius);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.banner__text {
  flex: 1 1 auto;
  min-width: 0;
}

.banner__headline {
  font-size: clamp(1.05rem, 1.9vw, 1.6rem);
  font-weight: 700;
  line-height: 1.15;
  color: var(--ink);
}

.banner__detail {
  margin: 3px 0 0;
  font-size: 13px;
  color: var(--ink-muted);
}

.banner__meta {
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  letter-spacing: 0.06em;
  color: var(--ink-muted);
  text-align: right;
}

.banner__sep {
  color: var(--line-strong);
}

.banner__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--ink-faint);
}

.banner__dot--live {
  background: var(--status);
  animation: pulse 2.4s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    box-shadow: 0 0 0 0 var(--status-wash);
    opacity: 1;
  }
  50% {
    box-shadow: 0 0 0 5px transparent;
    opacity: 0.55;
  }
}

@media (max-width: 860px) {
  .banner {
    flex-wrap: wrap;
    gap: 12px;
  }

  .banner__meta {
    width: 100%;
    justify-content: flex-start;
    text-align: left;
  }
}
</style>
