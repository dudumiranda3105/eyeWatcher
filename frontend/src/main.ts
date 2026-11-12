import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './services/api'
import { useLiveStore } from './stores/live'
import { useSessionStore } from './stores/session'
import '@fontsource-variable/archivo'
import '@fontsource-variable/public-sans'
import '@fontsource/martian-mono/400.css'
import '@fontsource/martian-mono/500.css'
import './styles/theme.css'

const app = createApp(App).use(createPinia())

const session = useSessionStore()
const live = useLiveStore()

setUnauthorizedHandler(() => {
  live.stop()
  session.logout()
  void router.push('/login')
})

router.beforeEach(async (to) => {
  if (!session.ready) await session.restore()
  if (to.meta.public) return session.authenticated ? '/' : true
  if (!session.authenticated) return '/login'
  if (to.meta.requires && !session.can(to.meta.requires)) return '/'
  void live.start()
  return true
})

// Depois de uma atualização do site, uma aba antiga pede arquivos que não existem
// mais. Recarregar a página busca a versão nova em vez de deixar a tela em branco.
router.onError((error: unknown, to) => {
  const message = error instanceof Error ? error.message : ''
  if (/dynamically imported module|module script/i.test(message)) {
    window.location.assign(to.fullPath)
  }
})

app.use(router).mount('#app')
