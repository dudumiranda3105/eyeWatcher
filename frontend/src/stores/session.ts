import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { http, readToken, storeToken } from '@/services/api'
import type { Role } from '@/types/api'

const RANK: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 }

export const ROLE_LABEL: Record<Role, string> = {
  viewer: 'Visualizador',
  operator: 'Operador',
  admin: 'Administrador',
}

export const useSessionStore = defineStore('session', () => {
  const username = ref<string | null>(null)
  const role = ref<Role | null>(null)
  const ready = ref(false)

  const authenticated = computed(() => username.value !== null)

  function can(required: Role): boolean {
    return role.value !== null && RANK[role.value] >= RANK[required]
  }

  async function restore(): Promise<void> {
    if (readToken()) {
      try {
        const { data } = await http.get<{ username: string; role: Role }>('/auth/me')
        username.value = data.username
        role.value = data.role
      } catch {
        storeToken(null)
      }
    }
    ready.value = true
  }

  async function login(user: string, password: string): Promise<void> {
    const { data } = await http.post<{ token: string; username: string; role: Role }>(
      '/auth/login',
      { username: user, password },
    )
    storeToken(data.token)
    username.value = data.username
    role.value = data.role
  }

  function logout(): void {
    storeToken(null)
    username.value = null
    role.value = null
  }

  return { username, role, ready, authenticated, can, restore, login, logout }
})
