<script setup lang="ts">
/**
 * A shared whiteboard in the meeting: everyone draws, everyone sees it right away. Lines are kept by the people in
 * the meeting (nothing is stored on the server); "Save picture" downloads it as a PNG.
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import AppIcon from './AppIcon.vue'
import { t } from '@/lib/i18n'
import type { Stroke } from '@/lib/meeting'

const props = defineProps<{ strokes: Stroke[] }>()
const emit = defineEmits<{ draw: [stroke: Stroke]; clear: []; close: [] }>()

const COLORS = ['#1f2937', '#2563eb', '#dc2626', '#16a34a', '#f59e0b']
const SIZES = [3, 6, 12]
const SCALE = 1000
const color = ref(COLORS[0])
const size = ref(SIZES[0])
const eraser = ref(false)
const canvas = ref<HTMLCanvasElement | null>(null)
let current: Stroke | null = null
let observer: ResizeObserver | null = null

function paintStroke(ctx: CanvasRenderingContext2D, s: Stroke, w: number, h: number) {
  if (s.points.length < 2) return
  ctx.strokeStyle = s.color
  ctx.lineWidth = (s.size * w) / SCALE
  ctx.lineCap = 'round'
  ctx.lineJoin = 'round'
  ctx.beginPath()
  ctx.moveTo((s.points[0] * w) / SCALE, (s.points[1] * h) / SCALE)
  for (let i = 2; i < s.points.length; i += 2) ctx.lineTo((s.points[i] * w) / SCALE, (s.points[i + 1] * h) / SCALE)
  if (s.points.length === 2) ctx.lineTo((s.points[0] * w) / SCALE + 0.1, (s.points[1] * h) / SCALE)
  ctx.stroke()
}

function paint() {
  const el = canvas.value
  if (!el) return
  const ctx = el.getContext('2d')!
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, el.width, el.height)
  for (const s of props.strokes) paintStroke(ctx, s, el.width, el.height)
  if (current) paintStroke(ctx, current, el.width, el.height)
}

function resize() {
  const el = canvas.value
  if (!el) return
  const ratio = window.devicePixelRatio || 1
  el.width = Math.round(el.clientWidth * ratio)
  el.height = Math.round(el.clientHeight * ratio)
  paint()
}

function point(event: PointerEvent): [number, number] {
  const r = canvas.value!.getBoundingClientRect()
  return [Math.round(((event.clientX - r.left) / r.width) * SCALE), Math.round(((event.clientY - r.top) / r.height) * SCALE)]
}

function down(event: PointerEvent) {
  if (event.button !== 0) return
  canvas.value?.setPointerCapture(event.pointerId)
  current = { id: `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`, color: eraser.value ? '#ffffff' : color.value, size: eraser.value ? 30 : size.value, points: point(event) }
  paint()
}

function move(event: PointerEvent) {
  if (!current) return
  const [x, y] = point(event)
  const n = current.points.length
  if (Math.abs(current.points[n - 2] - x) + Math.abs(current.points[n - 1] - y) < 3) return
  if (n >= 4000) return up()
  current.points.push(x, y)
  paint()
}

function up() {
  if (!current) return
  emit('draw', current)
  current = null
}

function save() {
  const el = canvas.value
  if (!el) return
  const link = document.createElement('a')
  link.download = `${t('meeting.board.fileName')}.png`
  link.href = el.toDataURL('image/png')
  link.click()
}

watch(() => props.strokes.length, paint)
watch(() => props.strokes, paint)
onMounted(() => {
  observer = new ResizeObserver(resize)
  if (canvas.value) observer.observe(canvas.value)
  resize()
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <section class="whiteboard" :aria-label="t('meeting.board.title')">
    <div class="tools" role="toolbar" :aria-label="t('meeting.board.tools')">
      <button v-for="c in COLORS" :key="c" type="button" class="swatch" :class="[`c${COLORS.indexOf(c)}`, { active: !eraser && color === c }]" :aria-label="t(`meeting.board.colors.c${COLORS.indexOf(c)}`)" :aria-pressed="!eraser && color === c" @click="color = c; eraser = false" />
      <span class="sep" aria-hidden="true" />
      <button v-for="s in SIZES" :key="s" type="button" class="size" :class="{ active: size === s && !eraser }" :aria-label="t(`meeting.board.sizes.s${s}`)" :aria-pressed="size === s && !eraser" @click="size = s; eraser = false"><span :class="`dot d${s}`" /></button>
      <button type="button" class="tool" :class="{ active: eraser }" :aria-pressed="eraser" @click="eraser = !eraser">{{ t('meeting.board.eraser') }}</button>
      <span class="sep" aria-hidden="true" />
      <button type="button" class="tool" @click="emit('clear')"><AppIcon name="trash" :size="16" />{{ t('meeting.board.clear') }}</button>
      <button type="button" class="tool" @click="save"><AppIcon name="download" :size="16" />{{ t('meeting.board.save') }}</button>
      <button type="button" class="tool close" :aria-label="t('meeting.board.close')" @click="emit('close')"><AppIcon name="close" :size="18" /></button>
    </div>
    <canvas ref="canvas" class="board" @pointerdown="down" @pointermove="move" @pointerup="up" @pointercancel="up" @pointerleave="up" />
  </section>
</template>

<style scoped>
.whiteboard {
  position: relative;
  display: grid;
  grid-template-rows: auto 1fr;
  min-height: 0;
  height: 100%;
  overflow: hidden;
  border-radius: 14px;
  background: #fff;
}

.tools {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-bottom: 1px solid #e5e7eb;
  background: #f8fafc;
  color: #1f2937;
}

.swatch {
  width: 28px;
  height: 28px;
  border: 2px solid #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 1px #cbd5e1;
  cursor: pointer;
}

.swatch.active {
  box-shadow: 0 0 0 3px #2563eb;
}

.c0 { background: #1f2937; }
.c1 { background: #2563eb; }
.c2 { background: #dc2626; }
.c3 { background: #16a34a; }
.c4 { background: #f59e0b; }

.sep {
  width: 1px;
  height: 24px;
  margin: 0 4px;
  background: #cbd5e1;
}

.size,
.tool {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-height: 34px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: none;
  color: inherit;
  font: inherit;
  font-size: 0.85rem;
  cursor: pointer;
}

.size.active,
.tool.active,
.size:hover,
.tool:hover {
  border-color: #cbd5e1;
  background: #fff;
}

.dot {
  display: block;
  border-radius: 50%;
  background: currentColor;
}

.d3 { width: 4px; height: 4px; }
.d6 { width: 8px; height: 8px; }
.d12 { width: 14px; height: 14px; }

.close {
  margin-left: auto;
}

.board {
  width: 100%;
  height: 100%;
  touch-action: none;
  cursor: crosshair;
}
</style>
