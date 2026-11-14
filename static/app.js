// Podcast Studio Frontend Application Logic

const state = {
  step: 1,
  currentTab: 'url',
  cacheKey: null,
  transcript: '',
  script: '',
  apiKey: localStorage.getItem('GEMINI_API_KEY') || '',
  selectedFile: null,
  activeModel: 'gemini-2.0-flash',
  availableModels: [],
  hasEnvApiKey: false,
};

// Initialize on DOM load
document.addEventListener('DOMContentLoaded', () => {
  if (window.lucide) {
    window.lucide.createIcons();
  }
  initSystem();
  setupEventListeners();
});

// Setup Initial System Status
async function initSystem() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    
    state.hasEnvApiKey = data.has_env_api_key;
    updateApiKeyBadge();
    updateCacheStats(data.cache_stats);

    // Initial model discovery
    await refreshModels(false);
  } catch (err) {
    console.error('Failed to initialize status:', err);
  }
}

// Update API Key UI Status
function updateApiKeyBadge() {
  const statusText = document.getElementById('api-key-status-text');
  const envKeyText = document.getElementById('env-key-text');
  const inputApiKey = document.getElementById('input-api-key');

  if (state.apiKey) {
    inputApiKey.value = state.apiKey;
    statusText.innerText = 'Key Configured (Custom)';
    statusText.classList.add('text-emerald-400');
  } else if (state.hasEnvApiKey) {
    statusText.innerText = 'Key Configured (Server Env)';
    statusText.classList.add('text-emerald-400');
  } else {
    statusText.innerText = 'Set Gemini Key';
    statusText.classList.remove('text-emerald-400');
  }

  if (state.hasEnvApiKey) {
    envKeyText.innerText = 'Detected GEMINI_API_KEY in server environment.';
  } else {
    envKeyText.innerText = 'No GEMINI_API_KEY detected in server environment. Enter your key above.';
  }
}

// Update Cache Indicator
function updateCacheStats(stats) {
  if (!stats) return;
  const pill = document.getElementById('cache-pill');
  const countEl = document.getElementById('cache-count');
  const sizeEl = document.getElementById('cache-size');
  
  pill.classList.remove('hidden');
  countEl.innerText = stats.total_cached_items || 0;
  sizeEl.innerText = `${stats.total_size_kb || 0} KB`;
}

// Refresh Available Gemini Models
async function refreshModels(force = false) {
  try {
    const res = await fetch('/api/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_key: state.apiKey || undefined,
        force_refresh: force
      })
    });
    const data = await res.json();
    if (data.models && data.models.length > 0) {
      state.availableModels = data.models;
      state.activeModel = data.models[0];
      const modelNameEl = document.getElementById('active-model-name');
      if (modelNameEl) {
        modelNameEl.innerText = state.activeModel;
      }
    }
  } catch (err) {
    console.warn('Failed to refresh models:', err);
  }
}

// Navigation between Stepper Steps
function setStep(stepNum) {
  state.step = stepNum;

  // Update nav headers
  for (let i = 1; i <= 4; i++) {
    const navItem = document.getElementById(`step-nav-${i}`);
    const section = document.getElementById(`step-section-${i}`);
    
    if (i === stepNum) {
      navItem.classList.add('active');
      navItem.classList.remove('completed', 'opacity-50');
      section.classList.remove('hidden');
    } else if (i < stepNum) {
      navItem.classList.add('completed');
      navItem.classList.remove('active', 'opacity-50');
      section.classList.add('hidden');
    } else {
      navItem.classList.remove('active', 'completed');
      navItem.classList.add('opacity-50');
      section.classList.add('hidden');
    }
  }

  window.scrollTo({ top: 0, behavior: 'smooth' });
}

// Setup Event Listeners
function setupEventListeners() {
  // Tab switching in Step 1
  const tabs = ['url', 'upload', 'text'];
  tabs.forEach(tab => {
    const btn = document.getElementById(`tab-btn-${tab}`);
    btn.addEventListener('click', () => {
      state.currentTab = tab;
      tabs.forEach(t => {
        const b = document.getElementById(`tab-btn-${t}`);
        const panel = document.getElementById(`tab-panel-${t}`);
        if (t === tab) {
          b.className = 'tab-btn flex-1 py-3 text-sm font-medium text-indigo-400 border-b-2 border-indigo-500 flex items-center justify-center space-x-2';
          panel.classList.remove('hidden');
        } else {
          b.className = 'tab-btn flex-1 py-3 text-sm font-medium text-gray-400 hover:text-gray-200 border-b-2 border-transparent flex items-center justify-center space-x-2';
          panel.classList.add('hidden');
        }
      });
    });
  });

  // Settings Modal controls
  const settingsModal = document.getElementById('settings-modal');
  document.getElementById('btn-open-settings').addEventListener('click', () => settingsModal.classList.remove('hidden'));
  document.getElementById('btn-close-settings').addEventListener('click', () => settingsModal.classList.add('hidden'));
  document.getElementById('btn-save-settings').addEventListener('click', () => {
    const val = document.getElementById('input-api-key').value.trim();
    state.apiKey = val;
    if (val) {
      localStorage.setItem('GEMINI_API_KEY', val);
    } else {
      localStorage.removeItem('GEMINI_API_KEY');
    }
    updateApiKeyBadge();
    refreshModels(true);
    settingsModal.classList.add('hidden');
  });

  // Clear cache button
  document.getElementById('btn-clear-cache').addEventListener('click', async () => {
    if (confirm('Clear all local disk cache for transcripts and scripts?')) {
      const res = await fetch('/api/cache/clear', { method: 'POST' });
      const data = await res.json();
      alert(`Cleared ${data.cleared_files} cached items.`);
      const statusRes = await fetch('/api/status');
      const statusData = await statusRes.json();
      updateCacheStats(statusData.cache_stats);
    }
  });

  // Refresh models button
  document.getElementById('btn-refresh-models').addEventListener('click', async () => {
    const icon = document.querySelector('#btn-refresh-models i');
    if (icon) icon.classList.add('animate-spin');
    await refreshModels(true);
    if (icon) icon.classList.remove('animate-spin');
    alert(`Active models refreshed dynamically! Selected: ${state.activeModel}`);
  });

  // Text tab live word count
  const pastedInput = document.getElementById('input-pasted-text');
  pastedInput.addEventListener('input', () => {
    const words = pastedInput.value.trim().split(/\s+/).filter(Boolean).length;
    document.getElementById('text-word-counter').innerText = `${words} words`;
    document.getElementById('text-token-estimate').innerText = `~${Math.round(words * 1.3)} estimated tokens`;
  });

  // File dropzone
  const dropzone = document.getElementById('dropzone');
  const fileInput = document.getElementById('file-input');
  dropzone.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', (e) => {
    if (e.target.files && e.target.files[0]) {
      handleSelectedFile(e.target.files[0]);
    }
  });
  dropzone.addEventListener('dragover', (e) => { e.preventDefault(); dropzone.classList.add('border-indigo-500'); });
  dropzone.addEventListener('dragleave', () => dropzone.classList.remove('border-indigo-500'));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzone.classList.remove('border-indigo-500');
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      handleSelectedFile(e.dataTransfer.files[0]);
    }
  });

  // STEP 1 Action: Process URL
  document.getElementById('btn-ingest-url').addEventListener('click', () => processUrl(false));
  document.getElementById('btn-fallback-audio').addEventListener('click', () => processUrl(true, 'extract_audio'));
  document.getElementById('btn-fallback-upload').addEventListener('click', () => {
    document.getElementById('no-captions-alert').classList.add('hidden');
    document.getElementById('tab-btn-upload').click();
  });

  // STEP 1 Action: Upload File
  document.getElementById('btn-upload-file').addEventListener('click', uploadAndTranscribe);

  // STEP 1 Action: Process Text
  document.getElementById('btn-ingest-text').addEventListener('click', processPastedText);

  // STEP 2 Actions
  document.getElementById('btn-back-to-step1').addEventListener('click', () => setStep(1));
  document.getElementById('btn-proceed-to-step3').addEventListener('click', () => {
    state.transcript = document.getElementById('transcript-editor').value.trim();
    setStep(3);
  });

  // Transcript live update in Step 2
  const transcriptEditor = document.getElementById('transcript-editor');
  transcriptEditor.addEventListener('input', () => {
    const words = transcriptEditor.value.trim().split(/\s+/).filter(Boolean).length;
    document.getElementById('transcript-word-count').innerText = words;
    document.getElementById('transcript-token-count').innerText = Math.round(words * 1.3);
  });

  // STEP 3 Actions: Style selector toggle (1 narrator vs 2 hosts)
  const styleSelect = document.getElementById('select-style');
  styleSelect.addEventListener('change', () => {
    const isTwoHost = styleSelect.value === 'two_host';
    const voiceHost2 = document.getElementById('select-voice-host2').parentElement;
    if (isTwoHost) {
      voiceHost2.classList.remove('hidden');
    } else {
      voiceHost2.classList.add('hidden');
    }
  });

  document.getElementById('btn-back-to-step2').addEventListener('click', () => setStep(2));
  document.getElementById('btn-generate-script').addEventListener('click', generateScript);
  document.getElementById('btn-synthesize-audio').addEventListener('click', synthesizeAudio);

  // STEP 4 Actions: Create another
  document.getElementById('btn-create-another').addEventListener('click', () => {
    setStep(1);
  });
}

function handleSelectedFile(file) {
  state.selectedFile = file;
  document.getElementById('file-name-display').innerText = `${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)`;
  document.getElementById('btn-upload-file').removeAttribute('disabled');
}

// Ingest URL (YouTube or Article)
async function processUrl(isFallback = false, actionOverride = null) {
  const urlInput = document.getElementById('input-url');
  const url = urlInput.value.trim();
  if (!url) {
    alert('Please enter a YouTube video link or webpage URL.');
    return;
  }

  const forceRefresh = document.getElementById('check-force-url').checked;
  const loading = document.getElementById('ingest-loading');
  const loadingStatus = document.getElementById('ingest-loading-status');
  const alertBox = document.getElementById('no-captions-alert');

  alertBox.classList.add('hidden');
  loading.classList.remove('hidden');
  loadingStatus.innerText = actionOverride === 'extract_audio' 
    ? 'Downloading public audio track and running local Whisper transcription...' 
    : 'Fetching public captions and inspecting source...';

  try {
    const res = await fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        input_text: url,
        force_refresh: forceRefresh,
        action_override: actionOverride
      })
    });
    const data = await res.json();

    if (!res.ok) {
      throw new Error(data.detail || 'Failed to ingest URL');
    }

    if (data.requires_user_action) {
      loading.classList.add('hidden');
      alertBox.classList.remove('hidden');
      document.getElementById('no-captions-message').innerText = data.message || 'No captions available.';
      return;
    }

    // Success: load into Step 2
    loadTranscriptIntoStep2(data);

  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    loading.classList.add('hidden');
  }
}

// Upload & Transcribe
async function uploadAndTranscribe() {
  if (!state.selectedFile) return;

  const loading = document.getElementById('ingest-loading');
  const loadingStatus = document.getElementById('ingest-loading-status');
  loading.classList.remove('hidden');
  loadingStatus.innerText = `Transcribing ${state.selectedFile.name} locally with faster-whisper...`;

  const modelSize = document.getElementById('select-whisper-model').value;
  const formData = new FormData();
  formData.append('file', state.selectedFile);
  formData.append('model_size', modelSize);

  try {
    const res = await fetch('/api/upload', {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Failed to transcribe file');
    }
    loadTranscriptIntoStep2(data);
  } catch (err) {
    alert(`Transcription Error: ${err.message}`);
  } finally {
    loading.classList.add('hidden');
  }
}

// Process Raw Pasted Text
async function processPastedText() {
  const text = document.getElementById('input-pasted-text').value.trim();
  if (!text) {
    alert('Please paste some text or article notes first.');
    return;
  }

  const loading = document.getElementById('ingest-loading');
  loading.classList.remove('hidden');

  try {
    const res = await fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input_text: text })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Failed to process text');
    loadTranscriptIntoStep2(data);
  } catch (err) {
    alert(`Error: ${err.message}`);
  } finally {
    loading.classList.add('hidden');
  }
}

// Load Transcript to Step 2
function loadTranscriptIntoStep2(data) {
  state.cacheKey = data.cache_key;
  state.transcript = data.transcript;

  document.getElementById('transcript-editor').value = data.transcript;
  document.getElementById('transcript-word-count').innerText = data.word_count || data.transcript.split(/\s+/).length;
  document.getElementById('transcript-token-count').innerText = data.estimated_tokens || Math.round(data.transcript.split(/\s+/).length * 1.3);
  document.getElementById('transcript-privacy-text').innerText = data.privacy_notice || 'Source successfully ingested.';

  const cacheBadge = document.getElementById('transcript-cache-badge');
  if (data.from_cache) {
    cacheBadge.classList.remove('hidden');
  } else {
    cacheBadge.classList.add('hidden');
  }

  setStep(2);
}

// Step 3: Generate Podcast Script with Gemini
async function generateScript() {
  const apiKey = state.apiKey;
  if (!apiKey && !state.hasEnvApiKey) {
    document.getElementById('settings-modal').classList.remove('hidden');
    alert('Please enter your Google Gemini API Key first.');
    return;
  }

  const scriptLoading = document.getElementById('script-loading');
  const scriptContainer = document.getElementById('script-editor-container');
  const btn = document.getElementById('btn-generate-script');

  scriptLoading.classList.remove('hidden');
  btn.classList.add('opacity-50', 'pointer-events-none');

  const style = document.getElementById('select-style').value;
  const duration = document.getElementById('select-duration').value;
  const language = document.getElementById('select-language').value;

  try {
    const res = await fetch('/api/generate-script', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        transcript: state.transcript,
        cache_key: state.cacheKey,
        style: style,
        duration: duration,
        language: language,
        api_key: apiKey || undefined,
        preferred_model: state.activeModel
      })
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Script generation failed');

    // Handle Failover Banner if 429 rate limit occurred
    const failoverBanner = document.getElementById('failover-banner');
    if (data.failover_occurred && data.failover_log && data.failover_log.length > 0) {
      const logs = data.failover_log.map(l => `${l.model} (${l.reason})`).join(', ');
      document.getElementById('failover-banner-text').innerText = 
        `Rate limit auto-handled! Switched to ${data.model_used}. Failovers: ${logs}`;
      failoverBanner.classList.remove('hidden');
    } else {
      failoverBanner.classList.add('hidden');
    }

    state.script = data.script;
    document.getElementById('script-editor').value = data.script;
    document.getElementById('script-words').innerText = data.script_word_count || data.script.split(/\s+/).length;
    document.getElementById('script-audio-est').innerText = `~${data.estimated_audio_minutes || 5} min`;
    document.getElementById('script-model-badge').innerText = data.model_used || state.activeModel;

    scriptContainer.classList.remove('hidden');
    scriptContainer.scrollIntoView({ behavior: 'smooth' });

  } catch (err) {
    alert(`Script Generation Error: ${err.message}`);
  } finally {
    scriptLoading.classList.add('hidden');
    btn.classList.remove('opacity-50', 'pointer-events-none');
  }
}

// Step 3 -> 4: Synthesize Podcast Audio
async function synthesizeAudio() {
  const scriptText = document.getElementById('script-editor').value.trim();
  if (!scriptText) {
    alert('Podcast script is empty. Please generate or enter script dialogue lines first.');
    return;
  }

  const modal = document.getElementById('audio-loading-modal');
  modal.classList.remove('hidden');

  const voiceHost1 = document.getElementById('select-voice-host1').value;
  const voiceHost2 = document.getElementById('select-voice-host2').value;

  try {
    const res = await fetch('/api/synthesize-audio', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        script: scriptText,
        voice_host1: voiceHost1,
        voice_host2: voiceHost2,
        voice_narrator: voiceHost1
      })
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Audio synthesis failed');

    // Load into Step 4
    document.getElementById('stat-segments').innerText = data.total_segments;
    document.getElementById('stat-filesize').innerText = `${data.file_size_mb} MB`;

    const player = document.getElementById('audio-player');
    player.src = data.stream_url;
    
    const downloadBtn = document.getElementById('btn-download-audio');
    downloadBtn.href = data.download_url;

    setStep(4);
    player.play().catch(() => {}); // Autoplay if permitted by browser

  } catch (err) {
    alert(`Audio Synthesis Error: ${err.message}`);
  } finally {
    modal.classList.add('hidden');
  }
}
