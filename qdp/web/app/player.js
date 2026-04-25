// Split from legacy app.js for lower-risk browser-native loading.

let _endedAdvanceTimer = 0;
const _PLAY_CURRENT_TIMEOUT_MS = 20000;
let _endedGeneration = 0;
let _errorHandledLocally = false;
let _volumeDuckTimer = 0;
let _seekDebounce = 0;
let _midPlaybackRetrying = false;

// ═══ Now Playing ═══

function syncNowPlaying(meta){
  const title = String(meta.title || '—');
  const subtitle = String(meta.artist || '—');
  $('title').textContent = title;
  $('title').title = title;
  $('subtitle').textContent = subtitle;
  $('subtitle').title = subtitle;
  $('cover').src = meta.image || '';
  updateMediaSession(meta, $('audio'));
  syncAuxiliaryUi();
  updateQueueInfo();
  updateDocumentTitle();
}
function updateDocumentTitle(){
  const track = normTrack(state.queue[state.idx]);
  if(!track || !state.playing && normalizePlayerUiMode(state.playerUi.mode) === 'idle'){
    document.title = 'QDP Web Player';
    return;
  }
  const t = track.title || '—';
  const a = track.artist || '';
  const mode = normalizePlayerUiMode(state.playerUi.mode);
  if(state.playing || mode === 'playing'){
    document.title = '▶ ' + t + ' — ' + a + ' | QDP';
  }else if(mode === 'paused' || mode === 'idle'){
    document.title = '❚❚ ' + t + ' — ' + a + ' | QDP';
  }else{
    document.title = 'QDP Web Player';
  }
}
function updateQueueInfo(){
  const el = $('playerQueueInfo');
  if(!el) return;
  if(state.queue.length > 0 && state.idx >= 0){
    el.textContent = `${state.idx + 1} / ${state.queue.length}`;
  }else{
    el.textContent = '—';
  }
}
function playerStatusText(mode, detail = ''){
  const normalizedMode = normalizePlayerUiMode(mode);
  const tail = state.activeAccount ? ` · ${state.activeAccount}` : '';
  if(normalizedMode === 'loading') return detail ? `正在准备 · ${detail}${tail}` : `正在准备播放${tail}`;
  if(normalizedMode === 'switching-quality') return detail ? `正在切换音质 · ${detail}${tail}` : `正在切换音质${tail}`;
  if(normalizedMode === 'playing') return detail ? `正在播放 · ${detail}${tail}` : `正在播放${tail}`;
  if(normalizedMode === 'paused') return detail ? `已暂停 · ${detail}${tail}` : `已暂停${tail}`;
  if(normalizedMode === 'download') return detail ? `开始下载 · ${detail}` : '开始下载';
  if(normalizedMode === 'error') return detail ? `播放异常 · ${detail}` : '播放异常';
  return detail || '空闲';
}
function currentTrackLabel(track = state.queue[state.idx], fmt = currentQuality()){
  const meta = normTrack(track) || {};
  const title = meta.title || '当前歌曲';
  const quality = describeQuality(fmt)?.label || describeQuality(currentQuality()).label;
  return `${title} · ${quality}`;
}
function applyCurrentTrackUi(track = state.queue[state.idx], options = {}){
  const meta = normTrack(track) || { title: '—', artist: '—', image: '' };
  syncNowPlaying(meta);
  if(options.statusMode){
    transitionPlayerUi(options.statusMode, currentTrackLabel(meta, options.fmt), {
      activeTrack: meta,
      pendingTrack: options.pendingTrack,
      reason: options.reason || '',
    });
  }
  return meta;
}
function setPlayerStatus(mode, detail = '', extra = {}){
  return transitionPlayerUi(mode, detail, extra);
}
function settleAfterPlayerError(mode, detail, extra = {}){
  const finalMode = normalizePlayerUiMode(mode || 'paused');
  if(finalMode === 'idle') return setPlayerStatus('idle', detail || '', extra);
  return setPlayerStatus(finalMode, detail || currentTrackLabel(extra.activeTrack), extra);
}
// ═══ Error Handling ═══

function handlePlayerError(err, options = {}){
  const audio = $('audio');
  const activeTrack = normTrack(options.activeTrack !== undefined ? options.activeTrack : state.queue[state.idx]);
  const fallbackMode = normalizePlayerUiMode(options.fallbackMode || (activeTrack ? 'paused' : 'idle'));
  const reason = options.reason || 'player-error';
  const message = String(options.message || err?.message || '播放器异常');
  state.playing = false;
  hideQualitySwitchFeedback(true);
  setPlayIcon(ICONS.play);
  updateDocumentTitle();
  if(options.pauseAudio !== false && audio){
    try{
      setAudioEventGate('pause');
      audio.pause();
    }catch(_e){}
  }
  setPlayerStatus('error', message, { activeTrack, reason });
  if(options.persist !== false) persistPlayerSession();
  if(options.settle !== false){
    window.setTimeout(()=>settleAfterPlayerError(fallbackMode, options.settleDetail || currentTrackLabel(activeTrack, options.fmt), {
      activeTrack,
      reason: `${reason}-settle`,
    }), 0);
  }
  if(options.logLabel !== false) console.error(options.logLabel || reason, err);
  return false;
}
// ═══ Session Restore ═══

function restorePersistedPlayerSession(options = {}){
  const raw = safeLocalStorageGet(PLAYER_SESSION_KEY);
  if(!raw) return false;
  try{
    const payload = JSON.parse(raw);
    const queue = normalizePersistedQueue(payload?.queue);
    if(!queue.length) return false;
    state.queue = queue;
    const payloadIdx = Number(payload?.idx);
    const fallbackTrack = normalizePersistedTrack(payload?.currentTrack);
    let nextIdx = Number.isInteger(payloadIdx) ? payloadIdx : -1;
    if(nextIdx < 0 || nextIdx >= queue.length){
      nextIdx = fallbackTrack ? queue.findIndex((item)=>String(item.id) === String(fallbackTrack.id)) : -1;
    }
    state.idx = nextIdx >= 0 ? nextIdx : 0;
    if(fallbackTrack && state.idx >= 0){
      state.queue[state.idx] = { ...state.queue[state.idx], ...fallbackTrack };
    }
    state.queueContext = buildQueueContext(payload?.queueContext || null);
    if(state.queueContext && state.idx >= 0){
      state.queueContext.activeOccurrenceKey = trackOccurrenceKey(state.queue[state.idx], state.queue, state.idx);
    }
    const restoredQuality = Number(payload?.quality);
    if(Number.isFinite(restoredQuality)) state.quality = restoredQuality;
    const restoredRepeatMode = String(payload?.repeatMode || '');
    if(REPEAT_MODES.includes(restoredRepeatMode)){
      state.repeatMode = restoredRepeatMode;
      safeLocalStorageSet(REPEAT_KEY, restoredRepeatMode);
    }
    syncRepeatUi();
    const restoredVolume = clampVolume(payload?.volume);
    state.volume = restoredVolume;
    if(restoredVolume > 0) state.lastNonZeroVolume = restoredVolume;
    state.muted = !!payload?.muted;
    state.playing = false;
    if($('qualitySelect')) $('qualitySelect').value = String(Number(state.quality || 5));
    applyVolumeToAudio();
    syncVolumeUi();
    const currentTrack = normTrack(state.queue[state.idx]);
    applyCurrentTrackUi(currentTrack);
    const restoredMode = payload?.wasPlaying ? 'paused' : normalizePlayerUiMode(payload?.playerMode || 'paused');
    settleAfterPlayerError(restoredMode === 'error' ? 'paused' : restoredMode, currentTrackLabel(currentTrack, state.quality), {
      activeTrack: currentTrack,
      reason: 'restore-player-session',
    });
    if(options.render !== false){
      renderQueue();
      syncAuxiliaryUi();
    }
    // Restore audio.src from stream cache so togglePlay doesn't need a fresh API call
    if(currentTrack?.id){
      const audio = $('audio');
      const cachedStream = state.streamCache && state.streamCache[`${currentTrack.id}:${state.quality}`];
      if(audio && cachedStream?.value?.url && streamCacheAge(`${currentTrack.id}:${state.quality}`) < STREAM_STALE_MS){
        try{ audio.src = cachedStream.value.url; }catch(_e){}
        audio.pause();
      }
    }
    persistPlayerSessionNow();
    return true;
  }catch(err){
    safeLocalStorageRemove(PLAYER_SESSION_KEY);
    handlePlayerError(err, {
      activeTrack: null,
      fallbackMode: 'idle',
      message: '恢复播放状态失败',
      reason: 'restore-player-session',
      pauseAudio: false,
      settleDetail: '空闲',
    });
    return false;
  }
}
// ═══ Playback ═══

function setCurrentIndex(nextIdx, reason = ''){
  if(nextIdx < 0 || nextIdx >= state.queue.length) return false;
  const previousTrackId = String(normTrack(state.queue[state.idx])?.id || '');
  const nextTrack = state.queue[nextIdx];
  const nextTrackId = String(normTrack(nextTrack)?.id || '');
  const isTrackSwitch = !!nextTrackId && nextTrackId !== previousTrackId;
  state.idx = nextIdx;
  if(state.queueContext) state.queueContext.activeOccurrenceKey = trackOccurrenceKey(nextTrack, state.queue, nextIdx);
  applyCurrentTrackUi(nextTrack, {
    statusMode: 'loading',
    pendingTrack: nextTrack,
    reason: isTrackSwitch ? reason : `${reason}（当前项）`,
  });
  if(reason){
    const reasonPrefix = isTrackSwitch ? reason : `${reason}（当前项）`;
    setPlayerStatus('loading', `${reasonPrefix} · ${currentTrackLabel(nextTrack)}`, {
      activeTrack: nextTrack,
      pendingTrack: nextTrack,
      reason: reasonPrefix,
    });
  }
  return true;
}
async function swapCurrentTrackQuality(fmt, options = {}){
  if(state.navLock) return false;
  state.navLock = true;
  try{
  const currentTrack = normTrack(state.queue[state.idx]);
  const audio = $('audio');
  if(!currentTrack?.id || !audio) return false;
  const seq = bumpRequestVersion('player');
  const wasPaused = options.forcePaused ?? audio.paused;
  const previousSrc = audio.currentSrc || audio.src || '';
  const previousTime = Number.isFinite(audio.currentTime) ? audio.currentTime : 0;
  const qualityMeta = describeQuality(fmt);
  showQualitySwitchFeedback(qualityMeta.label);
  setPlayerStatus('switching-quality', qualityMeta.label, {
    activeTrack: currentTrack,
    pendingTrack: currentTrack,
    reason: 'quality-switch',
  });
  try{
    const stream = await getTrackStream(currentTrack.id, fmt);
    if(seq !== state.playRequestSeq || state.idx < 0 || normTrack(state.queue[state.idx])?.id !== currentTrack.id) return false;
    if(previousSrc === stream.url){
      hideQualitySwitchFeedback();
      setPlayerStatus(wasPaused ? 'paused' : 'playing', currentTrackLabel(currentTrack, fmt), {
        activeTrack: currentTrack,
        reason: 'quality-switch-noop',
      });
      return true;
    }
    const restoreVolume = Number.isFinite(audio.volume) ? audio.volume : persistedVolume();
    const volumeBeforeDuck = state.volume;
    audio.dataset.playSeq = String(seq);
    audio.dataset.fmt = String(fmt);
    try{ audio.volume = wasPaused ? restoreVolume : Math.max(0.18, restoreVolume * 0.45); }catch(_e){}
    audio.src = stream.url;
    setAudioEventGate('pause');
    audio.load();
    await new Promise((resolve, reject)=>{
      const timeout = setTimeout(()=>{
        cleanup();
        reject(new Error('Audio load timed out'));
      }, 15000);
      const onLoaded = ()=>{ clearTimeout(timeout); cleanup(); resolve(); };
      const onError = ()=>{ clearTimeout(timeout); cleanup(); reject(new Error('新音质加载失败')); };
      const cleanup = ()=>{
        audio.removeEventListener('loadedmetadata', onLoaded);
        audio.removeEventListener('error', onError);
      };
      audio.addEventListener('loadedmetadata', onLoaded, { once: true });
      audio.addEventListener('error', onError, { once: true });
    });
    if(Number.isFinite(previousTime) && previousTime >= 0){
      const nextTime = audio.duration && isFinite(audio.duration) ? Math.min(previousTime, Math.max(audio.duration - 0.35, 0)) : previousTime;
      try{ audio.currentTime = Math.max(0, nextTime); }catch(_e){}
    }
    if(!wasPaused){
      setAudioEventGate('play');
      await audio.play();
      state.playing = true;
      setPlayIcon(ICONS.pause);
      clearTimeout(_volumeDuckTimer);
      _volumeDuckTimer = window.setTimeout(()=>{
        if(state.volume === volumeBeforeDuck){
          try{ applyVolumeToAudio(); }catch(_e){}
        }
      }, 140);
      setPlayerStatus('playing', currentTrackLabel(currentTrack, fmt), {
        activeTrack: currentTrack,
        reason: 'quality-switch-complete',
      });
    }else{
      try{ audio.volume = restoreVolume; }catch(_e){}
      audio.pause();
      applyVolumeToAudio();
      state.playing = false;
      setPlayIcon(ICONS.play);
      setPlayerStatus('paused', currentTrackLabel(currentTrack, fmt), {
        activeTrack: currentTrack,
        reason: 'quality-switch-complete',
      });
    }
    hideQualitySwitchFeedback();
    prefetchAdjacentStreams(state.idx, fmt);
    return true;
  }catch(err){
    if(seq !== state.playRequestSeq) return false;
    if(previousSrc && audio.src !== previousSrc) audio.src = previousSrc;
    try{
      setAudioEventGate('pause');
      audio.load();
      if(Number.isFinite(previousTime) && previousTime > 0) audio.currentTime = previousTime;
      if(!wasPaused){
        setAudioEventGate('play');
        await audio.play();
      }
      applyVolumeToAudio();
      state.playing = !wasPaused;
      setPlayIcon(wasPaused ? ICONS.play : ICONS.pause);
    }catch(_e){}
    hideQualitySwitchFeedback(true);
    return handlePlayerError(err, {
      activeTrack: currentTrack,
      fallbackMode: wasPaused ? 'paused' : 'playing',
      reason: 'quality-switch-rollback',
      settleDetail: currentTrackLabel(currentTrack),
      pauseAudio: false,
      logLabel: 'swapCurrentTrackQuality failed',
    });
  }
  }finally{ state.navLock = false; }
}
async function playCurrent(reason = ''){
  _endedGeneration++;
  const currentIdx = state.idx;
  const cur = state.queue[currentIdx];
  if(!cur) return false;
  const seq = bumpRequestVersion('player');
  const audio = $('audio');
  const fmt = currentQuality();
  const pendingTrack = normTrack(cur);
  applyCurrentTrackUi(pendingTrack, {
    statusMode: 'loading',
    fmt,
    pendingTrack,
    reason,
  });
  if(reason){
    setPlayerStatus('loading', `${reason} · ${currentTrackLabel(pendingTrack, fmt)}`, {
      activeTrack: pendingTrack,
      pendingTrack,
      reason,
    });
  }

  try{
    const meta = await getTrackMeta(cur);
    if(seq !== state.playRequestSeq || currentIdx !== state.idx) return false;
    state.queue[state.idx] = meta;
    if(state.queueContext) state.queueContext.activeOccurrenceKey = trackOccurrenceKey(meta, state.queue, state.idx);
    applyCurrentTrackUi(meta, {
      statusMode: 'loading',
      fmt,
      pendingTrack: meta,
      reason,
    });
    if(reason){
      setPlayerStatus('loading', `${reason} · ${currentTrackLabel(meta, fmt)}`, {
        activeTrack: meta,
        pendingTrack: meta,
        reason,
      });
    }

    // Validate cached stream freshness before fetching
    const streamCacheKey = `${meta.id}:${fmt}`;
    const streamAge = streamCacheAge(streamCacheKey);
    if(streamAge < Infinity && streamAge >= STREAM_STALE_MS){
      console.debug(`[playCurrent] evicting stale stream cache (${Math.round(streamAge / 1000)}s)`, streamCacheKey);
      delete state.streamCache[streamCacheKey];
      saveCacheMap(STREAM_CACHE_KEY, state.streamCache);
    }

    // Overall timeout — prevents playCurrent from hanging forever
    const _timeout = new Promise((_, reject) => setTimeout(() => reject(new Error('播放超时')), _PLAY_CURRENT_TIMEOUT_MS));
    const stream = await Promise.race([
      getTrackStreamWithRetry(meta.id, fmt),
      _timeout,
    ]);
    if(seq !== state.playRequestSeq || currentIdx !== state.idx) return false;

    audio.dataset.playSeq = String(seq);
    audio.dataset.fmt = String(fmt);
    if(audio.src !== stream.url){
      audio.src = stream.url;
    }else{
      // Force reload even with same URL (retry after error)
      audio.src = '';
      audio.src = stream.url;
    }
    applyVolumeToAudio();
    setAudioEventGate('play');
    await audio.play();
    state.playing = true;
    setPlayIcon(ICONS.pause);
    setPlayerStatus('playing', currentTrackLabel(meta, fmt), {
      activeTrack: meta,
      reason,
    });
    prefetchAdjacentStreams(state.idx, fmt);
    return true;
  }catch(err){
    if(seq !== state.playRequestSeq) return false;

    // If autoplay was blocked, show paused state instead of error
    if(err?.name === 'NotAllowedError'){
      const meta = normTrack(cur);
      state.playing = false;
      setPlayIcon(ICONS.play);
      setPlayerStatus('paused', `${currentTrackLabel(meta, fmt)} · 点击播放按钮开始`, {
        activeTrack: meta,
        reason: 'autoplay-blocked',
      });
      showToast('浏览器阻止了自动播放，请点击播放按钮', 'info');
      persistPlayerSession();
      return false;
    }

    // invalidate stream cache for this track so retry gets fresh URL
    const cacheKey = `${normTrack(cur)?.id}:${fmt}`;
    if(state.streamCache && state.streamCache[cacheKey]){
      delete state.streamCache[cacheKey];
      saveCacheMap(STREAM_CACHE_KEY, state.streamCache);
    }
    return handlePlayerError(err, {
      activeTrack: cur,
      fallbackMode: cur ? 'paused' : 'idle',
      reason: reason || 'play-current',
      settleDetail: currentTrackLabel(cur, fmt),
      message: err.message || '播放失败',
      logLabel: 'playCurrent failed',
    });
  }
}
// ═══ Navigation ═══

function nextIndex(){
  if(!state.queue.length) return -1;
  if(state.shuffle && state.queue.length > 1){
    let pick = state.idx;
    while(pick === state.idx) pick = Math.floor(Math.random() * state.queue.length);
    return pick;
  }
  if(state.idx + 1 < state.queue.length) return state.idx + 1;
  if(state.repeatMode === 'off') return -1;
  return 0;
}
async function navigateQueue(delta, reason){
  if(_endedAdvanceTimer){ clearTimeout(_endedAdvanceTimer); _endedAdvanceTimer = 0; }
  _endedGeneration++;
  const audio = $('audio');
  if(state.navLock) return state.idx;
  state.navLock = true;
  if(delta < 0 && audio.currentTime > 3){
    audio.currentTime = 0;
    const currentTrack = normTrack(state.queue[state.idx]);
    const mode = state.playing ? 'playing' : 'paused';
    setPlayerStatus(mode, currentTrackLabel(currentTrack), {
      activeTrack: currentTrack,
      reason: 'seek-reset',
    });
    state.navLock = false;
    return state.idx;
  }
  const previousIdx = state.idx;
  const previousTrack = normTrack(state.queue[previousIdx]);
  const targetIdx = delta > 0 ? nextIndex() : state.idx - 1;
  const navSeq = ++state.navRequestSeq;
  if(targetIdx < 0 || targetIdx >= state.queue.length){ state.navLock = false; return state.idx; }
  if(!setCurrentIndex(targetIdx, reason)){ state.navLock = false; return state.idx; }
  try{
    const ok = await playCurrent(reason);
    if(navSeq !== state.navRequestSeq){ state.navLock = false; return state.idx; }

    if(!ok){
      if(previousIdx >= 0 && previousIdx < state.queue.length){
        state.idx = previousIdx;
        if(state.queueContext) state.queueContext.activeOccurrenceKey = trackOccurrenceKey(state.queue[state.idx], state.queue, state.idx);
        applyCurrentTrackUi(previousTrack || state.queue[state.idx], { statusMode: state.playing ? 'playing' : 'paused' });
      }
    }
  }catch(err){
    state.navLock = false;
    console.warn('navigateQueue error', err);
    return state.idx;
  }
  state.navLock = false;
  return state.idx;
}
async function prev(){
  return navigateQueue(-1, '上一首');
}
async function next(){
  return navigateQueue(1, '下一首');
}

// ═══ Controls ═══

async function togglePlay(){
  if(state.playerUi.mode === 'loading' || state.playerUi.mode === 'switching-quality') return;
  const audio = $('audio');
  if(!audio.src || audio.src === location.href || audio.src === '' || audio.networkState === HTMLMediaElement.NETWORK_EMPTY){
    if(state.queue.length && state.idx >= 0) await playCurrent('恢复播放');
    return;
  }
  const currentTrack = normTrack(state.queue[state.idx]);
  if(audio.paused){
    // Check if stream URL is stale and refresh proactively
    if(currentTrack?.id){
      const staleKey = `${currentTrack.id}:${currentQuality()}`;
      if(streamCacheAge(staleKey) >= STREAM_STALE_MS){
        console.debug('[togglePlay] stream stale, refreshing before resume');
        try{
          const toggleSeq = state.playRequestSeq;
          const freshStream = await getTrackStream(currentTrack.id, currentQuality());
          if(toggleSeq !== state.playRequestSeq){ return; }
          if(freshStream?.url){
            const currentTime = audio.currentTime;
            audio.src = freshStream.url;
            audio.addEventListener('loadedmetadata', ()=>{ audio.currentTime = currentTime; }, { once: true });
          }
        }catch(_e){
          // Refresh failed, try playing with existing URL anyway
        }
      }
    }
    applyVolumeToAudio();
    setAudioEventGate('play');
    setPlayerStatus('loading', `恢复播放 · ${currentTrackLabel(currentTrack)}`, {
      activeTrack: currentTrack,
      pendingTrack: currentTrack,
      reason: 'resume',
    });
    try{
      await audio.play();
      state.playing = true;
      setPlayIcon(ICONS.pause);
      setPlayerStatus('playing', currentTrackLabel(currentTrack), {
        activeTrack: currentTrack,
        reason: 'resume',
      });
    }catch(_err){
      state.audioEventGate = '';
      setPlayIcon(ICONS.play);
      setPlayerStatus(state.queue.length ? 'paused' : 'idle', currentTrackLabel(currentTrack), {
        activeTrack: currentTrack,
        reason: 'play-rejected',
      });
    }
  }else{
    setAudioEventGate('pause');
    audio.pause();
    state.playing = false;
    setPlayIcon(ICONS.play);
    setPlayerStatus('paused', currentTrackLabel(currentTrack), {
      activeTrack: currentTrack,
      reason: 'pause',
    });
  }
}
function toggleShuffleMode(){
  state.shuffle = !state.shuffle;
  $('shuffle').classList.toggle('active', state.shuffle);
  $('shuffleMain').classList.toggle('active', state.shuffle);
}
function toggleRepeatMode(){
  const currentIdx = REPEAT_MODES.indexOf(state.repeatMode);
  const nextIdx = (currentIdx + 1) % REPEAT_MODES.length;
  state.repeatMode = REPEAT_MODES[nextIdx];
  safeLocalStorageSet(REPEAT_KEY, state.repeatMode);
  syncRepeatUi();
  persistPlayerSession();
}
function syncRepeatUi(){
  const mode = state.repeatMode;
  const iconName = mode === 'one' ? ICONS.repeatOne : ICONS.repeat;
  ['repeat', 'repeatMain'].forEach((id)=>{
    const btn = $(id);
    if(!btn) return;
    btn.classList.toggle('active', mode !== 'off');
    const icon = btn.querySelector('.icon');
    if(icon) icon.dataset.icon = iconName;
  });
}
function shuffleQueueNow(){
  if(state.queue.length < 2) return;
  const current = state.queue[state.idx];
  const rest = state.queue.filter((_, i)=>i !== state.idx);
  for(let i = rest.length - 1; i > 0; i--){
    const j = Math.floor(Math.random() * (i + 1));
    [rest[i], rest[j]] = [rest[j], rest[i]];
  }
  state.queue = current ? [current, ...rest] : rest;
  state.idx = current ? 0 : -1;
  if(state.queueContext && state.idx >= 0) state.queueContext.activeOccurrenceKey = trackOccurrenceKey(state.queue[state.idx], state.queue, state.idx);
  renderQueue();
}
// ═══ Audio Bindings ═══

function bindPlayer(){
  const audio = $('audio');
  const seek = $('seek');
  applyVolumeToAudio();
  syncVolumeUi();
  bindMediaSessionHandlers();

  audio.addEventListener('loadstart', ()=>{
    if(state.qualitySwitch.active) return;
    if(normalizePlayerUiMode(state.playerUi.mode) === 'error') return;
    const currentTrack = normTrack(state.queue[state.idx]);
    if(!state.playerUi.pendingTrackId) state.playerUi.pendingTrackId = String(currentTrack?.id || '');
    if(state.playerUi.pendingTrackId){
      const mode = 'loading';
      const detail = currentTrackLabel(currentTrack);
      setPlayerStatus(mode, detail, {
        activeTrack: currentTrack,
        pendingTrackId: state.playerUi.pendingTrackId,
        reason: 'audio-loadstart',
      });
    }
  });

  audio.addEventListener('canplay', ()=>{
    if(state.qualitySwitch.active) return;
    const currentTrack = normTrack(state.queue[state.idx]);
    const pendingTrackId = String(state.playerUi.pendingTrackId || '');
    const currentTrackId = String(currentTrack?.id || '');
    if(pendingTrackId && pendingTrackId === currentTrackId){
      const mode = audio.paused ? 'paused' : 'playing';
      const detail = currentTrackLabel(currentTrack);
      setPlayerStatus(mode, detail, {
        activeTrack: currentTrack,
        pendingTrack: null,
        reason: 'audio-canplay',
      });
      hideQualitySwitchFeedback();
    }
  });

  let _mediaSessionPosThrottle = 0;
  audio.addEventListener('timeupdate', ()=>{
    if(!audio.duration || !isFinite(audio.duration)) return;
    const v = Math.floor((audio.currentTime / audio.duration) * 1000);
    seek.value = String(v);
    $('tcur').textContent = fmtTime(audio.currentTime);
    $('tdur').textContent = fmtTime(audio.duration);
    const now = Date.now();
    if(now - _mediaSessionPosThrottle > 3000){
      _mediaSessionPosThrottle = now;
      updateMediaSession(state.queue[state.idx], audio);
    }
  });

  seek.addEventListener('input', ()=>{
    if(state.playerUi.mode === 'loading' || state.playerUi.mode === 'switching-quality') return;
    if(!audio.duration || !isFinite(audio.duration)) return;
    const v = Number(seek.value || 0) / 1000;
    audio.currentTime = v * audio.duration;
  });

  audio.addEventListener('volumechange', ()=>{
    const volume = clampVolume(audio.volume);
    state.muted = !!audio.muted || volume <= 0;
    if(volume > 0){
      state.volume = volume;
      state.lastNonZeroVolume = volume;
    }
    persistVolumeState();
    syncVolumeUi();
  });

  audio.addEventListener('ended', ()=>{
    if(!state.queue.length || state.idx < 0) return;
    if(_endedAdvanceTimer){ clearTimeout(_endedAdvanceTimer); _endedAdvanceTimer = 0; }
    _endedGeneration++;
    if(state.navLock) return;
    state.playing = false;
    hideQualitySwitchFeedback(true);
    setPlayIcon(ICONS.play);
    updateDocumentTitle();

    const startIdx = state.idx;
    const maxSkip = Math.min(state.queue.length, 5);
    let failedIdx = -1;

    // Repeat-one: replay current track immediately
    if(state.repeatMode === 'one'){
      const audio = $('audio');
      audio.currentTime = 0;
      setAudioEventGate('play');
      const currentTrack = normTrack(state.queue[state.idx]);
      audio.play().then(()=>{
        state.playing = true;
        setPlayIcon(ICONS.pause);
        setPlayerStatus('playing', currentTrackLabel(currentTrack), {
          activeTrack: currentTrack,
          reason: 'repeat-one',
        });
      }).catch(()=>{
        state.playing = false;
        setPlayIcon(ICONS.play);
        setPlayerStatus('paused', currentTrackLabel(currentTrack), {
          activeTrack: currentTrack,
          reason: 'repeat-one-failed',
        });
      });
      return;
    }

    // Repeat-off and at last track: stop playback
    if(state.repeatMode === 'off' && state.idx >= state.queue.length - 1){
      state.playing = false;
      setPlayIcon(ICONS.play);
      const currentTrack = normTrack(state.queue[state.idx]);
      setPlayerStatus('paused', currentTrackLabel(currentTrack), {
        activeTrack: currentTrack,
        reason: 'ended-queue-end',
      });
      persistPlayerSession();
      return;
    }

    if(_midPlaybackRetrying){ return; }

    const endedGen = _endedGeneration;
    function advanceEnded(attempt, retrying){
      if(_endedGeneration !== endedGen) return; // user manually intervened
      if(state.navLock){
        _endedAdvanceTimer = setTimeout(()=>{
          _endedAdvanceTimer = 0;
          advanceEnded(attempt, retrying);
        }, 200);
        return;
      }
      state.navLock = true;
      if(attempt > maxSkip || !state.queue.length){
        state.playing = false;
        setPlayIcon(ICONS.play);
        setPlayerStatus('error', '所有歌曲均无法播放，请手动选择', {
          activeTrack: normTrack(state.queue[state.idx]),
          reason: 'ended-all-failed',
        });
        showToast('所有歌曲均无法播放', 'error');
        state.navLock = false;
        return;
      }
      let ni;
      if(retrying){
        ni = failedIdx;
      }else if(attempt === 0){
        ni = nextIndex();
      }else{
        // Skip past the previously failed track
        ni = failedIdx + 1 < state.queue.length ? failedIdx + 1 : 0;
        if(ni === startIdx){
          state.playing = false;
          setPlayIcon(ICONS.play);
          setPlayerStatus('error', '所有歌曲均无法播放', { settle: true });
          state.navLock = false;
          return;
        }
      }
      if(ni < 0 || ni >= state.queue.length){ state.navLock = false; return; }
      if(!retrying) failedIdx = ni;
      setPlayerStatus('loading', retrying ? '重试播放' : '自动前进到下一首', {
        activeTrack: state.queue[startIdx],
        pendingTrack: state.queue[ni],
        reason: 'ended-next',
      });
      setCurrentIndex(ni, retrying ? '重试播放' : '自动下一首');
      playCurrent(retrying ? 'ended-retry' : 'ended-next').then((ok)=>{
        state.navLock = false;
        if(ok){
          prefetchAdjacentStreams();
        }else if(!retrying){
          _endedAdvanceTimer = setTimeout(()=>{ _endedAdvanceTimer = 0; advanceEnded(attempt, true); }, 500);
        }else{
          _endedAdvanceTimer = setTimeout(()=>{ _endedAdvanceTimer = 0; advanceEnded(attempt + 1, false); }, 250);
        }
      }).catch((err)=>{
        state.navLock = false;
        console.warn('ended-next failed, skipping track', err);
        if(!retrying){
          _endedAdvanceTimer = setTimeout(()=>{ _endedAdvanceTimer = 0; advanceEnded(attempt, true); }, 500);
        }else{
          _endedAdvanceTimer = setTimeout(()=>{ _endedAdvanceTimer = 0; advanceEnded(attempt + 1, false); }, 250);
        }
      });
    }

    advanceEnded(0, false);
  });
  audio.addEventListener('pause', ()=>{
    if(audio.ended) return;
    if(consumeAudioEventGate('pause')) return;
    state.playing = false;
    setPlayIcon(ICONS.play);
    updateMediaSessionPlaybackState(false);
    updateDocumentTitle();
    const currentTrack = normTrack(state.queue[state.idx]);
    if(state.qualitySwitch.active){
      setPlayerStatus('switching-quality', describeQuality(audio.dataset.fmt || currentQuality()).label, {
        activeTrack: currentTrack,
        pendingTrack: currentTrack,
        reason: 'audio-pause-quality-switch',
      });
      return;
    }
    if(normalizePlayerUiMode(state.playerUi.mode) === 'loading') return;
    setPlayerStatus('paused', currentTrackLabel(currentTrack), {
      activeTrack: currentTrack,
      reason: 'audio-pause',
    });
  });
  audio.addEventListener('play', ()=>{
    if(consumeAudioEventGate('play')) return;
    state.playing = true;
    setPlayIcon(ICONS.pause);
    updateMediaSessionPlaybackState(true);
    updateMediaSession(state.queue[state.idx], audio);
    updateDocumentTitle();
    const currentTrack = normTrack(state.queue[state.idx]);
    if(state.qualitySwitch.active){
      setPlayerStatus('switching-quality', describeQuality(audio.dataset.fmt || currentQuality()).label, {
        activeTrack: currentTrack,
        pendingTrack: currentTrack,
        reason: 'audio-play-quality-switch',
      });
      return;
    }
    prefetchAdjacentStreams();
    setPlayerStatus('playing', currentTrackLabel(currentTrack), {
      activeTrack: currentTrack,
      reason: 'audio-play',
    });
  });
  audio.addEventListener('emptied', ()=>{
    // When src is cleared/changed, suppress any pending ended handling
    if(_endedAdvanceTimer){ clearTimeout(_endedAdvanceTimer); _endedAdvanceTimer = 0; }
  });
  const MID_PLAYBACK_MAX_RETRIES = 3;

  audio.addEventListener('error', async () => {
    if(_midPlaybackRetrying) return;
    const currentTrack = normTrack(state.queue[state.idx]);
    const mediaError = audio.error;
    const isRecoverable = mediaError && (
      mediaError.code === MediaError.MEDIA_ERR_NETWORK ||
      mediaError.code === MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED
    );

    if(isRecoverable && currentTrack?.id){
      _midPlaybackRetrying = true;
      const recoverySeq = state.playRequestSeq;
      const lastPos = audio.currentTime || 0;
      const fmt = Number(audio.dataset.fmt || currentQuality());
      let recovered = false;

      // ── Try cached track fallback first ──
      try{
        const cachedAvailable = await checkCachedTrack(currentTrack.id, fmt);
        if(recoverySeq !== state.playRequestSeq){ _midPlaybackRetrying = false; return; }
        if(cachedAvailable){
          console.info('[stream-recovery] cached track available, switching source');
          setPlayerStatus('loading', '切换到本地缓存', {
            activeTrack: currentTrack,
            reason: 'cache-fallback',
          });
          const cachedUrl = getCachedTrackUrl(currentTrack.id, fmt);
          audio.src = cachedUrl;
          audio.load();
          await new Promise((resolve, reject)=>{
            const timeout = setTimeout(()=>{ cleanup(); reject(new Error('Cached audio load timed out')); }, 15000);
            const onLoaded = ()=>{ clearTimeout(timeout); cleanup(); resolve(); };
            const onError = ()=>{ clearTimeout(timeout); cleanup(); reject(new Error('cached track load failed')); };
            const cleanup = ()=>{
              audio.removeEventListener('loadedmetadata', onLoaded);
              audio.removeEventListener('error', onError);
            };
            audio.addEventListener('loadedmetadata', onLoaded, { once: true });
            audio.addEventListener('error', onError, { once: true });
          });
          if(lastPos > 0 && Number.isFinite(lastPos)){
            try{ audio.currentTime = Math.max(0, lastPos - 1); }catch(_e){}
          }
          applyVolumeToAudio();
          setAudioEventGate('play');
          await audio.play();
          if(recoverySeq !== state.playRequestSeq){ _midPlaybackRetrying = false; return; }
          state.playing = true;
          setPlayIcon(ICONS.pause);
          recovered = true;
          console.info('[stream-recovery] playback recovered from cached file');
        }
      }catch(cacheErr){
        console.warn('[stream-recovery] cached track fallback failed, trying stream refresh:', cacheErr);
      }

      // ── Existing retry logic (only if cache didn't work) ──
      if(!recovered){
      for(let attempt = 1; attempt <= MID_PLAYBACK_MAX_RETRIES; attempt++){
        const cacheKey = `${currentTrack.id}:${fmt}`;
        const cacheAge = streamCacheAge(cacheKey);
        const ageLabel = cacheAge === Infinity ? 'no cache' : `${Math.round(cacheAge / 1000)}s`;
        console.warn(`[stream-recovery] mid-playback error (attempt ${attempt}/${MID_PLAYBACK_MAX_RETRIES}), refreshing stream URL… cache age: ${ageLabel}`);
        setPlayerStatus('loading', `重新获取音频流 (${attempt}/${MID_PLAYBACK_MAX_RETRIES})`, {
          activeTrack: currentTrack,
          reason: 'stream-url-refresh',
        });
        try{
          await new Promise((r)=>setTimeout(r, 500 * attempt));
          if(state.streamCache && state.streamCache[cacheKey]){
            delete state.streamCache[cacheKey];
            saveCacheMap(STREAM_CACHE_KEY, state.streamCache);
          }
          const stream = await getTrackStream(currentTrack.id, fmt);
          if(recoverySeq !== state.playRequestSeq){ _midPlaybackRetrying = false; return; }
          audio.src = stream.url;
          audio.load();
          await new Promise((resolve, reject)=>{
            const timeout = setTimeout(()=>{
              cleanup();
              reject(new Error('Audio load timed out'));
            }, 15000);
            const onLoaded = ()=>{ clearTimeout(timeout); cleanup(); resolve(); };
            const onError = ()=>{ clearTimeout(timeout); cleanup(); reject(new Error('retry load failed')); };
            const cleanup = ()=>{
              audio.removeEventListener('loadedmetadata', onLoaded);
              audio.removeEventListener('error', onError);
            };
            audio.addEventListener('loadedmetadata', onLoaded, { once: true });
            audio.addEventListener('error', onError, { once: true });
          });
          if(recoverySeq !== state.playRequestSeq){ _midPlaybackRetrying = false; return; }
          if(lastPos > 0 && Number.isFinite(lastPos)){
            try{ audio.currentTime = Math.max(0, lastPos - 1); }catch(_e){}
          }
          applyVolumeToAudio();
          setAudioEventGate('play');
          await audio.play();
          if(recoverySeq !== state.playRequestSeq){ _midPlaybackRetrying = false; return; }
          state.playing = true;
          setPlayIcon(ICONS.pause);
          recovered = true;
          console.info('[stream-recovery] playback recovered successfully');
          break;
        }catch(retryErr){
          console.error(`[stream-recovery] attempt ${attempt} failed`, retryErr);
        }
      }
      } // end if(!recovered)

      _midPlaybackRetrying = false;
      if(recovered) return;
    }

    const fallbackMode = audio.src ? 'paused' : 'idle';
    handlePlayerError(new Error(currentTrack ? `${currentTrack.title} 加载失败` : '音频流加载失败'), {
      activeTrack: currentTrack,
      fallbackMode,
      reason: 'audio-error',
      settleDetail: currentTrack ? currentTrackLabel(currentTrack) : '空闲',
      logLabel: 'audio error',
    });
  });
}
