<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const day = ref('')
const policy = ref('same_day')
const msg = ref('')
const err = ref('')

onMounted(async () => {
  const d = await api.getDay()
  day.value = d.business_day
  policy.value = (await api.getReversalPolicy()).reversal_policy
})

async function save() {
  msg.value = ''; err.value = ''
  try {
    await api.setDay(day.value)
    msg.value = '已更新营业日'
  } catch (e) { err.value = e.message }
}

async function savePolicy() {
  msg.value = ''; err.value = ''
  try {
    await api.setReversalPolicy(policy.value)
    msg.value = '已更新冲正策略，全系统即刻只贯彻这一种'
  } catch (e) { err.value = e.message }
}
</script>

<template>
  <h2>设置</h2>
  <div class="row">
    <label>营业日 <input v-model="day" placeholder="YYYY-MM-DD" /></label>
    <button class="btn" @click="save">保存</button>
  </div>

  <h2>冲正命运（全局互斥）</h2>
  <p class="msg">同一时刻全系统只贯彻一种策略，切换对后续发起的冲正立即生效。</p>
  <div class="row">
    <label>冲正策略
      <select v-model="policy">
        <option value="same_day">同日对冲：冲正落原流水同一营业日，已封日无解封则拒绝</option>
        <option value="current_day">冲正日另计：冲正落当前营业日，原日已封合计不变</option>
      </select>
    </label>
    <button class="btn" @click="savePolicy">保存策略</button>
  </div>

  <p v-if="msg" class="msg">{{ msg }}</p>
  <p v-if="err" class="msg err">{{ err }}</p>
</template>
