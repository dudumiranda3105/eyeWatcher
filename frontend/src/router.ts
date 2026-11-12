import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import type { Role } from '@/types/api'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    group?: string
    requires?: Role
    public?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { title: 'Dashboard', group: 'Monitorar' },
  },
  {
    path: '/gemeo',
    name: 'twin',
    component: () => import('@/views/TwinView.vue'),
    meta: { title: 'Gêmeo digital', group: 'Monitorar' },
  },
  {
    path: '/insights',
    name: 'insights',
    component: () => import('@/views/InsightsView.vue'),
    meta: { title: 'Insights', group: 'Monitorar' },
  },
  {
    path: '/assistente',
    name: 'assistant',
    component: () => import('@/views/AssistantView.vue'),
    meta: { title: 'Assistente', group: 'Monitorar' },
  },
  {
    path: '/laboratorio',
    name: 'lab',
    component: () => import('@/views/LabView.vue'),
    meta: { title: 'Laboratório de dados', group: 'Inteligência' },
  },
  {
    path: '/treinamento',
    name: 'training',
    component: () => import('@/views/TrainingView.vue'),
    meta: { title: 'Treinamento', group: 'Inteligência' },
  },
  {
    path: '/dispositivos',
    name: 'devices',
    component: () => import('@/views/DevicesView.vue'),
    meta: { title: 'Dispositivos e regras', group: 'Sistema' },
  },
  {
    path: '/mensageria',
    name: 'messaging',
    component: () => import('@/views/MessagingView.vue'),
    meta: { title: 'Mensageria', group: 'Sistema' },
  },
  {
    path: '/auditoria',
    name: 'audit',
    component: () => import('@/views/AuditView.vue'),
    meta: { title: 'Auditoria', group: 'Sistema', requires: 'admin' },
  },
  {
    path: '/servicos',
    name: 'services',
    component: () => import('@/views/ServicesView.vue'),
    meta: { title: 'Serviços', group: 'Sistema' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({ history: createWebHistory(), routes })
export { routes }
