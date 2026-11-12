<script setup lang="ts">
import type { Status } from '@/types/api'
import { STATUS_LABEL } from '@/utils/format'

defineProps<{ status: Status; label?: string }>()
</script>

<template>
  <span class="badge" :data-status="status">{{ label ?? STATUS_LABEL[status] }}</span>
</template>
