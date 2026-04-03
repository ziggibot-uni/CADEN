const BASE = 'http://localhost:8000/api';

async function request(path: string, options: RequestInit = {}): Promise<unknown> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers as Record<string, string> || {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  return res.json();
}

// Status & AI
export function fetchStatus() {
  return request('/status');
}

export function sendChat(message: string, model?: string) {
  return request('/chat', {
    method: 'POST',
    body: JSON.stringify({ message, model }),
  });
}

export function getAIModels() {
  return request('/ai/models');
}

// Audio
export function getAudioDevices() {
  return request('/audio/devices');
}

export function configureAudio(config: { input_device: string; output_device: string; buffer_size: number }) {
  return request('/audio/configure', {
    method: 'POST',
    body: JSON.stringify(config),
  });
}

export function startAudio() {
  return request('/audio/start', { method: 'POST' });
}

export function stopAudio() {
  return request('/audio/stop', { method: 'POST' });
}

export function getAudioStatus() {
  return request('/audio/status');
}

export function toggleBypass(enabled: boolean) {
  return request(`/audio/bypass?enabled=${enabled}`, { method: 'POST' });
}

// Knobs
export function updateKnob(stageIndex: number, paramName: string, value: number) {
  return request('/knob', {
    method: 'POST',
    body: JSON.stringify({ stage_index: stageIndex, param_name: paramName, value }),
  });
}

// Inventory
export function getInventory(type?: string, search?: string) {
  const params = new URLSearchParams();
  if (type) params.set('type', type);
  if (search) params.set('search', search);
  const qs = params.toString();
  return request(`/inventory${qs ? '?' + qs : ''}`);
}

export function addInventoryItem(item: Record<string, unknown>) {
  return request('/inventory', { method: 'POST', body: JSON.stringify(item) });
}

export function updateInventoryItem(id: string, updates: Record<string, unknown>) {
  return request(`/inventory/${id}`, { method: 'PUT', body: JSON.stringify(updates) });
}

export function deleteInventoryItem(id: string) {
  return request(`/inventory/${id}`, { method: 'DELETE' });
}

export function adjustQuantity(id: string, delta: number) {
  return request(`/inventory/${id}/quantity?delta=${delta}`, { method: 'PATCH' });
}

// Keepers
export function getKeepers() {
  return request('/keepers');
}

export function saveKeeper(keeper: { name: string }) {
  return request('/keepers', { method: 'POST', body: JSON.stringify(keeper) });
}

export function loadKeeper(id: string) {
  return request(`/keepers/${id}/load`, { method: 'POST' });
}

export function deleteKeeper(id: string) {
  return request(`/keepers/${id}`, { method: 'DELETE' });
}

// Design
export function getCurrentDesign() {
  return request('/design');
}

export function getNetlist() {
  return request('/design/netlist');
}
