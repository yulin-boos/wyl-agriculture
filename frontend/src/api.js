const DEFAULT_API_BASE = '/api'
const API_BASE = (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE).replace(/\/+$/, '')

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, options)
  let payload = null
  try {
    const responseText = await response.text()
    payload = responseText ? JSON.parse(responseText) : null
  } catch {
    payload = null
  }
  if (!response.ok) {
    if (payload?.detail) throw new Error(payload.detail)
    if (response.status === 502) {
      throw new Error('云端网关暂时无法连接诊断服务，请稍后重试或检查云服务器后端进程。')
    }
    throw new Error(`云端接口请求失败（${response.status}）`)
  }
  return payload
}

export function getCrops() {
  return request('/crops')
}

export function getHealth() {
  return request('/health')
}

export function getProviders() {
  return request('/providers')
}

export function testProviderConnection(formData) {
  return request('/providers/test', { method: 'POST', body: formData })
}

export function createDiagnosis(formData) {
  return request('/diagnoses', { method: 'POST', body: formData })
}

export function getHistory(clientId) {
  const query = new URLSearchParams({ client_id: clientId, limit: '50' })
  return request(`/diagnoses?${query}`)
}
