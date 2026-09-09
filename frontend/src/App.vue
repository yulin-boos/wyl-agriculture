<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  createDiagnosis,
  getCrops,
  getHealth,
  getHistory,
  getProviders,
  testProviderConnection,
} from './api'
import { FALLBACK_API_PROVIDERS } from './providers'

const API_CONFIG_STORAGE_KEY = 'crop-disease-api-config'

function readSavedApiConfig() {
  try {
    const value = sessionStorage.getItem(API_CONFIG_STORAGE_KEY)
    return value ? JSON.parse(value) : null
  } catch {
    return null
  }
}

const activeView = ref('diagnose')
const crops = ref([])
const history = ref([])
const historyTotal = ref(0)
const selectedHistory = ref(null)
const result = ref(null)
const errorMessage = ref('')
const loading = ref(false)
const historyLoading = ref(false)
const fileInput = ref(null)
const selectedFile = ref(null)
const previewUrl = ref('')
const serviceStatus = ref('checking')
const form = ref({ crop: 'Tomato', symptom: '' })
const providers = ref(FALLBACK_API_PROVIDERS)
const savedApiConfig = ref(readSavedApiConfig())
const apiForm = ref({
  provider: savedApiConfig.value?.provider || 'deepseek',
  baseUrl: savedApiConfig.value?.baseUrl || '',
  model: savedApiConfig.value?.model || '',
  apiKey: savedApiConfig.value?.apiKey || '',
})
const showApiKey = ref(false)
const apiConfigError = ref('')
const apiConfigMessage = ref('')
const transportAcknowledged = ref(false)
const apiTesting = ref(false)
const apiTestResult = ref(null)
const apiTestError = ref('')

function getClientId() {
  const key = 'crop-disease-client-id'
  let id = localStorage.getItem(key)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(key, id)
  }
  return id
}

const clientId = getClientId()
const currentReport = computed(() => selectedHistory.value || result.value)
const selectedCropCoverage = computed(() =>
  crops.value.find((crop) => crop.key === form.value.crop)?.diseases || [],
)
const confidenceStyle = computed(() => {
  const value = Math.min(100, Math.max(0, currentReport.value?.likelihood_percent || 0))
  return { '--confidence': `${value}%` }
})
const selectedProvider = computed(() =>
  providers.value.find((provider) => provider.id === apiForm.value.provider),
)
const savedProvider = computed(() =>
  providers.value.find((provider) => provider.id === savedApiConfig.value?.provider),
)
const apiTransportIsInsecure = computed(() =>
  window.location.protocol === 'http:'
    || (import.meta.env.VITE_API_BASE_URL || 'http://170.106.137.89/api').startsWith('http://'),
)
const apiConfigured = computed(() => Boolean(savedApiConfig.value?.apiKey))
const actualRequestUrl = computed(() => {
  const baseUrl = normalizeBaseUrl(apiForm.value.baseUrl)
  return baseUrl ? `${baseUrl}/chat/completions` : '请先填写 API 基础地址'
})

function normalizeBaseUrl(value) {
  return value.trim().replace(/\/+$/, '').replace(/\/chat\/completions$/i, '')
}

function resetApiTest() {
  apiTestResult.value = null
  apiTestError.value = ''
}

function applyProviderDefaults() {
  const provider = selectedProvider.value
  if (!provider) return
  apiForm.value.baseUrl = provider.base_url
  apiForm.value.model = provider.default_model
  apiConfigError.value = ''
  apiConfigMessage.value = ''
  resetApiTest()
}

function validatedApiConfig() {
  apiConfigError.value = ''
  apiConfigMessage.value = ''
  const provider = selectedProvider.value
  const apiKey = apiForm.value.apiKey.trim()
  const model = apiForm.value.model.trim()
  const baseUrl = normalizeBaseUrl(apiForm.value.baseUrl)
  if (!provider) {
    apiConfigError.value = '请选择 API 厂家。'
    return null
  }
  if (apiKey.length < 8 || /\s/.test(apiKey)) {
    apiConfigError.value = '请输入有效的 API 密钥，密钥中不能包含空格。'
    return null
  }
  if (!model) {
    apiConfigError.value = '请输入厂家支持的模型名称。'
    return null
  }
  if (provider.custom && !baseUrl.startsWith('https://')) {
    apiConfigError.value = '自定义 API 必须使用公开的 HTTPS 地址。'
    return null
  }
  if (apiTransportIsInsecure.value && !transportAcknowledged.value) {
    apiConfigError.value = '请先确认你了解当前 HTTP 云接口的密钥传输风险。'
    return null
  }
  return {
    provider: provider.id,
    baseUrl: provider.custom ? baseUrl : provider.base_url,
    model,
    apiKey,
  }
}

function saveApiConfig() {
  const config = validatedApiConfig()
  if (!config) return
  const provider = selectedProvider.value
  sessionStorage.setItem(API_CONFIG_STORAGE_KEY, JSON.stringify(config))
  savedApiConfig.value = config
  apiForm.value = { ...config }
  apiConfigMessage.value = `${provider.name} 已用于当前浏览器会话。`
}

async function testApiConfig() {
  const config = validatedApiConfig()
  if (!config) return
  apiTesting.value = true
  resetApiTest()
  const payload = new FormData()
  payload.append('api_provider', config.provider)
  payload.append('api_model', config.model)
  payload.append('api_key', config.apiKey)
  if (config.provider === 'custom') payload.append('api_base_url', config.baseUrl)
  try {
    apiTestResult.value = await testProviderConnection(payload)
  } catch (error) {
    apiTestError.value = error.message
  } finally {
    apiTesting.value = false
  }
}

function clearApiConfig() {
  sessionStorage.removeItem(API_CONFIG_STORAGE_KEY)
  savedApiConfig.value = null
  apiForm.value.apiKey = ''
  showApiKey.value = false
  apiConfigError.value = ''
  apiConfigMessage.value = '当前会话中的 API 配置已清除。'
  resetApiTest()
}

function chooseFile() { fileInput.value?.click() }

function setFile(file) {
  selectedFile.value = file
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = URL.createObjectURL(file)
  result.value = null
  selectedHistory.value = null
  errorMessage.value = ''
}

function onFileChange(event) {
  const file = event.target.files?.[0]
  if (file) setFile(file)
}

function onDrop(event) {
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  if (!file.type.startsWith('image/')) {
    errorMessage.value = '请拖入 JPG、PNG、WEBP 或 BMP 图片。'
    return
  }
  setFile(file)
}

function clearFile() {
  selectedFile.value = null
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
  if (fileInput.value) fileInput.value.value = ''
}

async function submitDiagnosis() {
  if (!savedApiConfig.value?.apiKey) {
    apiConfigError.value = '请先填写并保存 API 配置，再开始诊断。'
    activeView.value = 'api'
    return
  }
  if (!selectedFile.value) {
    errorMessage.value = '请先选择一张清晰的叶片照片。'
    return
  }
  if (!form.value.crop) {
    errorMessage.value = '请选择图片中的作物类型。'
    return
  }
  loading.value = true
  errorMessage.value = ''
  selectedHistory.value = null
  const payload = new FormData()
  payload.append('image', selectedFile.value)
  payload.append('client_id', clientId)
  payload.append('crop', form.value.crop)
  if (form.value.symptom.trim()) payload.append('symptom_description', form.value.symptom.trim())
  payload.append('api_provider', savedApiConfig.value.provider)
  payload.append('api_model', savedApiConfig.value.model)
  payload.append('api_key', savedApiConfig.value.apiKey)
  if (savedApiConfig.value.provider === 'custom') {
    payload.append('api_base_url', savedApiConfig.value.baseUrl)
  }
  try {
    result.value = await createDiagnosis(payload)
    await loadHistory(false)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    loading.value = false
  }
}

async function loadHistory(showLoading = true) {
  if (showLoading) historyLoading.value = true
  try {
    const payload = await getHistory(clientId)
    history.value = payload.items
    historyTotal.value = payload.total
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    historyLoading.value = false
  }
}

function showHistory() {
  activeView.value = 'history'
  selectedHistory.value = null
  loadHistory()
}

function openHistory(item) {
  selectedHistory.value = item
  activeView.value = 'diagnose'
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function formatDate(value) {
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function downloadReport() {
  if (!currentReport.value) return
  const report = currentReport.value
  const blob = new Blob([report.report_text], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `诊疗报告_${report.disease_zh}_${report.id}.txt`
  anchor.click()
  URL.revokeObjectURL(url)
}

onMounted(async () => {
  try {
    await getHealth()
    serviceStatus.value = 'ready'
  } catch {
    serviceStatus.value = 'offline'
  }
  try {
    crops.value = await getCrops()
    if (!crops.value.some((crop) => crop.key === form.value.crop)) {
      form.value.crop = crops.value[0]?.key || ''
    }
  } catch (error) {
    errorMessage.value = `无法加载作物列表：${error.message}`
  }
  try {
    providers.value = await getProviders()
  } catch {
    providers.value = FALLBACK_API_PROVIDERS
  }
  if (!providers.value.some((provider) => provider.id === apiForm.value.provider)) {
    apiForm.value.provider = 'deepseek'
  }
  if (!savedApiConfig.value) applyProviderDefaults()
  loadHistory(false)
})

onBeforeUnmount(() => {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<template>
  <div class="app-shell">
    <header class="topbar">
      <button class="brand" type="button" @click="activeView = 'diagnose'">
        <span class="brand-mark" aria-hidden="true">禾</span>
        <span><strong>禾诊</strong><small>智能病虫害诊疗</small></span>
      </button>
      <nav aria-label="主导航">
        <button :class="{ active: activeView === 'diagnose' }" @click="activeView = 'diagnose'">智能诊断</button>
        <button :class="{ active: activeView === 'history' }" @click="showHistory">历史记录</button>
        <button :class="['api-nav-button', { active: activeView === 'api', configured: apiConfigured }]" @click="activeView = 'api'">
          API 配置<span aria-hidden="true"></span>
        </button>
      </nav>
      <span :class="['system-status', serviceStatus]"><i></i>{{ serviceStatus === 'ready' ? '核心服务已连接' : serviceStatus === 'offline' ? '核心服务未连接' : '正在检查服务' }}</span>
    </header>

    <main>
      <section v-if="activeView === 'diagnose'" class="diagnosis-view">
        <div class="hero-copy">
          <p class="eyebrow">MULTIMODAL · RAG · MULTI-API</p>
          <h1>让每一片叶子的异常<br><em>都有迹可循</em></h1>
          <p>上传叶片照片，补充现场症状。系统将融合视觉识别与权威知识，为你生成可追溯的诊疗建议。</p>
          <button class="api-summary" type="button" @click="activeView = 'api'">
            <span :class="{ ready: apiConfigured }"></span>
            {{ apiConfigured ? `${savedProvider?.name || '自定义接口'} · ${savedApiConfig.model}` : '尚未配置诊疗建议 API' }}
          </button>
        </div>

        <div class="workspace-grid">
          <section class="panel upload-panel">
            <div class="panel-heading">
              <span class="step-number">01</span>
              <div><h2>上传叶片照片</h2><p>自然光、对焦清晰，尽量同时包含完整叶片</p></div>
            </div>
            <input ref="fileInput" class="sr-only" type="file" accept="image/jpeg,image/png,image/webp,image/bmp" @change="onFileChange" />
            <button v-if="!previewUrl" class="drop-zone" type="button" @click="chooseFile" @dragover.prevent @drop.prevent="onDrop">
              <span class="camera-icon">⌁</span>
              <strong>选择或拖入叶片照片</strong>
              <small>支持 JPG、PNG、WEBP，最大 10 MB</small>
            </button>
            <div v-else class="image-preview">
              <img :src="previewUrl" alt="待诊断叶片预览" />
              <div class="preview-actions">
                <span>{{ selectedFile?.name }}</span>
                <button type="button" @click="chooseFile">更换</button>
                <button type="button" @click="clearFile">移除</button>
              </div>
            </div>

            <div class="form-grid">
              <label class="field full"><span>确认作物 <b>*</b></span>
                <select v-model="form.crop">
                  <option v-for="crop in crops" :key="crop.key" :value="crop.key">{{ crop.name }}</option>
                </select>
                <small v-if="selectedCropCoverage.length" class="coverage-note">
                  当前知识库覆盖：{{ selectedCropCoverage.map((item) => item.name).join('、') }}
                </small>
              </label>
              <label class="field full"><span>症状补充 <small>选填</small></span>
                <textarea v-model="form.symptom" maxlength="1000" placeholder="例如：下部老叶出现褐色圆斑，边缘有黄色晕圈……"></textarea>
              </label>
            </div>

            <p v-if="errorMessage" class="error-message">{{ errorMessage }}</p>
            <button class="primary-button" type="button" :disabled="loading" @click="submitDiagnosis">
              <span v-if="loading" class="spinner"></span>
              {{ loading ? '正在识别并生成诊疗建议…' : '开始智能诊断' }}
            </button>
            <p class="privacy-note">图片仅用于本次诊断，处理完成后立即从服务器临时目录删除。</p>
          </section>

          <section class="panel result-panel">
            <div class="panel-heading">
              <span class="step-number">02</span>
              <div><h2>诊疗结果</h2><p>视觉识别、现场信息与知识证据综合分析</p></div>
            </div>
            <div v-if="!currentReport && !loading" class="empty-result">
              <span class="leaf-watermark">叶</span>
              <strong>诊疗报告将在这里呈现</strong>
              <p>完成左侧信息后开始诊断</p>
            </div>
            <div v-else-if="loading" class="analysis-state">
              <div class="analysis-rings"><i></i><i></i><i></i></div>
              <strong>正在分析叶片特征</strong>
              <p>随后将检索权威知识并生成建议，请稍候</p>
            </div>
            <article v-else class="report-card">
              <div class="report-topline">
                <span :class="['decision-badge', currentReport.decision]">{{ currentReport.decision === 'accepted' ? '可信识别' : '建议复核' }}</span>
                <span>{{ formatDate(currentReport.created_at) }}</span>
              </div>
              <p class="report-label">最有可能的病症</p>
              <h3>{{ currentReport.disease_zh }}</h3>
              <div class="confidence-row">
                <div><span>模型候选概率</span><strong>{{ currentReport.likelihood_percent.toFixed(2) }}%</strong></div>
                <div class="confidence-track" :style="confidenceStyle"><i></i></div>
              </div>
              <section><h4>综合分析</h4><p>{{ currentReport.advice.summary }}</p></section>
              <section><h4>立即处理</h4><ol><li v-for="item in currentReport.advice.immediate_actions" :key="item">{{ item }}</li></ol></section>
              <div class="report-columns">
                <section><h4>预防建议</h4><ul><li v-for="item in currentReport.advice.prevention" :key="item">{{ item }}</li></ul></section>
                <section><h4>持续观察</h4><ul><li v-for="item in currentReport.advice.monitoring" :key="item">{{ item }}</li></ul></section>
              </div>
              <section class="warning-box"><h4>复核与安全说明</h4><p>{{ currentReport.advice.safety_note }}</p></section>
              <section v-if="currentReport.knowledge_sources.length" class="sources">
                <h4>知识依据</h4>
                <a v-for="source in currentReport.knowledge_sources" :key="source.source_id" :href="source.source_url" target="_blank" rel="noreferrer">{{ source.title }} · {{ source.source_org }}</a>
              </section>
              <button class="secondary-button" type="button" @click="downloadReport">下载诊疗报告</button>
            </article>
          </section>
        </div>
      </section>

      <section v-else-if="activeView === 'history'" class="history-view">
        <div class="history-heading">
          <div><p class="eyebrow">DIAGNOSIS ARCHIVE</p><h1>历史诊断记录</h1><p>当前浏览器共保存 {{ historyTotal }} 次诊断</p></div>
          <button class="secondary-button" @click="loadHistory">刷新记录</button>
        </div>
        <div v-if="historyLoading" class="history-empty">正在读取云端记录…</div>
        <div v-else-if="!history.length" class="history-empty">还没有诊断记录，先上传一张叶片照片吧。</div>
        <div v-else class="history-list">
          <button v-for="item in history" :key="item.id" class="history-item" @click="openHistory(item)">
            <span class="history-date">{{ formatDate(item.created_at) }}</span>
            <span class="history-crop">{{ item.crop_zh }}</span>
            <strong>{{ item.disease_zh }}</strong>
            <span class="history-confidence">{{ item.likelihood_percent.toFixed(2) }}%</span>
            <span :class="['decision-dot', item.decision]"></span>
          </button>
        </div>
      </section>

      <section v-else class="api-config-view">
        <div class="api-config-heading">
          <div>
            <p class="eyebrow">PRIVATE API SESSION</p>
            <h1>配置诊疗建议 API</h1>
            <p>选择厂家或填写自定义兼容接口。密钥仅保存在当前浏览器会话，关闭标签页后自动清除。</p>
          </div>
          <div :class="['api-session-badge', { ready: apiConfigured }]">
            <i></i>
            {{ apiConfigured ? `${savedProvider?.name || '自定义接口'} 已配置` : '当前会话未配置' }}
          </div>
        </div>

        <div class="api-config-layout">
          <section class="panel api-config-panel">
            <div class="panel-heading">
              <span class="step-number">01</span>
              <div><h2>选择接口厂家</h2><p>预设地址来自厂家官方兼容接口，模型名称仍可自行修改</p></div>
            </div>

            <div class="provider-grid">
              <button
                v-for="provider in providers"
                :key="provider.id"
                type="button"
                :class="['provider-card', { active: apiForm.provider === provider.id }]"
                @click="apiForm.provider = provider.id; applyProviderDefaults()"
              >
                <span class="provider-mark">{{ provider.custom ? '+' : provider.name.slice(0, 1) }}</span>
                <span><strong>{{ provider.name }}</strong><small>{{ provider.description }}</small></span>
                <i></i>
              </button>
            </div>

            <div class="api-fields">
              <label class="field full"><span>API 基础地址 <b>*</b></span>
                <input
                  v-model="apiForm.baseUrl"
                  type="url"
                  :readonly="!selectedProvider?.custom"
                  placeholder="https://example.com/v1"
                  autocomplete="off"
                  @input="resetApiTest"
                />
                <small class="coverage-note">
                  {{ selectedProvider?.custom ? '填写到版本路径即可，系统会自动追加 /chat/completions。仅允许公开 HTTPS 地址。' : '预设厂家地址已锁定，避免密钥被发送到错误站点。' }}
                </small>
              </label>
              <div class="actual-api-url">
                <span>实际测试地址</span>
                <code>{{ actualRequestUrl }}</code>
              </div>
              <label class="field full"><span>模型名称 <b>*</b></span>
                <input v-model="apiForm.model" type="text" maxlength="160" placeholder="例如 qwen-plus" autocomplete="off" @input="resetApiTest" />
              </label>
              <label class="field full"><span>API 密钥 <b>*</b></span>
                <div class="secret-input">
                  <input
                    v-model="apiForm.apiKey"
                    :type="showApiKey ? 'text' : 'password'"
                    maxlength="4096"
                    placeholder="在此粘贴厂家提供的 API Key"
                    autocomplete="off"
                    spellcheck="false"
                    @input="resetApiTest"
                  />
                  <button type="button" @click="showApiKey = !showApiKey">{{ showApiKey ? '隐藏' : '显示' }}</button>
                </div>
              </label>
            </div>

            <label v-if="apiTransportIsInsecure" class="transport-warning">
              <input v-model="transportAcknowledged" type="checkbox" />
              <span><strong>当前云端接口使用 HTTP</strong><small>密钥在传输过程中没有 HTTPS 加密。我了解此风险，并只在测试环境中继续使用。</small></span>
            </label>

            <p v-if="apiConfigError" class="error-message">{{ apiConfigError }}</p>
            <p v-if="apiConfigMessage" class="success-message">{{ apiConfigMessage }}</p>
            <div v-if="apiTestResult" class="api-test-result success">
              <span>✓</span>
              <div>
                <strong>API 测试成功</strong>
                <p>{{ apiTestResult.provider }} · {{ apiTestResult.model }} · {{ apiTestResult.latency_ms }} ms</p>
                <code>{{ apiTestResult.request_url }}</code>
              </div>
            </div>
            <div v-if="apiTestError" class="api-test-result failed">
              <span>!</span>
              <div><strong>API 测试失败</strong><p>{{ apiTestError }}</p></div>
            </div>
            <div class="api-actions">
              <button class="secondary-button test-api-button" type="button" :disabled="apiTesting" @click="testApiConfig">
                <span v-if="apiTesting" class="dark-spinner"></span>{{ apiTesting ? '正在测试…' : '测试 API' }}
              </button>
              <button class="primary-button" type="button" @click="saveApiConfig">保存到当前会话</button>
              <button class="secondary-button" type="button" :disabled="!apiConfigured" @click="clearApiConfig">清除配置</button>
            </div>
          </section>

          <aside class="api-security-panel">
            <p class="eyebrow">SECURITY NOTES</p>
            <h2>密钥如何使用</h2>
            <ol>
              <li><span>1</span><div><strong>只存当前会话</strong><p>使用 sessionStorage，不写入项目文件，也不进入诊断历史数据库。</p></div></li>
              <li><span>2</span><div><strong>只在诊断时发送</strong><p>密钥随本次图片诊断提交给后端，用于生成文字建议。</p></div></li>
              <li><span>3</span><div><strong>自定义地址受限</strong><p>只允许公开 HTTPS 地址，后端会阻止本机、内网和云元数据地址。</p></div></li>
            </ol>
            <div class="https-callout">
              <strong>上线前建议</strong>
              <p>为 `170.106.137.89` 配置域名和 HTTPS 后，再输入正式 API 密钥。</p>
            </div>
          </aside>
        </div>
      </section>
    </main>

    <footer><span>禾诊 · 农作物病虫害智能诊疗平台</span><span>辅助筛查结果不能替代农技人员或实验室确诊</span></footer>
  </div>
</template>
