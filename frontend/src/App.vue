<script setup lang="ts">
import { computed, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  PhArrowsLeftRight,
  PhChartLineUp,
  PhChatCircleDots,
  PhClipboardText,
  PhCpu,
  PhCube,
  PhEye,
  PhFlask,
  PhGauge,
  PhHeartbeat,
  PhLinkSimple,
  PhList,
  PhMoon,
  PhSignOut,
  PhSun,
} from '@phosphor-icons/vue'
import StatusBadge from '@/components/StatusBadge.vue'
import { theme, toggleTheme } from '@/composables/useTheme'
import { routes } from '@/router'
import { useLiveStore } from '@/stores/live'
import { ROLE_LABEL, useSessionStore } from '@/stores/session'
import type { Status } from '@/types/api'

const route = useRoute()
const router = useRouter()
const session = useSessionStore()
const live = useLiveStore()

const ICONS: Record<string, Component> = {
  dashboard: PhGauge,
  twin: PhCube,
  insights: PhHeartbeat,
  assistant: PhChatCircleDots,
  lab: PhFlask,
  training: PhChartLineUp,
  devices: PhCpu,
  messaging: PhArrowsLeftRight,
  audit: PhClipboardText,
  services: PhLinkSimple,
}

const menuOpen = ref(false)
watch(
  () => route.fullPath,
  () => (menuOpen.value = false),
)

const groups = computed(() => {
  const result = new Map<string, { path: string; title: string; icon?: Component }[]>()
  for (const item of routes) {
    const { group, title, requires } = item.meta ?? {}
    if (!group || !title || (requires && !session.can(requires))) continue
    const entry = { path: item.path, title, icon: ICONS[String(item.name)] }
    result.set(group, [...(result.get(group) ?? []), entry])
  }
  return [...result.entries()]
})

const openAlerts = computed(() => live.alerts.filter((alert) => !alert.cleared_at).length)

const dataStatus = computed<{ status: Status; label: string }>(() => {
  if (live.connection !== 'open') return { status: 'warning', label: 'Reconectando' }
  if (!live.anyLive) return { status: 'offline', label: 'Sem dados' }
  return { status: 'ok', label: 'Ao vivo' }
})

const initials = computed(() => (session.username ?? '?').slice(0, 2).toUpperCase())

function logout(): void {
  live.stop()
  session.logout()
  void router.push('/login')
}
</script>

<template>
  <RouterView v-if="route.meta.public" />
  <div v-else class="shell">
    <aside class="side" :class="{ open: menuOpen }">
      <div class="brand">
        <RouterLink to="/" class="logo">
          <span class="mark"><PhEye :size="18" weight="bold" /></span>
          eyeWatcher
        </RouterLink>
        <button
          class="btn btn-ghost menu"
          type="button"
          aria-label="Abrir menu"
          :aria-expanded="menuOpen"
          @click="menuOpen = !menuOpen"
        >
          <PhList :size="20" />
        </button>
      </div>

      <nav>
        <section v-for="[group, items] in groups" :key="group">
          <span class="eyebrow">{{ group }}</span>
          <RouterLink v-for="item in items" :key="item.path" :to="item.path">
            <component :is="item.icon" :size="18" />
            <span class="label">{{ item.title }}</span>
            <span v-if="item.path === '/insights' && openAlerts" class="count mono">{{ openAlerts }}</span>
          </RouterLink>
        </section>
      </nav>

      <footer>
        <div class="state">
          <StatusBadge :status="dataStatus.status" :label="dataStatus.label" />
          <button
            class="btn btn-ghost icon"
            type="button"
            :aria-label="theme === 'dark' ? 'Usar tema claro' : 'Usar tema escuro'"
            @click="toggleTheme"
          >
            <PhSun v-if="theme === 'dark'" :size="18" />
            <PhMoon v-else :size="18" />
          </button>
        </div>
        <div class="user">
          <span class="avatar mono">{{ initials }}</span>
          <div class="who">
            <strong>{{ session.username }}</strong>
            <span class="muted">{{ session.role ? ROLE_LABEL[session.role] : '' }}</span>
          </div>
          <button class="btn btn-ghost icon" type="button" aria-label="Sair" @click="logout">
            <PhSignOut :size="18" />
          </button>
        </div>
      </footer>
    </aside>
    <main class="content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: grid;
  grid-template-columns: 240px minmax(0, 1fr);
  min-height: 100dvh;
}

.side {
  position: sticky;
  top: 0;
  height: 100dvh;
  display: flex;
  flex-direction: column;
  gap: 22px;
  padding: 20px 14px 16px;
  background: var(--panel);
  border-right: 1px solid var(--line);
  overflow-y: auto;
}

.brand {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 6px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-display);
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--ink);
  text-decoration: none;
}

.mark {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: var(--radius);
  background: var(--accent);
  color: var(--accent-ink);
}

.menu {
  display: none;
}

nav {
  display: flex;
  flex-direction: column;
  gap: 20px;
  flex: 1;
}

nav section {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

nav .eyebrow {
  padding: 0 10px 6px;
}

nav a {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius);
  color: var(--ink-muted);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition:
    background-color 0.15s,
    color 0.15s;
}

nav a .label {
  flex: 1;
}

nav a:hover {
  background: var(--panel-sunk);
  color: var(--ink);
}

nav a.router-link-exact-active {
  background: var(--accent-wash);
  color: var(--accent);
  font-weight: 600;
}

nav a.router-link-exact-active::before {
  content: '';
  position: absolute;
  left: -14px;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--accent);
}

.count {
  font-size: 11px;
  padding: 1px 7px;
  border-radius: 999px;
  background: var(--crit);
  color: var(--on-status);
}

footer {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}

.state,
.user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 4px;
}

.state {
  justify-content: space-between;
}

.icon {
  padding: 6px;
}

.avatar {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: var(--panel-sunk);
  border: 1px solid var(--line);
  font-size: 11px;
  color: var(--ink-muted);
}

.who {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  font-size: 13px;
  line-height: 1.25;
}

.who strong {
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 600;
}

.who .muted {
  font-size: 12px;
}

@media (max-width: 860px) {
  .shell {
    grid-template-columns: minmax(0, 1fr);
  }

  .side {
    position: static;
    height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
    padding: 12px 16px;
    gap: 14px;
  }

  .menu {
    display: inline-flex;
  }

  nav,
  footer {
    display: none;
  }

  .side.open nav,
  .side.open footer {
    display: flex;
  }

  nav a.router-link-exact-active::before {
    left: -16px;
  }
}
</style>
