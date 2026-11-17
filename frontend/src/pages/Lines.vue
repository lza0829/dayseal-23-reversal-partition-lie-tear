<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api'

const rows = ref([])
const tills = ref([])
const day = ref('')
const policy = ref('')
const traces = ref([])
const form = ref({ till_code: 'TILL-A', amount: 10, pay_method: '现金', note: '' })
const msg = ref('')
const err = ref('')

const policyText = {
  same_day: '同日对冲：冲正落在原流水同一营业日，净额进入该日封账合计；该日已封则拒绝',
  current_day: '冲正日另计：冲正落入当前营业日，原日已封合计不变，负向额计入冲正日',
}

async function load() {
  err.value = ''
  const d = await api.getDay()
  day.value = d.business_day
  tills.value = await api.tills()
  policy.value = (await api.getReversalPolicy()).reversal_policy
  rows.value = await api.lines(day.value)
  traces.value = await api.reversals()
}

async function add() {
  msg.value = ''; err.value = ''
  try {
    await api.createLine({ ...form.value, business_day: day.value })
    msg.value = '已登记流水'
    await load()
  } catch (e) { err.value = e.message }
}

async function reverse(r) {
  msg.value = ''; err.value = ''
  if (!window.confirm(`确认冲正 ${r.line_no}？原流水保留为只读，系统将生成等额负向流水。`)) return
  try {
    const res = await api.reverseLine(r.id)
    msg.value = `已生成冲正流水 ${res.reversal.line_no}，落点营业日 ${res.reversal_business_day}`
    await load()
  } catch (e) { err.value = e.message }
}

onMounted(load)
</script>

<template>
  <h2>收银流水</h2>
  <p class="msg">营业日 {{ day }}</p>
  <p class="msg">当前冲正策略（全局互斥）：{{ policyText[policy] }}</p>
  <div class="row">
    <label>收银机
      <select v-model="form.till_code">
        <option v-for="t in tills" :key="t.till_code" :value="t.till_code">{{ t.title }}</option>
      </select>
    </label>
    <label>金额 <input type="number" step="0.01" v-model.number="form.amount" /></label>
    <label>支付方式
      <select v-model="form.pay_method">
        <option>现金</option><option>微信</option><option>支付宝</option>
      </select>
    </label>
    <button class="btn" @click="add">登记</button>
  </div>
  <p class="msg">负向流水只能由冲正产生，登记入口不接受负数。</p>
  <p v-if="msg" class="msg">{{ msg }}</p>
  <p v-if="err" class="msg err">{{ err }}</p>
  <div class="panel">
    <table>
      <thead>
        <tr><th>单号</th><th>类型</th><th>机</th><th>时刻</th><th>金额</th><th>方式</th><th>引用原单</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.line_no }}</td>
          <td>
            <span class="tag" :class="r.entry_type === 'reversal' ? 'warn' : 'ok'">
              {{ r.entry_type === 'reversal' ? '冲正' : '普通' }}
            </span>
          </td>
          <td>{{ r.till_code }}</td><td>{{ r.occurred_at }}</td>
          <td>{{ r.amount.toFixed(2) }}</td><td>{{ r.pay_method }}</td>
          <td>{{ r.reversal_of_line_no || '—' }}</td>
          <td>
            <button
              v-if="r.entry_type === 'normal'"
              class="btn ghost"
              @click="reverse(r)"
            >冲正</button>
            <span v-else class="msg">只读</span>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <div class="panel">
    <h2>冲正溯源</h2>
    <table>
      <thead>
        <tr><th>冲正单号</th><th>原单号</th><th>策略</th><th>原营业日</th><th>落点营业日</th><th>负向额</th></tr>
      </thead>
      <tbody>
        <tr v-for="t in traces" :key="t.id">
          <td>{{ t.reversal_line_no }}</td>
          <td>{{ t.original_line_no }}</td>
          <td>{{ t.policy === 'same_day' ? '同日对冲' : '冲正日另计' }}</td>
          <td>{{ t.original_business_day }}</td>
          <td>{{ t.reversal_business_day }}</td>
          <td>{{ t.amount.toFixed(2) }}</td>
        </tr>
        <tr v-if="!traces.length"><td colspan="6" class="msg">暂无冲正记录</td></tr>
      </tbody>
    </table>
  </div>
</template>
