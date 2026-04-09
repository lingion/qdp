// Split from legacy app.js for lower-risk browser-native loading.

function syncNowPlaying(meta){
  const title = String(meta.title || '—');
  const subtitle = String(meta.artist || '—');
  $('title').textContent = title;
  $('title').title = title;
  $('subtitle').textContent = subtitle;
  $('subtitle').title = subtitle;
  $('cover').src = meta.image || '';
  syncAuxiliaryUi();
  renderQueue();
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
  return detail || 'Idle';
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
function handlePlayerError(err, options = {}){
  const audio = $('audio');
  const activeTrack = normTrack(options.activeTrack !== undefined ? options.activeTrack : state.queue[state.idx]);
  const fallbackMode = normalizePlayerUiMode(options.fallbackMode || (activeTrack ? 'paused' : 'idle'));
  const reason = options.reason || 'player-error';
  const message = String(options.message || err?.message || '播放器异常');
  state.playing = false;
  hideQualitySwitchFeedback(true);
  setPlayIcon(ICONS.play);
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
    persistPlayerSession();
    return true;
  }catch(err){
    safeLocalStorageRemove(PLAYER_SESSION_KEY);
    handlePlayerError(err, {
      activeTrack: null,
      fallbackMode: 'idle',
      message: '恢复播放状态失败',
      reason: 'restore-player-session',
      pauseAudio: false,
      settleDetail: 'Idle',
    });
    return false;
  }
}
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
  const currentTrack = normTrack(state.queue[state.idx]);
  const audio = $('audio');
  if(!currentTrack?.id || !audio) return false;
  const seq = ++state.playRequestSeq;
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
    audio.dataset.playSeq = String(seq);
    audio.dataset.fmt = String(fmt);
    try{ audio.volume = wasPaused ? restoreVolume : Math.max(0.18, restoreVolume * 0.45); }catch(_e){}
    audio.src = stream.url;
    setAudioEventGate('pause');
    audio.load();
    await new Promise((resolve, reject)=>{
      const onLoaded = ()=>{ cleanup(); resolve(); };
      const onError = ()=>{ cleanup(); reject(new Error('新音质加载失败')); };
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
      window.setTimeout(()=>{ try{ applyVolumeToAudio(); }catch(_e){} }, 140);
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
}
async function playCurrent(reason = ''){
  const currentIdx = state.idx;
  const cur = state.queue[currentIdx];
  if(!cur) return false;
  const seq = ++state.playRequestSeq;
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

    const stream = await getTrackStream(meta.id, fmt);
    if(seq !== state.playRequestSeq || currentIdx !== state.idx) return false;

    audio.dataset.playSeq = String(seq);
    audio.dataset.fmt = String(fmt);
    if(audio.src !== stream.url) audio.src = stream.url;
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
function nextIndex(){
  if(!state.queue.length) return -1;
  if(state.shuffle && state.queue.length > 1){
    let pick = state.idx;
    while(pick === state.idx) pick = Math.floor(Math.random() * state.queue.length);
    return pick;
  }
  return state.idx + 1 < state.queue.length ? state.idx + 1 : -1;
}
async function navigateQueue(delta, reason){
  const audio = $('audio');
  if(delta < 0 && audio.currentTime > 3){
    audio.currentTime = 0;
    const currentTrack = normTrack(state.queue[state.idx]);
    const mode = state.playing ? 'playing' : 'paused';
    setPlayerStatus(mode, currentTrackLabel(currentTrack), {
      activeTrack: currentTrack,
      reason: 'seek-reset',
    });
    return state.idx;
  }
  const previousIdx = state.idx;
  const previousTrack = normTrack(state.queue[previousIdx]);
  const targetIdx = delta > 0 ? nextIndex() : state.idx - 1;
  const navSeq = ++state.navRequestSeq;
  if(targetIdx < 0 || targetIdx >= state.queue.length) return state.idx;
  if(!setCurrentIndex(targetIdx, reason)) return state.idx;
  const ok = await playCurrent(reason);
  if(navSeq !== state.navRequestSeq) return state.idx;
  if(!ok){
    if(previousIdx >= 0 && previousIdx < state.queue.length){
      state.idx = previousIdx;
      if(state.queueContext) state.queueContext.activeOccurrenceKey = trackOccurrenceKey(state.queue[state.idx], state.queue, state.idx);
      applyCurrentTrackUi(previousTrack || state.queue[state.idx]);
    }
    handlePlayerError(new Error('导航失败'), {
      activeTrack: previousTrack || state.queue[state.idx],
      fallbackMode: previousTrack ? 'paused' : 'idle',
      reason: 'nav-failed',
      settleDetail: currentTrackLabel(previousTrack || state.queue[state.idx]),
      logLabel: false,
    });
    return state.idx;
  }
  return state.idx;
}
async function prev(){
  return navigateQueue(-1, '上一首');
}
async function next(){
  return navigateQueue(1, '下一首');
}
async function togglePlay(){
  const audio = $('audio');
  if(!audio.src){
    if(state.queue.length && state.idx >= 0) await playCurrent('恢复播放');
    return;
  }
  const currentTrack = normTrack(state.queue[state.idx]);
  if(audio.paused){
    applyVolumeToAudio();
    setAudioEventGate('play');
    setPlayerStatus('loading', `恢复播放 · ${currentTrackLabel(currentTrack)}`, {
      activeTrack: currentTrack,
      pendingTrack: currentTrack,
      reason: 'resume',
    });
    await audio.play();
    state.playing = true;
    setPlayIcon(ICONS.pause);
    setPlayerStatus('playing', currentTrackLabel(currentTrack), {
      activeTrack: currentTrack,
      reason: 'resume',
    });
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
function bindPlayer(){
  const audio = $('audio');
  const seek = $('seek');
  applyVolumeToAudio();
  syncVolumeUi();

  audio.addEventListener('loadstart', ()=>{
    const currentTrack = normTrack(state.queue[state.idx]);
    if(!state.playerUi.pendingTrackId) state.playerUi.pendingTrackId = String(currentTrack?.id || '');
    if(state.playerUi.pendingTrackId){
      const mode = state.qualitySwitch.active ? 'switching-quality' : 'loading';
      const detail = state.qualitySwitch.active ? describeQuality(audio.dataset.fmt || currentQuality()).label : currentTrackLabel(currentTrack);
      setPlayerStatus(mode, detail, {
        activeTrack: currentTrack,
        pendingTrackId: state.playerUi.pendingTrackId,
        reason: 'audio-loadstart',
      });
    }
  });

  audio.addEventListener('canplay', ()=>{
    const currentTrack = normTrack(state.queue[state.idx]);
    const pendingTrackId = String(state.playerUi.pendingTrackId || '');
    const currentTrackId = String(currentTrack?.id || '');
    if(pendingTrackId && pendingTrackId === currentTrackId){
      const mode = state.qualitySwitch.active ? 'switching-quality' : (audio.paused ? 'paused' : 'playing');
      const detail = state.qualitySwitch.active ? describeQuality(audio.dataset.fmt || currentQuality()).label : currentTrackLabel(currentTrack);
      setPlayerStatus(mode, detail, {
        activeTrack: currentTrack,
        pendingTrack: state.qualitySwitch.active ? currentTrack : null,
        reason: 'audio-canplay',
      });
      if(!state.qualitySwitch.active) hideQualitySwitchFeedback();
    }
  });

  audio.addEventListener('timeupdate', ()=>{
    if(!audio.duration || !isFinite(audio.duration)) return;
    const v = Math.floor((audio.currentTime / audio.duration) * 1000);
    seek.value = String(v);
    $('tcur').textContent = fmtTime(audio.currentTime);
    $('tdur').textContent = fmtTime(audio.duration);
  });

  seek.addEventListener('input', ()=>{
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
    state.playing = false;
    hideQualitySwitchFeedback(true);
    setPlayIcon(ICONS.play);
    setPlayerStatus('loading', '自动前进到下一首', {
      activeTrack: state.queue[state.idx],
      pendingTrack: state.queue[nextIndex()],
      reason: 'ended-next',
    });
    next().catch((err)=>{
      handlePlayerError(err, {
        activeTrack: state.queue[state.idx],
        fallbackMode: state.queue[state.idx] ? 'paused' : 'idle',
        reason: 'ended-next-error',
        settleDetail: currentTrackLabel(state.queue[state.idx]),
        logLabel: 'next failed',
      });
    });
  });
  audio.addEventListener('pause', ()=>{
    if(audio.ended) return;
    state.playing = false;
    setPlayIcon(ICONS.play);
    if(consumeAudioEventGate('pause')) return;
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
    state.playing = true;
    setPlayIcon(ICONS.pause);
    if(consumeAudioEventGate('play')) return;
    const currentTrack = normTrack(state.queue[state.idx]);
    if(state.qualitySwitch.active){
      setPlayerStatus('switching-quality', describeQuality(audio.dataset.fmt || currentQuality()).label, {
        activeTrack: currentTrack,
        pendingTrack: currentTrack,
        reason: 'audio-play-quality-switch',
      });
      return;
    }
    setPlayerStatus('playing', currentTrackLabel(currentTrack), {
      activeTrack: currentTrack,
      reason: 'audio-play',
    });
  });
  audio.addEventListener('error', ()=>{
    const currentTrack = normTrack(state.queue[state.idx]);
    const fallbackMode = audio.src ? 'paused' : 'idle';
    handlePlayerError(new Error(currentTrack ? `${currentTrack.title} 加载失败` : '音频流加载失败'), {
      activeTrack: currentTrack,
      fallbackMode,
      reason: 'audio-error',
      settleDetail: currentTrack ? currentTrackLabel(currentTrack) : 'Idle',
      logLabel: 'audio error',
    });
  });
}
