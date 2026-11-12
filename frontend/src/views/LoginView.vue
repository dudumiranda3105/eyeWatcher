<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { PhEye } from '@phosphor-icons/vue'
import { errorMessage } from '@/services/api'
import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const router = useRouter()

const username = ref('')
const password = ref('')
const error = ref('')
const busy = ref(false)

async function submit(): Promise<void> {
  busy.value = true
  error.value = ''
  try {
    await session.login(username.value, password.value)
    await router.push('/')
  } catch (cause) {
    error.value = errorMessage(cause)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login">
    <section class="pitch" aria-hidden="true">
      <div class="logo">
        <span class="mark"><PhEye :size="20" weight="bold" /></span>
        eyeWatcher
      </div>
      <div class="message">
        <h1>A sala avisa antes de esquentar.</h1>
        <p>
          Sensores, gêmeo digital 3D e manutenção preditiva dos ar-condicionados da sala de
          servidores, em tempo real.
        </p>
      </div>
      <p class="foot">Projeto AIoT, 2º bimestre</p>
    </section>

    <section class="entry">
      <form @submit.prevent="submit">
        <h2>Entrar</h2>
        <label class="field">
          Usuário
          <input v-model="username" autocomplete="username" required autofocus />
        </label>
        <label class="field">
          Senha
          <input v-model="password" type="password" autocomplete="current-password" required />
        </label>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <button class="btn btn-primary" type="submit" :disabled="busy">
          {{ busy ? 'Entrando' : 'Entrar' }}
        </button>
        <p class="note">As senhas de demonstração ficam em <code>secrets/CREDENCIAIS.txt</code>.</p>
      </form>
    </section>
  </div>
</template>

<style scoped>
.login {
  min-height: 100dvh;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(360px, 1fr);
}

/* O lado da marca é sempre escuro, nos dois temas: é a "sala" do produto. */
.pitch {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 32px;
  padding: 40px 48px;
  color: #f2f3f5;
  background-color: #050505;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.045) 1px, transparent 1px),
    radial-gradient(circle at 78% 18%, rgba(90, 168, 255, 0.16), transparent 46%);
  background-size:
    44px 44px,
    44px 44px,
    100% 100%;
}

.logo {
  display: flex;
  align-items: center;
  gap: 10px;
  font-family: var(--font-display);
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

.mark {
  display: grid;
  place-items: center;
  width: 36px;
  height: 36px;
  border-radius: var(--radius);
  background: #5aa8ff;
  color: #04101a;
}

.message h1 {
  font-size: clamp(34px, 4.4vw, 58px);
  line-height: 1.04;
  letter-spacing: -0.03em;
  max-width: 13ch;
}

.message p {
  margin: 18px 0 0;
  max-width: 46ch;
  font-size: 17px;
  color: #a8abb1;
}

.foot {
  margin: 0;
  font-size: 13px;
  color: #7f838a;
}

.entry {
  display: grid;
  place-items: center;
  padding: 32px 24px;
  background: var(--panel);
}

form {
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: min(340px, 100%);
  animation: rise 0.5s var(--ease) both;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
}

h2 {
  font-size: 26px;
  margin-bottom: 4px;
}

.btn-primary {
  padding: 10px 13px;
  margin-top: 4px;
}

@media (max-width: 820px) {
  .login {
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto 1fr;
  }

  .pitch {
    padding: 28px 24px;
    gap: 24px;
  }

}
</style>
