// Split from legacy app.js for lower-risk browser-native loading.

// ═══ DOM Helpers ═══

const $ = (id) => document.getElementById(id);

// ═══ Toast Notifications ═══

function showToast(message, type, duration) {
  if (typeof type !== 'string' || !type) type = 'error';
  if (typeof duration !== 'number' || !Number.isFinite(duration) || duration <= 0) duration = 4000;

  const container = document.getElementById('toastContainer');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = 'toast toast-' + type;
  toast.textContent = message;
  container.appendChild(toast);

  const timer = setTimeout(() => {
    toast.classList.add('toast-exit');
    toast.addEventListener('animationend', () => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, { once: true });
    // Fallback removal in case animationend doesn't fire
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 500);
  }, duration);

  // Allow manual dismiss on click
  toast.addEventListener('click', () => {
    clearTimeout(timer);
    toast.classList.add('toast-exit');
    toast.addEventListener('animationend', () => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, { once: true });
    setTimeout(() => {
      if (toast.parentNode) toast.parentNode.removeChild(toast);
    }, 500);
  });
}

// ═══ Custom Modal Dialogs ═══

function showModalDialog(options){
  // options: { title, message, input, inputDefault, placeholder, confirmText, cancelText, type, body }
  // type: 'danger' (red confirm), 'alert' (no cancel)
  // Returns Promise<{ confirmed, value? }>
  return new Promise((resolve)=>{
    const overlay = document.createElement('div');
    overlay.className = 'modalOverlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    if(options.title) overlay.setAttribute('aria-label', options.title);

    const card = document.createElement('div');
    card.className = 'modalCard';

    // Title
    if(options.title){
      const titleEl = document.createElement('div');
      titleEl.className = 'modalTitle';
      titleEl.textContent = options.title;
      card.appendChild(titleEl);
    }

    // Message
    if(options.message){
      const msgEl = document.createElement('div');
      msgEl.className = 'modalMessage';
      msgEl.textContent = options.message;
      card.appendChild(msgEl);
    }

    // Custom body element
    if(options.body) card.appendChild(options.body);

    // Input field
    let inputEl = null;
    if(options.input){
      inputEl = document.createElement('input');
      inputEl.className = 'modalInput';
      inputEl.type = 'text';
      inputEl.value = options.inputDefault || '';
      inputEl.placeholder = options.placeholder || '';
      card.appendChild(inputEl);
    }

    // Actions row
    const actions = document.createElement('div');
    actions.className = 'modalActions';

    function close(result){
      document.removeEventListener('keydown', onKey, true);
      overlay.classList.add('modalExit');
      const timer = setTimeout(()=>{
        if(overlay.parentNode) overlay.parentNode.removeChild(overlay);
      }, 200);
      resolve(result);
    }

    // Confirm button
    if(options.confirmText !== false){
      const confirmBtn = document.createElement('button');
      confirmBtn.type = 'button';
      confirmBtn.className = options.type === 'danger' ? 'btn small' : 'btn small primary';
      confirmBtn.textContent = options.confirmText || '确定';
      if(options.type === 'danger'){
        confirmBtn.style.background = 'rgba(220, 53, 69, 0.8)';
        confirmBtn.style.borderColor = 'rgba(220, 53, 69, 0.45)';
        confirmBtn.style.color = '#fff';
      }
      confirmBtn.addEventListener('click', ()=>{
        close(options.input ? { confirmed: true, value: inputEl.value } : { confirmed: true });
      });
      actions.appendChild(confirmBtn);
    }

    // Cancel button
    if(options.cancelText !== false && options.type !== 'alert'){
      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className = 'btn small';
      cancelBtn.textContent = options.cancelText || '取消';
      cancelBtn.addEventListener('click', ()=> close({ confirmed: false }));
      actions.appendChild(cancelBtn);
    }

    card.appendChild(actions);
    overlay.appendChild(card);
    document.body.appendChild(overlay);

    // Auto-focus
    requestAnimationFrame(()=>{
      if(inputEl){ inputEl.focus(); inputEl.select(); }
      else{
        const firstBtn = actions.querySelector('.btn');
        if(firstBtn) firstBtn.focus();
      }
    });

    // Keyboard — capture phase fires before app.js bubble-phase handler
    function onKey(e){
      if(e.key === 'Escape'){
        e.preventDefault();
        e.stopImmediatePropagation();
        close({ confirmed: false });
        return;
      }
      if(e.key === 'Enter' && options.input && document.activeElement === inputEl){
        e.preventDefault();
        e.stopImmediatePropagation();
        close({ confirmed: true, value: inputEl.value });
        return;
      }
    }
    document.addEventListener('keydown', onKey, true);

    // Click backdrop to close
    overlay.addEventListener('click', (e)=>{
      if(e.target === overlay) close({ confirmed: false });
    });
  });
}

async function showPromptModal(title, message, defaultText = '', placeholder = ''){
  const result = await showModalDialog({
    title,
    message,
    input: true,
    inputDefault: defaultText,
    placeholder,
    confirmText: '确定',
    cancelText: '取消',
  });
  return result.confirmed ? result.value : null;
}

async function showConfirmModal(title, message, confirmText = '确定', cancelText = '取消', options = {}){
  const result = await showModalDialog({
    title,
    message,
    confirmText,
    cancelText,
    type: options.danger ? 'danger' : undefined,
  });
  return result.confirmed;
}

async function showAlertModal(title, message){
  await showModalDialog({
    title,
    message,
    confirmText: '好的',
    cancelText: false,
    type: 'alert',
  });
}

function showPlaylistPickerModal(title, playlists){
  return new Promise((resolve)=>{
    const overlay = document.createElement('div');
    overlay.className = 'modalOverlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', title);

    const card = document.createElement('div');
    card.className = 'modalCard';

    // Title
    const titleEl = document.createElement('div');
    titleEl.className = 'modalTitle';
    titleEl.textContent = title;
    card.appendChild(titleEl);

    // Message
    const msgEl = document.createElement('div');
    msgEl.className = 'modalMessage';
    msgEl.textContent = playlists.length ? '选择一个歌单，或新建歌单' : '暂无歌单，请新建一个';
    card.appendChild(msgEl);

    // Body
    const body = document.createElement('div');
    body.className = 'modalBody';

    if(playlists.length){
      const list = document.createElement('div');
      list.className = 'modalPlaylistList';
      playlists.forEach((pl)=>{
        const item = document.createElement('button');
        item.type = 'button';
        item.className = 'modalPlaylistItem';
        const nameSpan = document.createElement('span');
        nameSpan.className = 'modalPlaylistItemName';
        nameSpan.textContent = pl.name;
        const countSpan = document.createElement('span');
        countSpan.className = 'modalPlaylistItemCount';
        countSpan.textContent = `${pl.tracks.length} 首`;
        item.appendChild(nameSpan);
        item.appendChild(countSpan);
        item.addEventListener('click', ()=> close({ action: 'select', id: pl.id }));
        list.appendChild(item);
      });
      body.appendChild(list);
    }

    // New playlist option
    const newBtn = document.createElement('button');
    newBtn.type = 'button';
    newBtn.className = 'modalPlaylistNewItem';
    newBtn.textContent = '+ 新建歌单…';
    newBtn.addEventListener('click', ()=> close({ action: 'new' }));
    body.appendChild(newBtn);

    card.appendChild(body);

    // Cancel button
    const actions = document.createElement('div');
    actions.className = 'modalActions';
    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.className = 'btn small';
    cancelBtn.textContent = '取消';
    cancelBtn.addEventListener('click', ()=> close(null));
    actions.appendChild(cancelBtn);
    card.appendChild(actions);

    overlay.appendChild(card);
    document.body.appendChild(overlay);

    function close(result){
      document.removeEventListener('keydown', onKey, true);
      overlay.classList.add('modalExit');
      setTimeout(()=>{
        if(overlay.parentNode) overlay.parentNode.removeChild(overlay);
      }, 200);
      resolve(result);
    }

    // Keyboard — capture phase fires before app.js bubble-phase handler
    function onKey(e){
      if(e.key === 'Escape'){
        e.preventDefault();
        e.stopImmediatePropagation();
        close(null);
      }
    }
    document.addEventListener('keydown', onKey, true);

    // Click backdrop to close
    overlay.addEventListener('click', (e)=>{
      if(e.target === overlay) close(null);
    });

    // Focus first interactive element
    requestAnimationFrame(()=>{
      const firstItem = body.querySelector('.modalPlaylistItem, .modalPlaylistNewItem');
      if(firstItem) firstItem.focus();
    });
  });
}

// ═══ Constants ═══

// runtime version is sourced from /api/meta; keep placeholder empty to avoid drift
const APP_VERSION = '';
const APP_VERSION_LOADING = '…';
const PLAYER_UI_MODES = new Set(['idle', 'loading', 'playing', 'paused', 'switching-quality', 'download', 'error']);
const MOBILE_BREAKPOINT = 900;
// Intentional file-scoped global: set from /api/meta, read by app.js for version display
let runtimeVersion = '';
const DOWNLOAD_FORMAT_OPTIONS = [
  { fmt: 5, label: 'MP3 · 320kbps', hint: '标准' },
  { fmt: 6, label: 'FLAC · 1411kbps', hint: '无损' },
  { fmt: 7, label: 'Hi-Res · 24bit/96kHz', hint: '高解析' },
  { fmt: 27, label: 'MAX · 最高可用', hint: '最高' },
];
const MOBILE_DRAWER_SWIPE_CLOSE_THRESHOLD = 88;
const MOBILE_DRAWER_SCROLL_GUARD = 18;
const PLAYLISTS_KEY = 'qdp.web.playlists.v2';
const PLAYLIST_IMPORT_EXPORT_VERSION = 1;
const ARTIST_CACHE_KEY = 'qdp.web.artist-cache.v1';
const ALBUM_CACHE_KEY = 'qdp.web.album-cache.v1';
const STREAM_CACHE_KEY = 'qdp.web.stream-cache.v1';
const VOLUME_KEY = 'qdp.web.volume.v1';
const LAST_NONZERO_VOLUME_KEY = 'qdp.web.last-nonzero-volume.v1';
const MUTED_KEY = 'qdp.web.muted.v1';
const PLAYER_SESSION_KEY = 'qdp.web.player-session.v1';
const REPEAT_KEY = 'qdp.web.repeat.v1';
const REPEAT_MODES = ['off', 'all', 'one'];
const ICONS = { play: 'play', pause: 'pause', volume: 'volume', mute: 'mute', repeat: 'repeat', repeatOne: 'repeatOne' };
const CACHE_TTL_MS = 1000 * 60 * 60 * 6;
const STREAM_STALE_MS = 1000 * 60 * 30;   // stream URLs expire ~1h; refresh after 30min
const STREAM_PREFETCH_MAX_AGE_MS = STREAM_STALE_MS;  // align with staleness threshold to avoid stale-cache gap

// ═══ State ═══

const state = {
  type: 'tracks',
  q: '',
  quality: (function() {
    const raw = Number(localStorage.getItem('qdp.web.quality') || '5');
    const valid = [5, 6, 7, 27];
    return valid.includes(raw) ? raw : 5;
  })(),
  volume: clampVolume(localStorage.getItem(VOLUME_KEY)),
  muted: localStorage.getItem(MUTED_KEY) === '1',
  volumePopoverOpen: false,
  sidebarSections: { queue: true, playlists: false },
  lastNonZeroVolume: (()=>{ const v = clampVolume(localStorage.getItem(LAST_NONZERO_VOLUME_KEY)); return (v > 0) ? v : 1; })(),
  queue: [],
  idx: -1,
  playing: false,
  shuffle: false,
  repeatMode: REPEAT_MODES.includes(localStorage.getItem(REPEAT_KEY)) ? localStorage.getItem(REPEAT_KEY) : 'off',
  history: [],
  currentView: null,
  playlists: loadPlaylists(),
  accounts: [],
  activeAccount: '',
  artistCache: loadCacheMap(ARTIST_CACHE_KEY),
  albumCache: loadCacheMap(ALBUM_CACHE_KEY),
  streamCache: loadCacheMap(STREAM_CACHE_KEY),
  prefetchedStreamIds: new Set(),
  playRequestSeq: 0,
  navRequestSeq: 0,
  navLock: false,
  loadingTrackId: '',
  audioEventGate: '',
  playerUi: { mode: 'idle', detail: '', statusText: '空闲', activeTrackId: '', pendingTrackId: '', reason: '' },
  discoverRandom: { loading: false, seed: '', albums: [], error: '' },
  downloadMenu: { open: false, track: null, anchorRect: null, mobile: false },
  qualitySwitch: { active: false, label: '', token: 0, hideTimer: 0 },
  asyncRequestVersions: { player: 0, 'player-nav': 0, 'download-modal': 0, 'browse-dir': 0, 'download-settings': 0 },
  queueContext: null,
  queueDrag: { fromIndex: -1, overIndex: -1 },
  mobileSidebarOpen: false,
  mobileSidebarTab: 'queue',
  mobileDrawerTouch: {
    tracking: false,
    startY: 0,
    currentY: 0,
    deltaY: 0,
    engaged: false,
    pointerId: null,
  },
  trackSelection: { viewKey: '', selectedKeys: [] },
  searchOffset: 0,
  searchHasMore: false,
};

// Prune stale stream cache entries on startup
(function _pruneStreamCache(){
  const now = Date.now();
  let dirty = false;
  for(const key of Object.keys(state.streamCache)){
    if(now - Number(state.streamCache[key]?.ts || 0) > STREAM_STALE_MS){
      delete state.streamCache[key];
      dirty = true;
    }
  }
  if(dirty) saveCacheMap(STREAM_CACHE_KEY, state.streamCache, true);
})();


// ═══ Volume ═══

function clampVolume(value){
  const num = Number(value);
  if(!Number.isFinite(num)) return 1;
  return Math.max(0, Math.min(1, num));
}
function persistedVolume(){
  return clampVolume(state.muted ? 0 : state.volume);
}
// ═══ LocalStorage ═══

function safeLocalStorageSet(key, value){
  try{ localStorage.setItem(key, value); }catch(_e){}
}
function safeLocalStorageGet(key){
  try{ return localStorage.getItem(key); }catch(_e){ return null; }
}
function safeLocalStorageRemove(key){
  try{ localStorage.removeItem(key); }catch(_e){}
}
function sanitizeFileNamePart(value, fallback = 'track'){
  const text = String(value || '').trim().replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim();
  return text || fallback;
}
function preferredTrackDownloadName(track, fmt = currentQuality()){
  const meta = normTrack(track) || {};
  const base = sanitizeFileNamePart(meta.title || meta.name || 'track');
  const quality = describeQuality(fmt);
  const label = String(quality?.label || '').toLowerCase();
  if(label.includes('flac')) return `${base}.flac`;
  if(label.includes('hi-res') || label.includes('max')) return `${base}.flac`;
  return `${base}.mp3`;
}
// ═══ Player Session ═══

function normalizePersistedTrack(track){
  const meta = normTrack(track);
  if(!meta?.id) return null;
  return {
    id: String(meta.id),
    title: String(meta.title || '—'),
    artist: String(meta.artist || ''),
    image: String(meta.image || ''),
    albumId: meta.albumId || null,
    albumTitle: String(meta.albumTitle || ''),
  };
}
function normalizePersistedQueue(queue){
  return (Array.isArray(queue) ? queue : []).map(normalizePersistedTrack).filter(Boolean);
}
function snapshotPlayerSession(){
  const activeTrack = state.idx >= 0 ? normalizePersistedTrack(state.queue[state.idx]) : null;
  return {
    version: 1,
    queue: normalizePersistedQueue(state.queue),
    idx: Number.isInteger(state.idx) ? state.idx : -1,
    currentTrack: activeTrack,
    queueContext: buildQueueContext(state.queueContext),
    quality: Number(state.quality || currentQuality()),
    volume: clampVolume(state.volume),
    muted: !!state.muted,
    wasPlaying: !!state.playing,
    playerMode: normalizePlayerUiMode(state.playerUi.mode),
    repeatMode: state.repeatMode || 'off',
    ts: Date.now(),
  };
}
let _persistSessionTimer = 0;

function persistPlayerSessionNow(){
  clearTimeout(_persistSessionTimer);
  const queue = normalizePersistedQueue(state.queue);
  if(!queue.length){
    safeLocalStorageRemove(PLAYER_SESSION_KEY);
    return null;
  }
  const payload = snapshotPlayerSession();
  safeLocalStorageSet(PLAYER_SESSION_KEY, JSON.stringify(payload));
  return payload;
}
function persistPlayerSession(){
  clearTimeout(_persistSessionTimer);
  // Write immediately to keep session restore deterministic after explicit queue/state changes.
  persistPlayerSessionNow();
  _persistSessionTimer = setTimeout(persistPlayerSessionNow, 500);
}
let _volumeSessionTimer = 0;
function persistVolumeState(){
  safeLocalStorageSet(VOLUME_KEY, String(clampVolume(state.volume)));
  safeLocalStorageSet(MUTED_KEY, state.muted ? '1' : '0');
  clearTimeout(_volumeSessionTimer);
  _volumeSessionTimer = setTimeout(persistPlayerSession, 500);
}
function setAudioEventGate(kind = ''){
  state.audioEventGate = String(kind || '');
}
function nextAsyncRequestVersion(scope = 'default'){
  const key = String(scope || 'default');
  const current = Number(state.asyncRequestVersions[key] || 0) + 1;
  state.asyncRequestVersions[key] = current;
  return current;
}
function isCurrentAsyncRequestVersion(scope, version){
  const key = String(scope || 'default');
  return Number(version || 0) === Number(state.asyncRequestVersions[key] || 0);
}
function currentAsyncRequestVersion(scope = 'default'){
  const key = String(scope || 'default');
  return Number(state.asyncRequestVersions[key] || 0);
}
function invalidateAsyncRequestVersion(scope = 'default'){
  return nextAsyncRequestVersion(scope);
}
function bumpRequestVersion(scope = 'default'){
  const version = nextAsyncRequestVersion(scope);
  if(String(scope || 'default') === 'player'){
    state.playRequestSeq = version;
  }
  return version;
}
function normalizePathLike(value, fallback = ''){
  const text = String(value || '').trim();
  if(!text) return String(fallback || '');
  return text.replace(/\\+/g, '/').replace(/\/+/g, '/').replace(/\/+$/, '');
}

function buildQueueContext(context = null){
  if(!context) return null;
  const base = {
    sourceType: String(context.sourceType || context.type || 'unknown'),
    sourceLabel: String(context.sourceLabel || context.label || ''),
    activeOccurrenceKey: context.activeOccurrenceKey || context.activeTrackKey || null,
    writablePlaylist: !!context.writablePlaylist,
    playlistId: context.playlistId || '',
  };
  if(base.sourceType === 'local-playlist'){
    base.writablePlaylist = true;
    if(!base.sourceLabel && base.playlistId){
      const playlist = state.playlists.find((pl)=>pl.id === base.playlistId);
      if(playlist) base.sourceLabel = `来自 Playlist · ${playlist.name}`;
    }
  }
  if(!base.sourceLabel){
    if(base.sourceType === 'remote-playlist') base.sourceLabel = '来自 Qobuz Playlist';
    else if(base.sourceType === 'album') base.sourceLabel = '来自 Album';
    else if(base.sourceType === 'artist') base.sourceLabel = '来自 Artist 集合';
    else if(base.sourceType === 'single-track') base.sourceLabel = '单曲队列';
  }
  return base;
}
// ═══ Volume UI ═══

function applyVolumeToAudio(){
  const audio = $('audio');
  if(!audio) return;
  const nextVolume = persistedVolume();
  try{ audio.volume = nextVolume; }catch(_e){}
  audio.muted = state.muted || nextVolume <= 0;
}
function syncVolumeUi(){
  const slider = $('volume');
  const muteBtn = $('mute');
  const muteToggle = $('volumeMuteToggle');
  const pill = $('volumeValue');
  const icon = muteBtn?.querySelector('.icon');
  const percent = Math.round(persistedVolume() * 100);
  if(slider) slider.value = String(percent);
  if(pill) pill.textContent = `${percent}%`;
  if(icon) icon.dataset.icon = state.muted || percent === 0 ? ICONS.mute : ICONS.volume;
  if(muteBtn) muteBtn.classList.toggle('active', state.muted || percent === 0 || state.volumePopoverOpen);
  if(muteToggle){
    muteToggle.textContent = state.muted || percent === 0 ? '取消静音' : '静音';
    muteToggle.classList.toggle('active', state.muted || percent === 0);
  }
}
function setVolume(nextVolume, options = {}){
  const value = clampVolume(nextVolume);
  state.volume = value;
  if(value > 0){
    state.lastNonZeroVolume = value;
    safeLocalStorageSet(LAST_NONZERO_VOLUME_KEY, String(value));
  }
  if(options.syncMuted !== false){
    state.muted = value <= 0 ? true : !!options.forceMuted;
    if(value > 0 && !options.forceMuted) state.muted = false;
  }
  persistVolumeState();
  applyVolumeToAudio();
  syncVolumeUi();
  return value;
}
function toggleMute(){
  if(state.muted || persistedVolume() <= 0){
    state.muted = false;
    setVolume(state.lastNonZeroVolume || 1, { syncMuted: true });
    return false;
  }
  state.muted = true;
  persistVolumeState();
  applyVolumeToAudio();
  syncVolumeUi();
  return true;
}
function isHiResSource(source){
  const spec = trackAudioSpec(source);
  return !!(spec.bitDepth && spec.samplingRate && spec.samplingRate > 48000);
}
// ═══ Sidebar ═══

function syncSidebarSections(){
  const queueToggle = $('queueSectionToggle');
  const playlistsToggle = $('playlistsSectionToggle');
  const queueBody = $('queue');
  const playlistsBody = $('myPlaylists');
  const entries = [
    ['queue', queueToggle, queueBody],
    ['playlists', playlistsToggle, playlistsBody],
  ];
  entries.forEach(([name, toggle, body])=>{
    const expanded = !!state.sidebarSections[name];
    if(toggle){
      toggle.classList.toggle('active', expanded);
      toggle.setAttribute('aria-expanded', String(expanded));
    }
    if(body) body.classList.toggle('collapsed', !expanded);
  });
}
function setSidebarSection(name, expanded){
  if(!(name in state.sidebarSections)) return;
  state.sidebarSections[name] = !!expanded;
  syncSidebarSections();
}
function toggleSidebarSection(name){
  if(!(name in state.sidebarSections)) return;
  setSidebarSection(name, !state.sidebarSections[name]);
}
function setVolumePopoverOpen(open){
  state.volumePopoverOpen = !!open;
  const popover = $('volumePopover');
  if(popover){
    popover.classList.toggle('hidden', !state.volumePopoverOpen);
    popover.classList.toggle('open', state.volumePopoverOpen);
    popover.setAttribute('aria-hidden', String(!state.volumePopoverOpen));
  }
  syncVolumeUi();
}
function toggleVolumePopover(force){
  const next = typeof force === 'boolean' ? force : !state.volumePopoverOpen;
  setVolumePopoverOpen(next);
}
// ═══ Quality ═══

function currentQuality(){
  const selectVal = Number($('qualitySelect')?.value || NaN);
  const val = Number.isFinite(selectVal) ? selectVal : Number(state.quality || 5);
  return Number.isFinite(val) ? val : 5;
}
// ═══ Track Helpers ═══

function trackIdentity(track){
  const t = normTrack(track) || {};
  return String(t.id || '');
}
function trackOccurrenceKey(track, tracks, idx){
  const id = trackIdentity(track);
  let occurrence = 0;
  for(let i = 0; i <= idx; i++){
    if(trackIdentity(tracks[i]) === id) occurrence += 1;
  }
  return `${id}#${occurrence}`;
}
function findTrackIndexByOccurrence(tracks, key){
  if(!key) return -1;
  const [id, nthRaw] = String(key).split('#');
  const nth = Number(nthRaw || 1);
  let occurrence = 0;
  for(let i = 0; i < tracks.length; i++){
    if(trackIdentity(tracks[i]) !== id) continue;
    occurrence += 1;
    if(occurrence === nth) return i;
  }
  return -1;
}
// ═══ Playlist Utilities ═══

function sanitizePlaylistName(name){
  return String(name || '').trim().slice(0, 80);
}
function loadPlaylists(){
  try{
    const raw = JSON.parse(localStorage.getItem(PLAYLISTS_KEY) || 'null');
    if(Array.isArray(raw)) return raw.map(normalizePlaylist).filter(Boolean);
    if(raw && Array.isArray(raw.items)) return raw.items.map(normalizePlaylist).filter(Boolean);
  }catch(_e){}
  // Only try legacy key if primary had no data
  try{
    const legacy = JSON.parse(localStorage.getItem('qdp.web.playlists.v1') || 'null');
    if(Array.isArray(legacy)){
      const migrated = legacy.map(normalizePlaylist).filter(Boolean);
      localStorage.setItem(PLAYLISTS_KEY, JSON.stringify({ version: 1, items: migrated }));
      localStorage.removeItem('qdp.web.playlists.v1');
      return migrated;
    }
  }catch(_e){}
  return [];
}
function savePlaylists(){
  try{
    localStorage.setItem(PLAYLISTS_KEY, JSON.stringify({ version: 1, items: state.playlists }));
  }catch(e){
    if(e.name === 'QuotaExceededError' || (e.code === 22)){
      console.error('localStorage quota exceeded', e);
      if(typeof showToast === 'function') showToast('存储空间不足，播放列表未保存', 'error');
    }
  }
}
function normalizePlaylistTrack(track){
  const t = normTrack(track);
  if(!t || !t.id) return null;
  return t;
}
function normalizePlaylist(pl){
  if(!pl) return null;
  const id = String(pl.id || Date.now());
  const name = sanitizePlaylistName(pl.name) || 'Untitled Playlist';
  const tracks = (Array.isArray(pl.tracks) ? pl.tracks : []).map(normalizePlaylistTrack).filter(Boolean);
  return { id, name, tracks, createdAt: pl.createdAt || Date.now(), updatedAt: pl.updatedAt || Date.now() };
}
function createPlaylistRecord(playlists, name){
  const finalName = sanitizePlaylistName(name);
  if(!finalName) throw new Error('Playlist name required');
  return playlists.concat([{ id: `pl-${Date.now()}-${Math.random().toString(16).slice(2,8)}`, name: finalName, tracks: [], createdAt: Date.now(), updatedAt: Date.now() }]);
}
function renamePlaylistRecord(playlists, id, name){
  const finalName = sanitizePlaylistName(name);
  if(!finalName) throw new Error('Playlist name required');
  return playlists.map((pl)=> pl.id === id ? { ...pl, name: finalName, updatedAt: Date.now() } : pl);
}
function deletePlaylistRecord(playlists, id){
  return playlists.filter((pl)=> pl.id !== id);
}
function addTrackToPlaylistRecord(playlists, playlistId, track){
  const t = normalizePlaylistTrack(track);
  if(!t) throw new Error('Track invalid');
  return playlists.map((pl)=> pl.id === playlistId ? { ...pl, updatedAt: Date.now(), tracks: pl.tracks.concat([t]) } : pl);
}
function removeTrackFromPlaylistRecord(playlists, playlistId, trackIndex){
  return playlists.map((pl)=>{
    if(pl.id !== playlistId) return pl;
    return { ...pl, updatedAt: Date.now(), tracks: pl.tracks.filter((_, i)=>i !== trackIndex) };
  });
}
function reorderPlaylistTracksRecord(playlists, playlistId, fromIndex, toIndex){
  return playlists.map((pl)=>{
    if(pl.id !== playlistId) return pl;
    const tracks = pl.tracks.slice();
    if(fromIndex === toIndex || fromIndex < 0 || toIndex < 0 || fromIndex >= tracks.length || toIndex >= tracks.length) return pl;
    const [moved] = tracks.splice(fromIndex, 1);
    tracks.splice(toIndex, 0, moved);
    return { ...pl, updatedAt: Date.now(), tracks };
  });
}
function uniquePlaylistName(existingNames, requestedName){
  const base = sanitizePlaylistName(requestedName) || 'Imported Playlist';
  if(!existingNames.has(base)) return base;
  let counter = 2;
  let candidate = `${base} (${counter})`;
  while(existingNames.has(candidate)){
    counter += 1;
    candidate = `${base} (${counter})`;
  }
  return candidate;
}
function exportPlaylistsPayload(playlists){
  return {
    version: PLAYLIST_IMPORT_EXPORT_VERSION,
    playlists: (playlists || []).map((pl)=>normalizePlaylist(pl)).filter(Boolean),
  };
}
function mergeImportedPlaylists(currentPlaylists, payload, options = {}){
  const items = Array.isArray(payload) ? payload : (Array.isArray(payload?.playlists) ? payload.playlists : Array.isArray(payload?.items) ? payload.items : []);
  const mode = options.mode || 'merge';
  const existingNames = new Set(currentPlaylists.map((pl)=>pl.name));
  const imported = items.map(normalizePlaylist).filter(Boolean).map((pl)=>{
    let nextName = pl.name;
    if(mode === 'merge') nextName = uniquePlaylistName(existingNames, pl.name);
    existingNames.add(nextName);
    return { ...pl, id: `pl-${Date.now()}-${Math.random().toString(16).slice(2,8)}`, name: nextName, createdAt: pl.createdAt || Date.now(), updatedAt: Date.now() };
  });
  return mode === 'replace' ? imported : currentPlaylists.concat(imported);
}
// ═══ Cache ═══

function loadCacheMap(key){
  try{
    const raw = localStorage.getItem(key) || sessionStorage.getItem(key) || '{}';
    const obj = JSON.parse(raw);
    if(obj && typeof obj === 'object') return obj;
  }catch(_e){}
  return {};
}
function saveCacheMap(key, map, skipSession = false){
  const payload = JSON.stringify(map);
  if(!skipSession){ try{ sessionStorage.setItem(key, payload); }catch(_e){} }
  try{
    localStorage.setItem(key, payload);
  }catch(e){
    if(e.name === 'QuotaExceededError' || (e.code === 22)){
      console.error('localStorage quota exceeded for', key, e);
      if(typeof showToast === 'function') showToast('存储空间不足，缓存未保存', 'error');
    }
  }
}
function getCachedMapValue(map, key){
  const item = map[String(key)];
  if(!item) return null;
  if(Date.now() - Number(item.ts || 0) > CACHE_TTL_MS) return null;
  return item.value;
}
function setCachedMapValue(map, storageKey, key, value){
  map[String(key)] = { ts: Date.now(), value };
  saveCacheMap(storageKey, map, storageKey === STREAM_CACHE_KEY);
  if(storageKey === STREAM_CACHE_KEY) evictStreamCacheIfNeeded();
  return value;
}
function evictStreamCacheIfNeeded(){
  const keys = Object.keys(state.streamCache);
  if(keys.length <= 150) return;
  keys.sort((a, b) => (state.streamCache[a]?.ts || 0) - (state.streamCache[b]?.ts || 0));
  const toRemove = keys.length - 100;
  for(let i = 0; i < toRemove; i++) delete state.streamCache[keys[i]];
  saveCacheMap(STREAM_CACHE_KEY, state.streamCache, true);
}
function streamCacheAge(cacheKey){
  const item = state.streamCache[String(cacheKey)];
  if(!item?.ts) return Infinity;
  return Date.now() - Number(item.ts);
}
// ═══ Cache Management UI ═══

function formatBytes(bytes){
  if(!bytes || bytes <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let size = bytes;
  while(size >= 1024 && i < units.length - 1){ size /= 1024; i++; }
  return `${size.toFixed(1)} ${units[i]}`;
}

async function loadCacheStats(){
  const textEl = $('cacheStatsText');
  if(!textEl) return;
  textEl.textContent = '缓存 …';
  try{
    const res = await api('/api/cache-stats');
    const audio = res?.audio || {};
    const total = res?.total || {};
    const audioStr = formatBytes(audio.size_bytes || 0);
    const totalStr = formatBytes(total.size_bytes || 0);
    const parts = [];
    if(audio.size_bytes > 0) parts.push(`音频 ${audioStr}`);
    parts.push(`共 ${totalStr}`);
    textEl.textContent = parts.join(' · ');
  }catch(_err){
    textEl.textContent = '缓存 读取失败';
  }
}

async function clearCacheByType(type){
  const btnAudio = $('clearCacheAudio');
  const btnAll = $('clearCacheAll');
  const buttons = [btnAudio, btnAll];
  buttons.forEach((b)=>{ if(b) b.disabled = true; });
  const clickedBtn = type === 'all' ? btnAll : btnAudio;
  const origText = clickedBtn?.textContent || '';
  if(clickedBtn) clickedBtn.textContent = '…';
  try{
    // Clear frontend caches for 'all'
    if(type === 'all'){
      state.artistCache = {};
      state.albumCache = {};
      state.streamCache = {};
      state.prefetchedStreamIds.clear();
      clearPendingStreams();
      saveCacheMap(ARTIST_CACHE_KEY, state.artistCache);
      saveCacheMap(ALBUM_CACHE_KEY, state.albumCache);
      saveCacheMap(STREAM_CACHE_KEY, state.streamCache);
    }
    const res = await api('/api/cache-clear', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type }) });
    const freed = formatBytes(res?.cleared_bytes || 0);
    showToast(`已清除 ${freed}`, 'info');
    setPlayerStatus('idle', `缓存已清除 · ${freed}`);
    await loadCacheStats();
  }catch(err){
    showToast('清除缓存失败', 'error');
  }finally{
    buttons.forEach((b)=>{ if(b){ b.disabled = false; } });
    if(clickedBtn) clickedBtn.textContent = origText;
  }
}
// ═══ Format Helpers ═══

function fmtTime(sec){
  sec = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2,'0')}`;
}
function esc(s){
  return String(s || '').replace(/[&<>"']/g, (m)=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[m]));
}
function normalizeSamplingRateValue(value){
  const num = Number(value);
  if(!Number.isFinite(num) || num <= 0) return null;
  return num < 1000 ? Math.round(num * 1000) : Math.round(num);
}
function trackAudioSpec(track){
  const t = track || {};
  const bitDepth = Number(t.bit_depth ?? t.bitDepth ?? t.maximum_bit_depth ?? t.maximumBitDepth);
  const samplingRate = normalizeSamplingRateValue(t.sampling_rate ?? t.samplingRate ?? t.maximum_sampling_rate ?? t.maximumSamplingRate);
  return {
    bitDepth: Number.isFinite(bitDepth) && bitDepth > 0 ? Math.round(bitDepth) : null,
    samplingRate,
  };
}
function formatSamplingRate(hz){
  const value = normalizeSamplingRateValue(hz);
  if(!value) return '';
  const khz = value / 1000;
  const text = Number.isInteger(khz) ? String(khz) : khz.toFixed(1).replace(/\.0$/, '');
  return `${text}kHz`;
}
function formatAudioSpec(track){
  const spec = trackAudioSpec(track);
  if(!spec.bitDepth || !spec.samplingRate) return '';
  return `${spec.bitDepth}B·${formatSamplingRate(spec.samplingRate)}`;
}
function decorateSubtitleWithAudioSpec(subtitle, source){
  const spec = formatAudioSpec(source);
  return spec ? joinMetaParts([subtitle, spec]) : subtitle;
}
function joinMetaParts(parts = []){
  return parts.filter((part)=>String(part || '').trim()).join(' · ');
}
function normTrack(it){
  if(!it) return null;
  const spec = trackAudioSpec(it);
  return {
    id: it.id,
    title: it.title || it.name || '—',
    artist: (typeof it.artist === 'string' ? it.artist : (it.artist||{}).name)
          || (typeof it.performer === 'string' ? it.performer : (it.performer||{}).name)
          || '',
    image: (typeof it.image === 'string' ? it.image : '')
        || ((it.image||{}).large)
        || ((it.image||{}).medium)
        || ((it.album||{}).image||{}).large
        || ((it.album||{}).image||{}).medium
        || ((it.album||{}).image||{}).small
        || '',
    albumId: it.albumId || (it.album && it.album.id) || null,
    albumTitle: it.albumTitle || (it.album && it.album.title) || '',
    bit_depth: spec.bitDepth,
    sampling_rate: spec.samplingRate,
  };
}
// ═══ Navigation ═══

function setPlayIcon(kind){
  const btn = $('play');
  if(!btn) return;
  const icon = btn.querySelector('.icon');
  if(icon) icon.dataset.icon = kind;
}
function setActiveTab(type){
  state.type = type;
  document.querySelectorAll('.tab').forEach((b)=> b.classList.toggle('active', b.dataset.type === type));
}
function setView(renderer){
  state.currentView = renderer;
  const root = $('results');
  if(!root) return;
  root.innerHTML = '';
  renderer(root);
  const backBtn = $('backTop');
  if(backBtn) backBtn.classList.toggle('hidden', state.history.length === 0);
}
function pushView(renderer){
  if(state.currentView) state.history.push(state.currentView);
  setView(renderer);
}
function goBack(){
  const prev = state.history.pop();
  if(prev) setView(prev);
  const backBtn = $('backTop');
  if(backBtn) backBtn.classList.toggle('hidden', state.history.length === 0);
}
function clearHistory(){
  state.history = [];
  state.currentView = null;
  const backBtn = $('backTop');
  if(backBtn) backBtn.classList.add('hidden');
}
// ═══ Card & UI Components ═══

function card(img, title, subtitle, onClick, actions = [], options = {}){
  const el = document.createElement('article');
  const audioSpec = options.audioSpec || '';
  const hiRes = options.hiRes ?? isHiResSource(options.audioSpecSource || options.entity || options.track || null);
  el.className = `card${hiRes ? ' hiResCard' : ''}`;
  el.innerHTML = `
    <img class="cardCover" src="${esc(img)}" alt="" />
    <div class="k cardBody">
      <div class="cardMain">
        <div class="titleStack">
          <div class="t"></div>
          <div class="s"></div>
        </div>
        <div class="cardRight">
          <div class="metaBadges"></div>
          <div class="cardActions"></div>
        </div>
      </div>
    </div>
  `;
  el.querySelector('.cardCover').addEventListener('click', onClick);
  el.querySelector('.t').textContent = title || '—';
  el.querySelector('.t').addEventListener('click', onClick);
  el.querySelector('.s').textContent = subtitle || '';
  const badges = el.querySelector('.metaBadges');
  if(audioSpec){
    const pill = document.createElement('span');
    pill.className = `metaBadge metaBadgeSpec${hiRes ? ' metaBadgeHiRes' : ''}`;
    pill.textContent = audioSpec;
    badges.appendChild(pill);
  }
  (options.badges || []).forEach((label)=>{
    if(!String(label || '').trim()) return;
    const pill = document.createElement('span');
    pill.className = 'metaBadge';
    pill.textContent = label;
    badges.appendChild(pill);
  });
  badges.classList.toggle('hidden', !badges.childElementCount);
  const act = el.querySelector('.cardActions');
  actions.forEach((a) => act.appendChild(a));
  act.classList.toggle('hidden', !actions.length);
  return el;
}
function renderEmpty(msg){
  const root = $('results');
  root.innerHTML = '';
  const d = document.createElement('div');
  d.className = 'empty';
  d.textContent = msg;
  root.appendChild(d);
}
function renderLoadingSkeleton(type = 'cards'){
  const root = $('results');
  root.innerHTML = '';
  const count = type === 'tracks' ? 8 : 12;
  for(let i = 0; i < count; i++){
    const el = document.createElement('div');
    if(type === 'tracks'){
      el.className = 'trackrow';
      el.innerHTML = `
        <span class="n skeleton"></span>
        <span class="skeleton" style="width:28px;height:28px;border-radius:6px;display:inline-block"></span>
        <span class="skeleton" style="width:28px;height:12px"></span>
        <div class="trackTitleWrap" style="gap:8px">
          <span class="skeleton" style="width:${60 + Math.floor(Math.random()*40)}%;height:12px"></span>
        </div>
        <span class="skeleton" style="width:60px;height:12px"></span>
      `;
    }else{
      el.className = 'card';
      el.innerHTML = `
        <span class="skeleton" style="width:52px;height:52px;border-radius:12px;display:inline-block;flex:0 0 auto"></span>
        <div class="cardBody">
          <div class="titleStack">
            <span class="skeleton" style="width:${55 + Math.floor(Math.random()*30)}%;height:14px"></span>
            <span class="skeleton" style="width:${35 + Math.floor(Math.random()*25)}%;height:12px"></span>
          </div>
        </div>
      `;
    }
    root.appendChild(el);
  }
}
function makeBtn(label, onClick, cls='btn small'){
  const b = document.createElement('button');
  b.className = cls;
  b.textContent = label;
  b.addEventListener('click', (e)=>{ e.stopPropagation(); onClick(e); });
  return b;
}
function makeIconButton(iconName, onClick, title=''){
  const b = document.createElement('button');
  b.className = 'btn small iconOnlyBtn';
  b.title = title;
  if(title) b.setAttribute('aria-label', title);
  b.innerHTML = `<span class="icon" data-icon="${iconName}"></span>`;
  b.addEventListener('click', (e)=>{ e.stopPropagation(); try{ const r = onClick(e); if(r && r.catch) r.catch((err)=>console.error('[action-btn]', err)); }catch(err){ console.error('[action-btn]', err); } });
  return b;
}
function makeIconLink(href, title='Download'){
  const a = document.createElement('a');
  a.className = 'btn small iconBtn';
  a.href = href;
  a.title = title;
  a.download = '';
  a.innerHTML = '<span class="icon" data-icon="download"></span>';
  a.addEventListener('click', (e)=>e.stopPropagation());
  return a;
}
// ═══ Queue Context ═══

function describeQuality(fmt){
  return DOWNLOAD_FORMAT_OPTIONS.find((item)=>item.fmt === Number(fmt)) || DOWNLOAD_FORMAT_OPTIONS[0];
}
function queueContextSourceLabel(context = state.queueContext){
  if(!context) return '';
  if(context.sourceType === 'local-playlist'){
    const playlist = state.playlists.find((pl)=>pl.id === context.playlistId);
    return context.sourceLabel || (playlist ? `来自 Playlist · ${playlist.name}` : '来自 Playlist');
  }
  if(context.sourceType === 'remote-playlist') return context.sourceLabel || '来自 Qobuz Playlist';
  if(context.sourceType === 'album') return context.sourceLabel || '来自 Album';
  if(context.sourceType === 'artist') return context.sourceLabel || '来自 Artist 集合';
  if(context.sourceType === 'single-track') return context.sourceLabel || '单曲队列';
  return context.sourceLabel || '';
}
function queuePresentationState(){
  const activeTrack = state.idx >= 0 ? normTrack(state.queue[state.idx]) : null;
  return {
    currentIndex: state.idx,
    currentTrackId: String(activeTrack?.id || ''),
    currentTrackTitle: String(activeTrack?.title || ''),
    queueLength: state.queue.length,
    pendingTrackId: String(state.playerUi.pendingTrackId || state.loadingTrackId || ''),
    dragFromIndex: state.queueDrag.fromIndex,
    dragOverIndex: state.queueDrag.overIndex,
    context: state.queueContext,
  };
}
function getUiFlags(){
  const mode = normalizePlayerUiMode(state.playerUi.mode);
  return {
    mode,
    isLoading: mode === 'loading' || mode === 'switching-quality',
    isPlaying: mode === 'playing',
    isPaused: mode === 'paused',
    isSwitchingQuality: mode === 'switching-quality' || !!state.qualitySwitch.active,
    isQueueDragging: state.queueDrag.fromIndex >= 0,
    isDownloadMenuOpen: !!state.downloadMenu.open,
    queueSourceLabel: queueContextSourceLabel(),
    queueState: queuePresentationState(),
  };
}
// ═══ Player UI ═══

function renderPlayerStatus(){
  const node = $('playerStatus');
  if(node){
    const text = state.playerUi.statusText || '空闲';
    node.textContent = text;
    node.title = text;
  }
  const player = $('player');
  if(player) player.classList.toggle('compactMobile', isMobileLayout());
}
function normalizePlayerUiMode(mode){
  const nextMode = String(mode || 'idle').trim() || 'idle';
  return PLAYER_UI_MODES.has(nextMode) ? nextMode : 'idle';
}
function playerUiSnapshot(){
  return {
    mode: normalizePlayerUiMode(state.playerUi.mode),
    detail: state.playerUi.detail || '',
    reason: state.playerUi.reason || '',
    activeTrackId: String(state.playerUi.activeTrackId || ''),
    pendingTrackId: String(state.playerUi.pendingTrackId || ''),
  };
}
function syncPlayerUiState(){
  state.playerUi.statusText = playerStatusText(state.playerUi.mode, state.playerUi.detail);
  renderPlayerStatus();
  renderQueueDebounced();
}
function transitionPlayerUi(mode, detail = '', extra = {}){
  const nextMode = normalizePlayerUiMode(mode);
  const activeTrack = extra.activeTrack !== undefined ? normTrack(extra.activeTrack) : normTrack(state.queue[state.idx]);
  const pendingTrack = extra.pendingTrack !== undefined ? normTrack(extra.pendingTrack) : null;
  state.playerUi.mode = nextMode;
  state.playerUi.detail = detail || '';
  state.playerUi.reason = extra.reason || '';
  state.playerUi.activeTrackId = String(activeTrack?.id || '');
  state.playerUi.pendingTrackId = String(pendingTrack?.id || extra.pendingTrackId || '');
  state.loadingTrackId = nextMode === 'loading' || nextMode === 'switching-quality'
    ? String(state.playerUi.pendingTrackId || state.playerUi.activeTrackId || '')
    : '';
  syncPlayerUiState();
  persistPlayerSession();
  return playerUiSnapshot();
}
function setPlayerUiState(mode, detail = ''){
  return transitionPlayerUi(mode, detail);
}
function syncAuxiliaryUi(){
  const sourceLabel = queueContextSourceLabel();
  const queueBadge = $('queueSourceBadge');
  const nowPill = $('nowSourcePill');
  if(queueBadge){
    queueBadge.textContent = sourceLabel;
    queueBadge.title = sourceLabel || '';
    queueBadge.classList.toggle('hidden', !sourceLabel);
  }
  if(nowPill){
    const nowLabel = sourceLabel || '手动队列';
    nowPill.textContent = nowLabel;
    nowPill.title = nowLabel;
    nowPill.classList.toggle('hidden', !(sourceLabel || state.queue.length));
  }
}
function buildQueueItemSubtitle(track, idx){
  const parts = [];
  if(track.artist) parts.push(track.artist);
  const audioSpec = formatAudioSpec(track);
  if(audioSpec) parts.push(audioSpec);
  const flags = getUiFlags();
  const queueState = flags.queueState || {};
  if(queueState.pendingTrackId && trackIdentity(state.queue[idx]) === queueState.pendingTrackId){
    parts.push(flags.isSwitchingQuality ? '切换中' : '加载中');
  }else if(flags.isPlaying && queueState.currentIndex === idx){
    parts.push('播放中');
  }else if(flags.isPaused && queueState.currentIndex === idx){
    parts.push('暂停');
  }
  return parts.join(' · ');
}
// ═══ Quality Switch Feedback ═══

function showQualitySwitchFeedback(label){
  const badge = $('qualitySwitchBadge');
  if(!badge) return;
  state.qualitySwitch.active = true;
  state.qualitySwitch.label = label;
  state.qualitySwitch.token += 1;
  const token = state.qualitySwitch.token;
  badge.textContent = `切换到 ${label}…`;
  badge.classList.remove('hidden');
  if(state.qualitySwitch.hideTimer) clearTimeout(state.qualitySwitch.hideTimer);
  state.qualitySwitch.hideTimer = window.setTimeout(()=>{
    if(token !== state.qualitySwitch.token) return;
    state.qualitySwitch.active = false;
    badge.classList.add('hidden');
  }, 1600);
}
function hideQualitySwitchFeedback(force = false){
  const badge = $('qualitySwitchBadge');
  if(!badge) return;
  state.qualitySwitch.active = false;
  if(force) state.qualitySwitch.token += 1;
  if(state.qualitySwitch.hideTimer) clearTimeout(state.qualitySwitch.hideTimer);
  state.qualitySwitch.hideTimer = window.setTimeout(()=>badge.classList.add('hidden'), force ? 0 : 380);
}
// ═══ Download ═══

// --- Download modal state ---
let _downloadModalState = {
  open: false,
  track: null,
  selectedFmt: 0,
  defaultPath: '',
  loading: false,
};
let _browseDirState = {
  currentPath: '',
  parentPath: null,
};

// Stub for backward compatibility (test hooks reference this)
function queueDownloadHref(track, fmt = currentQuality()){
  const id = encodeURIComponent(track?.id || '');
  return `/api/download?id=${id}&fmt=${fmt}`;
}

function closeDownloadMenu(){
  state.downloadMenu = { open: false, track: null, anchorRect: null, mobile: false };
  syncAuxiliaryUi();
  const menu = $('downloadMenu');
  if(menu){
    menu.classList.add('hidden');
    menu.classList.remove('open');
    menu.classList.remove('mobileSheet');
    menu.setAttribute('aria-hidden', 'true');
  }
  const card = $('downloadMenuCard');
  if(card){
    card.innerHTML = '';
    card.removeAttribute('style');
  }
  // Also close the new download modal if open
  closeDownloadModal();
}

// ─── New Download Modal (server-side tagged download) ───

async function fetchDefaultDownloadPath(){
  try{
    const res = await api('/api/download-settings');
    return res?.default_path || '';
  }catch(_err){
    return '';
  }
}

function closeDownloadModal(){
  _downloadModalState.open = false;
  _downloadModalState.loading = false;
  const modal = $('downloadModal');
  if(modal){
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
  }
}

function openDownloadModal(track, _anchor){
  if(!track?.id) return Promise.resolve();
  const t = normTrack(track);
  if(!t) return Promise.resolve();

  closeDownloadMenu();
  state.downloadMenu.open = false;

  const requestVersion = bumpRequestVersion('download-modal');
  _downloadModalState.open = true;
  _downloadModalState.track = t;
  _downloadModalState.selectedFmt = currentQuality();
  _downloadModalState.loading = false;
  _downloadModalState.requestVersion = requestVersion;
  _downloadModalState.defaultPath = _downloadModalState.defaultPath || '';

  return fetchDefaultDownloadPath().then((defaultPath)=>{
    if(!isCurrentAsyncRequestVersion('download-modal', requestVersion)) return;
    if(defaultPath) _downloadModalState.defaultPath = defaultPath;

    const modal = $('downloadModal');
    if(!modal) return;
    modal.classList.remove('hidden');
    modal.setAttribute('aria-hidden', 'false');

    const trackNameEl = $('downloadModalTrackName');
    if(trackNameEl){
      const bulkCount = _downloadModalState._pendingBulkTracks?.length;
      if(bulkCount && bulkCount > 1){
        trackNameEl.textContent = `${_downloadModalState._pendingBulkTitle || '专辑'} · ${bulkCount} 首`;
      }else{
        trackNameEl.textContent = t.title || '当前歌曲';
      }
    }

    const qualityBtns = $('downloadModalQualityBtns');
    if(qualityBtns){
      qualityBtns.innerHTML = '';
      DOWNLOAD_FORMAT_OPTIONS.forEach((item) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `downloadModalQualityBtn${_downloadModalState.selectedFmt === item.fmt ? ' active' : ''}`;
        btn.textContent = item.hint || item.label;
        btn.dataset.fmt = String(item.fmt);
        btn.addEventListener('click', () => {
          _downloadModalState.selectedFmt = item.fmt;
          qualityBtns.querySelectorAll('.downloadModalQualityBtn').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
        });
        qualityBtns.appendChild(btn);
      });
    }

    const pathInput = $('downloadModalPathText');
    if(pathInput) pathInput.value = _downloadModalState.defaultPath;

    const setDefaultCheckbox = $('downloadModalSetDefault');
    if(setDefaultCheckbox) setDefaultCheckbox.checked = false;
  });
}

async function confirmDownloadModal(){
  if(_downloadModalState.loading) return;
  const t = _downloadModalState.track;
  if(!t?.id) return;

  const pathInput = $('downloadModalPathText');
  const downloadPath = pathInput?.value?.trim() || _downloadModalState.defaultPath;
  const fmt = _downloadModalState.selectedFmt;
  const setDefault = $('downloadModalSetDefault')?.checked || false;
  const workersInput = $('downloadModalWorkers');
  const workers = Math.max(1, Number(workersInput?.value || _downloadModalState.workers || 4) || 4);
  _downloadModalState.workers = workers;

  if(!downloadPath){
    showToast('请选择下载路径', 'error');
    return;
  }

  // Save as default if checkbox checked
  if(setDefault){
    try{
      await api('/api/download-settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ default_path: downloadPath, workers }),
      });
      _downloadModalState.defaultPath = downloadPath;
      _downloadModalState.workers = workers;
    }catch(_err){
      console.warn('Failed to save default download path', _err);
    }
  }

  // Check if this is a bulk album download
  const bulkTracks = _downloadModalState._pendingBulkTracks;
  const bulkTitle = _downloadModalState._pendingBulkTitle;
  const bulkAlbumId = _downloadModalState._pendingBulkAlbumId;
  const bulkType = _downloadModalState._pendingBulkType || 'album';
  _downloadModalState._pendingBulkTracks = null;
  _downloadModalState._pendingBulkTitle = null;
  _downloadModalState._pendingBulkAlbumId = null;
  _downloadModalState._pendingBulkType = null;

  const embed = $('downloadModalEmbedCover')?.checked !== false ? '1' : '0';

  if(bulkTracks && bulkTracks.length > 1){
    closeDownloadModal();
    if(bulkType === 'playlist'){
      const p = encodeURIComponent(downloadPath);
      api(`/api/download-tagged?id=local-playlist&fmt=${fmt}&path=${p}&embed=${embed}&type=playlist&workers=${workers}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: bulkTitle || '歌单', tracks: bulkTracks }),
        timeout: 1800000,
      })
        .then((res) => {
          const savedPath = res?.path || downloadPath;
          showToast(`${bulkTitle || '歌单'}已保存至: ${savedPath}`, 'success', 5000);
          setPlayerStatus('download', `${bulkTitle || '歌单'} · ${bulkTracks.length} 首`, { reason: 'playlist-download' });
        })
        .catch((err) => {
          showToast(`下载失败: ${err?.message || '未知错误'}`, 'error');
        });
      return;
    }
    if(bulkAlbumId){
      triggerBulkAlbumDownload(bulkAlbumId, bulkTracks, fmt, downloadPath, embed, bulkTitle, workers);
    }else{
      triggerBulkAlbumDownload('', bulkTracks, fmt, downloadPath, embed, bulkTitle, workers);
    }
    setPlayerStatus('download', `${bulkTitle || '批量下载'} · ${bulkTracks.length} 首`, { reason: 'album-download' });
    return;
  }

  _downloadModalState.loading = true;
  const confirmBtn = $('downloadModalConfirmBtn');
  if(confirmBtn){
    confirmBtn.disabled = true;
    confirmBtn.textContent = '下载中…';
  }

  try{
    const id = encodeURIComponent(t.id);
    const path = encodeURIComponent(downloadPath);
    const res = await api(`/api/download-tagged?id=${id}&fmt=${fmt}&path=${path}&embed=${embed}&workers=${workers}`, { timeout: 600000 });

    const savedPath = res?.path || downloadPath;
    showToast(`文件已保存至: ${savedPath}`, 'success', 5000);
    setPlayerStatus('download', `${t.title || '当前歌曲'} · ${describeQuality(fmt).label}`);

    closeDownloadModal();
  }catch(err){
    showToast(`下载失败: ${err?.message || '未知错误'}`, 'error');
  }finally{
    _downloadModalState.loading = false;
    if(confirmBtn){
      confirmBtn.disabled = false;
      confirmBtn.textContent = '下载';
    }
  }
}

function cancelDownloadModal(){
  closeDownloadModal();
}

// ─── Browse Directory Sub-dialog ───

function closeBrowseDirModal(){
  const modal = $('browseDirModal');
  if(modal){
    modal.classList.add('hidden');
    modal.setAttribute('aria-hidden', 'true');
  }
}

async function openBrowseDirModal(startPath){
  const modal = $('browseDirModal');
  if(!modal) return;
  modal.classList.remove('hidden');
  modal.setAttribute('aria-hidden', 'false');
  await loadBrowseDir(startPath || _browseDirState.currentPath || _downloadModalState.defaultPath || '');
}

async function loadBrowseDir(dirPath){
  const listEl = $('browseDirList');
  const pathEl = $('browseDirCurrentPath');
  if(!listEl) return;

  const requestVersion = bumpRequestVersion('browse-dir');
  listEl.innerHTML = '<div style="padding:12px;color:var(--muted)">加载中…</div>';

  try{
    const p = encodeURIComponent(dirPath || '');
    const res = await api(`/api/browse-dirs?path=${p}`);
    if(!isCurrentAsyncRequestVersion('browse-dir', requestVersion)) return;
    const currentPath = res?.path || dirPath || '';
    const parent = res?.parent || null;
    const dirs = res?.dirs || [];

    _browseDirState.currentPath = currentPath;
    _browseDirState.parentPath = parent;

    if(pathEl) pathEl.textContent = currentPath;
    listEl.innerHTML = '';

    // Parent button
    if(parent){
      const parentItem = document.createElement('button');
      parentItem.type = 'button';
      parentItem.className = 'browseDirItem parent';
      parentItem.innerHTML = '<span class="browseDirItemIcon">⋯</span><span class="browseDirItemName">..</span>';
      parentItem.addEventListener('click', () => loadBrowseDir(parent));
      listEl.appendChild(parentItem);
    }

    // Directories
    dirs.forEach((dir) => {
      const item = document.createElement('button');
      item.type = 'button';
      item.className = 'browseDirItem';
      item.innerHTML = `<span class="browseDirItemIcon">📁</span><span class="browseDirItemName">${esc(dir.name)}</span>`;
      item.addEventListener('click', () => loadBrowseDir(dir.path));
      listEl.appendChild(item);
    });

    if(!dirs.length && !parent){
      listEl.innerHTML = '<div style="padding:12px;color:var(--muted)">空目录</div>';
    }
  }catch(err){
    if(!isCurrentAsyncRequestVersion('browse-dir', requestVersion)) return;
    listEl.innerHTML = `<div style="padding:12px;color:var(--muted)">读取失败: ${esc(err?.message || '')}</div>`;
  }
}

function confirmBrowseDir(){
  const pathInput = $('downloadModalPathText');
  if(pathInput) pathInput.value = _browseDirState.currentPath;
  closeBrowseDirModal();
}

function cancelBrowseDir(){
  closeBrowseDirModal();
}

// ─── Download link builders (used by other modules) ───

function positionDownloadMenu(_rect){ /* legacy: no-op, replaced by centered modal */ }
function buildDownloadMenuContent(_track, _mobile){ /* legacy: no-op, replaced by modal */ }

function openDownloadMenu(track, anchor){
  openDownloadModal(track, anchor);
}

function makeAlbumDownloadLink(album, title='Download album'){
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn small iconBtn';
  btn.title = title;
  btn.innerHTML = '<span class="icon" data-icon="download"></span>';
  btn.addEventListener('click', async (e)=>{
    e.stopPropagation();
    const albumId = album?.albumId || album?.id;
    if(!albumId) return;
    // Store album tracks for bulk download, then open modal to pick quality + path
    try{
      const full = album?.tracks ? album : await fetchAlbum(albumId);
      const tracks = (full?.tracks || []).map(normTrack).filter((track)=>track?.id);
      if(!tracks.length) return;
      _downloadModalState._pendingBulkTracks = tracks;
      _downloadModalState._pendingBulkTitle = full?.title || album?.title || '专辑';
      _downloadModalState._pendingBulkAlbumId = albumId;
      openDownloadModal(tracks[0], btn);
    }catch(err){
      console.error('album download failed', err);
    }
  });
  return btn;
}

function makeTrackDownloadLink(track, title='Download'){
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'btn small iconBtn';
  btn.title = title;
  btn.innerHTML = '<span class="icon" data-icon="download"></span>';
  btn.addEventListener('click', (e)=>{
    e.stopPropagation();
    openDownloadModal(track, btn);
  });
  return btn;
}

function triggerTrackDownload(track, fmt = currentQuality()){
  // Tagged server-side download (replaces legacy 302 redirect)
  const t = normTrack(track);
  const id = encodeURIComponent(track?.id || t?.id || '');
  if(!id) return;
  const downloadPath = _downloadModalState.defaultPath || '';
  if(!downloadPath){
    showToast('请先设置下载路径', 'error');
    openDownloadModal(track);
    return;
  }
  const path = encodeURIComponent(downloadPath);
  const embed = $('downloadModalEmbedCover')?.checked !== false ? '1' : '0';
  api(`/api/download-tagged?id=${id}&fmt=${fmt}&path=${path}&embed=${embed}`, { timeout: 600000 })
    .then((res) => {
      const savedPath = res?.path || downloadPath;
      showToast(`文件已保存至: ${savedPath}`, 'success', 5000);
      setPlayerStatus('download', `${t?.title || '当前歌曲'} · ${describeQuality(fmt).label}`);
    })
    .catch((err) => {
      showToast(`下载失败: ${err?.message || '未知错误'}`, 'error');
    });
}
// ═══ Track Selection ═══

function buildSelectionKey(track, index){
  return `${trackIdentity(track)}#${index}`;
}
function resetTrackSelection(viewKey = ''){
  state.trackSelection = { viewKey: String(viewKey || ''), selectedKeys: [] };
}
function ensureTrackSelectionView(viewKey = ''){
  const key = String(viewKey || '');
  if(state.trackSelection.viewKey !== key) resetTrackSelection(key);
}
function isTrackSelected(viewKey, track, index){
  ensureTrackSelectionView(viewKey);
  return state.trackSelection.selectedKeys.includes(buildSelectionKey(track, index));
}
function toggleTrackSelection(viewKey, track, index, checked){
  ensureTrackSelectionView(viewKey);
  const key = buildSelectionKey(track, index);
  const selected = new Set(state.trackSelection.selectedKeys);
  if(checked) selected.add(key);
  else selected.delete(key);
  state.trackSelection.selectedKeys = Array.from(selected);
}
function selectedTracksForView(viewKey, tracks){
  ensureTrackSelectionView(viewKey);
  const keys = new Set(state.trackSelection.selectedKeys);
  return (Array.isArray(tracks) ? tracks : []).filter((track, index)=>keys.has(buildSelectionKey(track, index)));
}
function selectAllTracks(viewKey, tracks){
  ensureTrackSelectionView(viewKey);
  state.trackSelection.selectedKeys = (Array.isArray(tracks) ? tracks : []).map((track, index)=>buildSelectionKey(track, index));
}
function clearSelectedTracks(viewKey){
  ensureTrackSelectionView(viewKey);
  state.trackSelection.selectedKeys = [];
}
// ═══ Bulk Download ═══

function triggerBulkAlbumDownload(albumId, tracks, fmt = currentQuality(), downloadPath = '', embed = '1', title = ''){
  const normalized = (Array.isArray(tracks) ? tracks : []).map(normTrack).filter((track)=>track?.id);
  if(!normalized.length) return;
  const path = downloadPath || _downloadModalState.defaultPath || '';
  if(!path){
    showToast('请先设置下载路径', 'error');
    return;
  }
  const effectiveAlbumId = albumId || normalized[0]?.albumId || '';
  if(effectiveAlbumId){
    // Single album download using download_release
    const id = encodeURIComponent(effectiveAlbumId);
    const p = encodeURIComponent(path);
    api(`/api/download-tagged?id=${id}&fmt=${fmt}&path=${p}&embed=${embed}&type=album&album_id=${id}`, { timeout: 600000 })
      .then((res) => {
        const savedPath = res?.path || path;
        const label = title || '专辑';
        showToast(`${label}已保存至: ${savedPath}`, 'success', 5000);
        setPlayerStatus('download', `${label} · ${describeQuality(fmt).label}`);
      })
      .catch((err) => {
        showToast(`下载失败: ${err?.message || '未知错误'}`, 'error');
      });
  }else{
    // Fallback: sequential track downloads
    const delayMs = Math.max(100, Math.round(900 / effectiveWorkers));
  normalized.forEach((track, index) => window.setTimeout(() => triggerTrackDownload(track, fmt, effectiveWorkers), index * delayMs));
  }
  return normalized.length;
}

function triggerBulkDownload(tracks, fmt = currentQuality()){
  const normalized = (Array.isArray(tracks) ? tracks : []).map(normTrack).filter((track)=>track?.id);
  if(!normalized.length) return 0;
  // Always route through modal for explicit path/quality confirmation
  _downloadModalState._pendingBulkTracks = normalized;
  _downloadModalState._pendingBulkTitle = '批量下载';
  _downloadModalState._pendingBulkAlbumId = null;
  openDownloadModal(normalized[0]);
  return normalized.length;
}
// ═══ Track List View ═══

function buildTrackListViewKey(options = {}, title = ''){
  return String(options.viewKey || [options.source || options.sourceType || 'tracks', options.playlistId || '', title || ''].filter(Boolean).join(':') || `tracks:${title || 'detail'}`);
}
function buildTrackListSubtitle(subtitle, options = {}, tracks = []){
  const parts = [subtitle];
  if(options.showTrackCount !== false && Array.isArray(tracks) && tracks.length) parts.push(`${tracks.length} 首`);
  if(!options.skipAudioSpec){
    const spec = options.audioSpec || formatAudioSpec(options.audioSpecSource || tracks.find((track)=>formatAudioSpec(track)) || null);
    if(spec) parts.push(spec);
  }
  return joinMetaParts(parts);
}
function renderTrackBulkBar(container, viewKey, tracks, onChange){
  const selected = selectedTracksForView(viewKey, tracks);
  const bar = document.createElement('div');
  bar.className = 'bulkBar';
  bar.innerHTML = `
    <label class="bulkSelectAll checkWrap"><input type="checkbox" class="bulkToggleAll checkInput" /> <span class="checkMark" aria-hidden="true"></span><span>全选</span></label>
    <div class="bulkSummary">已选 <strong class="bulkCount">0</strong> 首</div>
    <div class="bulkActions">
      <button type="button" class="btn small bulkDownloadBtn">批量下载</button>
      <button type="button" class="btn small bulkAddBtn">批量加入 Playlist</button>
      <button type="button" class="btn small bulkClearBtn">清空选择</button>
    </div>
  `;
  const countNode = bar.querySelector('.bulkCount');
  const allBox = bar.querySelector('.bulkToggleAll');
  const sync = ()=>{
    const items = selectedTracksForView(viewKey, tracks);
    countNode.textContent = String(items.length);
    allBox.checked = !!tracks.length && items.length === tracks.length;
    allBox.indeterminate = items.length > 0 && items.length < tracks.length;
    bar.classList.toggle('hasSelection', items.length > 0);
    onChange?.(items);
  };
  allBox.addEventListener('change', ()=>{
    if(allBox.checked) selectAllTracks(viewKey, tracks);
    else clearSelectedTracks(viewKey);
    sync();
  });
  bar.querySelector('.bulkDownloadBtn').addEventListener('click', ()=>{
    const items = selectedTracksForView(viewKey, tracks);
    if(!items.length) return;
    triggerBulkDownload(items);
  });
  bar.querySelector('.bulkAddBtn').addEventListener('click', ()=>{
    const items = selectedTracksForView(viewKey, tracks);
    if(!items.length) return;
    choosePlaylistForTracks(items);
  });
  bar.querySelector('.bulkClearBtn').addEventListener('click', ()=>{
    clearSelectedTracks(viewKey);
    sync();
  });
  sync();
  return { bar, sync };
}

// ═══ Media Session ═══

function updateMediaSession(meta, audio){
  if(!('mediaSession' in navigator)) return;
  const t = normTrack(meta) || {};
  const artwork = [];
  if(t.image){
    artwork.push({ src: t.image, sizes: '512x512', type: 'image/jpeg' });
  }
  if(t.album_image && t.album_image !== t.image){
    artwork.push({ src: t.album_image, sizes: '512x512', type: 'image/jpeg' });
  }
  if(!artwork.length){
    artwork.push({ src: '', sizes: '512x512', type: 'image/jpeg' });
  }
  navigator.mediaSession.metadata = new MediaMetadata({
    title: t.title || '—',
    artist: t.artist || '',
    album: t.albumTitle || '',
    artwork,
  });
  if(audio && audio.duration && isFinite(audio.duration)){
    try{
      navigator.mediaSession.setPositionState({
        duration: audio.duration,
        playbackRate: 1.0,
        position: Math.min(audio.currentTime || 0, audio.duration),
      });
    }catch(_e){}
  }
}
function bindMediaSessionHandlers(){
  if(!('mediaSession' in navigator)) return;
  const actions = {
    play: ()=>togglePlay(),
    pause: ()=>togglePlay(),
    previoustrack: ()=>prev(),
    nexttrack: ()=>next(),
    seekto: (details)=>{
      const audio = $('audio');
      if(audio && details.seekTime !== undefined){
        audio.currentTime = details.seekTime;
      }
    },
  };
  for(const [action, handler] of Object.entries(actions)){
    try{ navigator.mediaSession.setActionHandler(action, handler); }catch(_e){}
  }
}
function updateMediaSessionPlaybackState(playing){
  if(!('mediaSession' in navigator)) return;
  try{
    navigator.mediaSession.playbackState = playing ? 'playing' : 'paused';
  }catch(_e){}
}

