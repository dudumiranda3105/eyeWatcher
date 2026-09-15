<script setup lang="ts">
import type { RangeKey } from '@/types/api'
import { RANGE_LABEL } from '@/utils/format'

const props = defineProps<{
  modelValue: RangeKey
  /** Períodos oferecidos; o contrato também aceita 30d. */
  options?: readonly RangeKey[]
  disabled?: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: RangeKey): void
}>()

const DEFAULT_OPTIONS: readonly RangeKey[] = ['15m', '1h', '6h', '24h', '7d']

function select(value: RangeKey): void {
  if (props.disabled || value === props.modelValue) return
  emit('update:modelValue', value)
}
</script>

<template>
  <div class="ranges" role="group" aria-label="Período do histórico">
    <span class="eyebrow ranges__label">Período</span>
    <div class="ranges__group">
      <button
        v-for="option in options ?? DEFAULT_OPTIONS"
        :key="option"
        type="button"
        class="ranges__button mono"
        :class="{ 'ranges__button--active': option === modelValue }"
        :aria-pressed="option === modelValue"
        :disabled="disabled"
        :title="RANGE_LABEL[option]"
        @click="select(option)"
      >
        {{ option }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.ranges {
  display: flex;
  align-items: center;
  gap: 10px;
}

.ranges__label {
  white-space: nowrap;
}

.ranges__group {
  display: flex;
  border: 1px solid var(--line-strong);
  border-radius: var(--radius);
  overflow: hidden;
}

.ranges__button {
  padding: 6px 12px;
  min-width: 48px;
  background: var(--panel);
  border: none;
  border-right: 1px solid var(--line);
  font-size: 11px;
  font-weight: 500;
  color: var(--ink-muted);
  cursor: pointer;
  transition: background-color 150ms ease, color 150ms ease;
}

.ranges__button:last-child {
  border-right: none;
}

.ranges__button:hover:not(:disabled):not(.ranges__button--active) {
  background: var(--panel-sunk);
  color: var(--ink);
}

.ranges__button--active {
  background: var(--ink);
  color: var(--panel);
  font-weight: 700;
}

.ranges__button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}
</style>
