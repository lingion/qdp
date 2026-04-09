// Split from legacy app.js for lower-risk browser-native loading.

const $ = (id) => document.getElementById(id);

// runtime version is sourced from /api/meta; keep placeholder empty to avoid drift
const APP_VERSION = '';
const APP_VERSION_LOADING = '…';
const PLAYER_UI_MODES = new Set(['idle', 'loading', 'playing', 'paused', 'switching-quality', 'download', 'error']);
const MOBILE_BREAKPOINT = 900;
let runtimeVersion = '';
const DOWNLOAD_FORMAT_OPTIONS = [
  { fmt: 5, label: 'MP3', hint: '标准音质' },
  { fmt: 6, label: 'FLAC', hint: '无损' },
  { fmt: 7, label: 'Hi-Res 96k', hint: '高解析度' },
  { fmt: 27, label: 'MAX', hint: '最高可用' },
];
const MOBILE_DRAWER_SWIPE_CLOSE_THRESHOLD = 88;
const MOBILE_DRAWER_SCROLL_GUARD = 18;
const PLAYLISTS_KEY = 'qdp.web.playlists.v2';
const PLAYLIST_IMPORT_EXPORT_VERSION = 1;
const ARTIST_CACHE_KEY = 'qdp.web.artist-cache.v1';
const ALBUM_CACHE_KEY = 'qdp.web.album-cache.v1';
const STREAM_CACHE_KEY = 'qdp.web.stream-cache.v1';
const VOLUME_KEY = 'qdp.web.volume.v1';
const MUTED_KEY = 'qdp.web.muted.v1';
const PLAYER_SESSION_KEY = 'qdp.web.player-session.v1';
const ICONS = { play: 'play', pause: 'pause', volume: 'volume', mute: 'mute' };
const CACHE_TTL_MS = 1000 * 60 * 60 * 6;
const DISCOVER_RANDOM_SEEDS = ['jazz', 'classical', 'pop', 'new', 'electronic', 'soundtrack'];

const state = {
  type: 'tracks',
  q: '',
  quality: Number(localStorage.getItem('qdp.web.quality') || '5'),
  volume: clampVolume(localStorage.getItem(VOLUME_KEY)),
  muted: localStorage.getItem(MUTED_KEY) === '1',
  volumePopoverOpen: false,
  sidebarSections: { queue: true, playlists: false },
  lastNonZeroVolume: clampVolume(localStorage.getItem(VOLUME_KEY)) || 1,
  queue: [],
  idx: -1,
  playing: false,
  shuffle: false,
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
  loadingTrackId: '',
  audioEventGate: '',
  playerUi: { mode: 'idle', detail: '', statusText: 'Idle', activeTrackId: '', pendingTrackId: '', reason: '' },
  discoverRandom: { loading: false, seed: '', albums: [], error: '' },
  downloadMenu: { open: false, track: null, anchorRect: null, mobile: false },
  qualitySwitch: { active: false, label: '', token: 0, hideTimer: 0 },
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
};


function clampVolume(value){
  const num = Number(value);
  if(!Number.isFinite(num)) return 1;
  return Math.max(0, Math.min(1, num));
}
function persistedVolume(){
  return clampVolume(state.muted ? 0 : state.volume);
}
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
    ts: Date.now(),
  };
}
function persistPlayerSession(){
  const queue = normalizePersistedQueue(state.queue);
  if(!queue.length){
    safeLocalStorageRemove(PLAYER_SESSION_KEY);
    return null;
  }
  const payload = snapshotPlayerSession();
  safeLocalStorageSet(PLAYER_SESSION_KEY, JSON.stringify(payload));
  return payload;
}
function persistVolumeState(){
  safeLocalStorageSet(VOLUME_KEY, String(clampVolume(state.volume)));
  safeLocalStorageSet(MUTED_KEY, state.muted ? '1' : '0');
  persistPlayerSession();
}
function setAudioEventGate(kind = ''){
  state.audioEventGate = String(kind || '');
}
function consumeAudioEventGate(kind){
  if(state.audioEventGate && state.audioEventGate === kind){
    state.audioEventGate = '';
    return true;
  }
  return false;
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
  if(value > 0) state.lastNonZeroVolume = value;
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
function currentQuality(){
  const selectVal = Number($('qualitySelect')?.value || NaN);
  const val = Number.isFinite(selectVal) ? selectVal : Number(state.quality || 5);
  return Number.isFinite(val) ? val : 5;
}
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
function sanitizePlaylistName(name){
  return String(name || '').trim().slice(0, 80);
}
function loadPlaylists(){
  try{
    const raw = JSON.parse(localStorage.getItem(PLAYLISTS_KEY) || 'null');
    if(Array.isArray(raw)) return raw.map(normalizePlaylist).filter(Boolean);
    if(raw && Array.isArray(raw.items)) return raw.items.map(normalizePlaylist).filter(Boolean);
  }catch(_e){}
  try{
    const legacy = JSON.parse(localStorage.getItem('qdp.web.playlists.v1') || 'null');
    if(Array.isArray(legacy)) return legacy.map(normalizePlaylist).filter(Boolean);
  }catch(_e){}
  return [];
}
function savePlaylists(){
  localStorage.setItem(PLAYLISTS_KEY, JSON.stringify({ version: 1, items: state.playlists }));
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
function loadCacheMap(key){
  try{
    const obj = JSON.parse(sessionStorage.getItem(key) || localStorage.getItem(key) || '{}');
    if(obj && typeof obj === 'object') return obj;
  }catch(_e){}
  return {};
}
function saveCacheMap(key, map){
  const payload = JSON.stringify(map);
  try{ sessionStorage.setItem(key, payload); }catch(_e){}
  try{ localStorage.setItem(key, payload); }catch(_e){}
}
function getCachedMapValue(map, key){
  const item = map[String(key)];
  if(!item) return null;
  if(Date.now() - Number(item.ts || 0) > CACHE_TTL_MS) return null;
  return item.value;
}
function setCachedMapValue(map, storageKey, key, value){
  map[String(key)] = { ts: Date.now(), value };
  saveCacheMap(storageKey, map);
  return value;
}
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
    artist: it.artist || it.performer || ((it.performer||{}).name) || ((it.artist||{}).name) || '',
    image: it.image || ((it.album||{}).image||{}).large || ((it.album||{}).image||{}).medium || ((it.album||{}).image||{}).small || ((it.image||{}).large) || ((it.image||{}).medium) || ((it.image||{}).small) || '',
    albumId: it.albumId || (it.album && it.album.id) || null,
    albumTitle: it.albumTitle || (it.album && it.album.title) || '',
    bit_depth: spec.bitDepth,
    sampling_rate: spec.samplingRate,
  };
}
function setPlayIcon(kind){
  const icon = $('play').querySelector('.icon');
  icon.dataset.icon = kind;
}
function setActiveTab(type){
  state.type = type;
  document.querySelectorAll('.tab').forEach((b)=> b.classList.toggle('active', b.dataset.type === type));
}
function setView(renderer){
  state.currentView = renderer;
  const root = $('results');
  root.innerHTML = '';
  renderer(root);
  $('backTop').classList.toggle('hidden', state.history.length === 0);
}
function pushView(renderer){
  if(state.currentView) state.history.push(state.currentView);
  setView(renderer);
}
function goBack(){
  const prev = state.history.pop();
  if(prev) setView(prev);
  $('backTop').classList.toggle('hidden', state.history.length === 0);
}
function clearHistory(){
  state.history = [];
  state.currentView = null;
  $('backTop').classList.add('hidden');
}
function card(img, title, subtitle, onClick, actions = [], options = {}){
  const el = document.createElement('article');
  const audioSpec = options.audioSpec || '';
  const hiRes = options.hiRes ?? isHiResSource(options.audioSpecSource || options.entity || options.track || null);
  el.className = `card${options.compact ? ' compact' : ''}${options.emphasizeAudioSpec ? ' emphasizeAudioSpec' : ''}${hiRes ? ' hiResCard' : ''}`;
  el.innerHTML = `
    <img class="cardCover" src="${esc(img)}" alt="" />
    <div class="k cardBody">
      <div class="cardMain">
        <div class="titleStack">
          <div class="t"></div>
          <div class="s"></div>
        </div>
        <div class="metaBadges"></div>
      </div>
      <div class="cardActions"></div>
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
function makeBtn(label, onClick, cls='btn small'){
  const b = document.createElement('button');
  b.className = cls;
  b.textContent = label;
  b.addEventListener('click', (e)=>{ e.stopPropagation(); onClick(e); });
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
function renderPlayerStatus(){
  const node = $('playerStatus');
  if(node){
    const text = state.playerUi.statusText || 'Idle';
    node.textContent = text;
    node.title = text;
  }
  $('player')?.classList.toggle('compactMobile', isMobileLayout());
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
  renderQueue();
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
function buildQueueItemHint(idx){
  return '';
}
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
function closeDownloadMenu(){
  state.downloadMenu = { open: false, track: null, anchorRect: null, mobile: false };
  syncAuxiliaryUi();
  const menu = $('downloadMenu');
  if(!menu) return;
  menu.classList.add('hidden');
  menu.classList.remove('open');
  menu.classList.remove('mobileSheet');
  menu.setAttribute('aria-hidden', 'true');
  const card = $('downloadMenuCard');
  if(card){
    card.innerHTML = '';
    card.removeAttribute('style');
  }
}
function triggerTrackDownload(track, fmt = currentQuality()){
  const href = queueDownloadHref(track, fmt);
  const a = document.createElement('a');
  a.href = href;
  a.download = preferredTrackDownloadName(track, fmt);
  document.body.appendChild(a);
  a.click();
  a.remove();
  setPlayerStatus('download', `${normTrack(track)?.title || '当前歌曲'} · ${describeQuality(fmt).label}`);
  closeDownloadMenu();
  return href;
}
function positionDownloadMenu(rect){
  const menu = $('downloadMenu');
  const card = $('downloadMenuCard');
  if(!menu || !card) return;
  if(state.downloadMenu.mobile || isMobileLayout()){
    card.style.left = '12px';
    card.style.right = '12px';
    card.style.top = 'auto';
    card.style.bottom = '12px';
    card.style.width = 'auto';
    return;
  }
  if(!rect) return;
  const vw = window.innerWidth || document.documentElement.clientWidth || 0;
  const vh = window.innerHeight || document.documentElement.clientHeight || 0;
  const width = Math.min(240, Math.max(200, vw - 24));
  const left = Math.max(12, Math.min(rect.left, vw - width - 12));
  card.style.width = `${width}px`;
  card.style.right = 'auto';
  card.style.bottom = 'auto';
  requestAnimationFrame(()=>{
    const cardHeight = card.offsetHeight || 0;
    const showAbove = rect.bottom + cardHeight + 12 > vh && rect.top - cardHeight - 12 > 12;
    const top = showAbove ? Math.max(12, rect.top - cardHeight - 8) : Math.max(12, rect.bottom + 8);
    card.style.left = `${left}px`;
    card.style.top = `${top}px`;
  });
}
function buildDownloadMenuContent(track, mobile = false){
  const card = $('downloadMenuCard');
  if(!card) return;
  const t = normTrack(track);
  card.innerHTML = '';
  if(mobile){
    const head = document.createElement('div');
    head.className = 'downloadMenuHeader';
    head.innerHTML = `<div class="downloadMenuTitle">下载</div><div class="downloadMenuSub">${esc(t?.title || '当前歌曲')}</div>`;
    card.appendChild(head);
  }
  DOWNLOAD_FORMAT_OPTIONS.forEach((item)=>{
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = `downloadMenuOption${Number(currentQuality()) === item.fmt ? ' active' : ''}${mobile ? ' mobile' : ''}`;
    btn.dataset.fmt = String(item.fmt);
    btn.innerHTML = `<span class="downloadMenuFmt">${esc(item.label)}</span><span class="downloadMenuHint">${esc(item.hint)}</span>`;
    btn.addEventListener('click', (e)=>{
      e.stopPropagation();
      triggerTrackDownload(track, item.fmt);
    });
    card.appendChild(btn);
  });
  if(mobile){
    const cancel = document.createElement('button');
    cancel.type = 'button';
    cancel.className = 'downloadMenuOption mobile downloadMenuCancel';
    cancel.textContent = '取消';
    cancel.addEventListener('click', (e)=>{
      e.stopPropagation();
      closeDownloadMenu();
    });
    card.appendChild(cancel);
  }
}
function openDownloadMenu(track, anchor){
  if(!track?.id) return;
  const mobile = isMobileLayout();
  const rect = anchor?.getBoundingClientRect ? anchor.getBoundingClientRect() : null;
  state.downloadMenu = { open: true, track: normTrack(track), anchorRect: rect, mobile };
  syncAuxiliaryUi();
  const menu = $('downloadMenu');
  const card = $('downloadMenuCard');
  if(!menu || !card) return;
  buildDownloadMenuContent(track, mobile);
  menu.classList.remove('hidden');
  menu.classList.add('open');
  menu.classList.toggle('mobileSheet', mobile);
  menu.setAttribute('aria-hidden', 'false');
  positionDownloadMenu(rect);
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
    try{
      const full = album?.tracks ? album : await fetchAlbum(albumId);
      const tracks = (full?.tracks || []).map(normTrack).filter((track)=>track?.id);
      if(!tracks.length) return;
      triggerBulkDownload(tracks);
      setPlayerStatus('download', `${full?.title || album?.title || '专辑'} · ${tracks.length} 首`, { reason: 'album-download' });
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
    if(state.downloadMenu.open && state.downloadMenu.track?.id === String(track.id)){
      closeDownloadMenu();
      return;
    }
    openDownloadMenu(track, btn);
  });
  return btn;
}
function queueDownloadHref(track, fmt = currentQuality()){
  const id = encodeURIComponent(track.id);
  return `/api/download?id=${id}&fmt=${fmt}`;
}
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
function triggerBulkDownload(tracks, fmt = currentQuality()){
  const normalized = (Array.isArray(tracks) ? tracks : []).map(normTrack).filter((track)=>track?.id);
  normalized.forEach((track, index)=>window.setTimeout(()=>triggerTrackDownload(track, fmt), index * 180));
  return normalized.length;
}
function buildTrackListViewKey(options = {}, title = ''){
  return String(options.viewKey || [options.source || options.sourceType || 'tracks', options.playlistId || '', title || ''].filter(Boolean).join(':') || `tracks:${title || 'detail'}`);
}
function buildTrackListSubtitle(subtitle, options = {}, tracks = []){
  const parts = [subtitle];
  if(options.showTrackCount !== false && Array.isArray(tracks) && tracks.length) parts.push(`${tracks.length} 首`);
  const spec = options.audioSpec || formatAudioSpec(options.audioSpecSource || tracks.find((track)=>formatAudioSpec(track)) || null);
  if(spec) parts.push(spec);
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
