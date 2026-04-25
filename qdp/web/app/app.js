// Split from legacy app.js for lower-risk browser-native loading.

// ═══ Keyboard Helpers ═══

function shouldIgnoreSpaceToggle(target){
  if(!target) return false;
  const tag = String(target.tagName || '').toLowerCase();
  if(['input', 'textarea', 'select', 'button'].includes(tag)) return true;
  if(target.isContentEditable) return true;
  return false;
}
// ═══ Mobile Layout ═══

function isMobileLayout(){
  return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`).matches;
}
// Intentional file-scoped global: used across bindUI() and keyboard/click handlers in this file
let mobileSettingsOpen = false;
function setMobileSettingsOpen(open){
  mobileSettingsOpen = !!open;
  const meta = document.querySelector('.topbarMetaInline');
  const backdrop = $('mobileSettingsBackdrop');
  if(meta) meta.classList.toggle('mobileSettingsOpen', mobileSettingsOpen);
  if(backdrop){
    backdrop.classList.toggle('open', mobileSettingsOpen);
    backdrop.setAttribute('aria-hidden', String(!mobileSettingsOpen));
  }
  if(mobileSettingsOpen){
    const mq = $('qualitySelectMobile');
    if(mq) mq.value = String(currentQuality());
    const mv = $('appVersionMobile');
    if(mv) mv.textContent = appVersionText();
    loadCacheStats();
  }
}
function toggleMobileSettings(force){
  setMobileSettingsOpen(typeof force === 'boolean' ? force : !mobileSettingsOpen);
}
// ═══ App Version ═══

function appVersionText(){
  const version = runtimeVersion || APP_VERSION;
  return version ? `v${version}` : `v${APP_VERSION_LOADING}`;
}
function syncAppVersion(){
  const text = appVersionText();
  const node = $('appVersion');
  if(node) node.textContent = text;
  const mobile = $('appVersionMobile');
  if(mobile) mobile.textContent = text;
}
async function loadMeta(){
  const meta = await api('/api/meta');
  runtimeVersion = String(meta?.version || meta?.web_player_version || '').trim();
  syncAppVersion();
  return meta;
}
// ═══ Mobile Sidebar ═══

function setMobileSidebarTab(tab){
  const nextTab = tab === 'playlists' ? 'playlists' : 'queue';
  state.mobileSidebarTab = nextTab;
  const sidebar = $('sidebar');
  if(sidebar) sidebar.dataset.mobileTab = nextTab;
  ['queue', 'playlists'].forEach((name)=>{
    const btn = name === 'queue' ? $('mobileTabQueue') : $('mobileTabPlaylists');
    if(!btn) return;
    const active = name === nextTab;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', String(active));
  });
}
function resetMobileDrawerTouch(){
  const touch = state.mobileDrawerTouch;
  touch.tracking = false;
  touch.startY = 0;
  touch.currentY = 0;
  touch.deltaY = 0;
  touch.engaged = false;
  touch.pointerId = null;
  const sidebar = $('sidebar');
  if(sidebar) sidebar.style.removeProperty('--mobile-drawer-drag-offset');
}
function canStartMobileDrawerSwipe(target){
  if(!target) return false;
  const scrollRoot = target.closest('.queue, .playlists');
  if(scrollRoot && scrollRoot.scrollTop > MOBILE_DRAWER_SCROLL_GUARD) return false;
  return true;
}
function onMobileDrawerTouchStart(e){
  if(!isMobileLayout() || !state.mobileSidebarOpen) return;
  const touchPoint = e.changedTouches && e.changedTouches[0];
  if(!touchPoint || !canStartMobileDrawerSwipe(e.target)){
    resetMobileDrawerTouch();
    return;
  }
  const touch = state.mobileDrawerTouch;
  touch.tracking = true;
  touch.startY = touchPoint.clientY;
  touch.currentY = touchPoint.clientY;
  touch.deltaY = 0;
  touch.engaged = false;
  touch.pointerId = touchPoint.identifier;
}
function onMobileDrawerTouchMove(e){
  const touch = state.mobileDrawerTouch;
  if(!touch.tracking || !isMobileLayout() || !state.mobileSidebarOpen) return;
  const touchPoint = Array.from(e.changedTouches || []).find((item)=>item.identifier === touch.pointerId);
  if(!touchPoint) return;
  const deltaY = Math.max(0, touchPoint.clientY - touch.startY);
  touch.currentY = touchPoint.clientY;
  touch.deltaY = deltaY;
  if(deltaY <= 0) return;
  touch.engaged = true;
  const sidebar = $('sidebar');
  if(sidebar) sidebar.style.setProperty('--mobile-drawer-drag-offset', `${Math.min(deltaY, 180)}px`);
  if(deltaY > 10) e.preventDefault();
}
function onMobileDrawerTouchEnd(e){
  const touch = state.mobileDrawerTouch;
  if(!touch.tracking) return;
  const touchPoint = Array.from(e.changedTouches || []).find((item)=>item.identifier === touch.pointerId);
  if(touchPoint) touch.deltaY = Math.max(0, touchPoint.clientY - touch.startY);
  const wasEngaged = touch.engaged;
  const shouldClose = isMobileLayout() && state.mobileSidebarOpen && wasEngaged && touch.deltaY >= MOBILE_DRAWER_SWIPE_CLOSE_THRESHOLD;
  resetMobileDrawerTouch();
  if(shouldClose){
    setMobileSidebarOpen(false);
  }else if(wasEngaged){
    setMobileSidebarOpen(true);
  }
}
// ═══ Viewport ═══

function setMobileSidebarOpen(open){
  state.mobileSidebarOpen = !!open;
  const sidebar = $('sidebar');
  const toggle = $('mobileSidebarToggle');
  const overlay = $('mobileSidebarOverlay');
  const mobileOpen = state.mobileSidebarOpen && isMobileLayout();
  if(sidebar) sidebar.classList.toggle('mobileOpen', mobileOpen);
  if(toggle) toggle.setAttribute('aria-expanded', String(state.mobileSidebarOpen));
  if(overlay) overlay.setAttribute('aria-hidden', String(!mobileOpen));
  document.body.classList.toggle('mobileSidebarOpen', mobileOpen);
  if(!mobileOpen) resetMobileDrawerTouch();
}
// ═══ UI Bindings ═══

function handleViewportChange(){
  const mobile = isMobileLayout();
  document.body.classList.toggle('mobileLayout', mobile);
  document.body.classList.toggle('mobileSidebarOpen', mobile && state.mobileSidebarOpen);
  if(!mobile) setMobileSidebarOpen(false);
  if(!mobile) setMobileSettingsOpen(false);
  setMobileSidebarTab(state.mobileSidebarTab);
  syncSidebarSections();
  if(!mobile) setVolumePopoverOpen(false);
  else setVolumePopoverOpen(true);
  document.documentElement.style.setProperty('--app-height', `${window.innerHeight || document.documentElement.clientHeight || 0}px`);
}
function setDesktopSearchFocus(open){
  if(isMobileLayout()) return;
  document.body.classList.toggle('searchFocusedDesktop', !!open);
}

function bindUI(){
  document.querySelectorAll('.tab').forEach((b)=>{
    b.addEventListener('click', ()=>{
      setActiveTab(b.dataset.type);
      if(state.q && !$('urlMode').checked) search().catch((e)=>renderEmpty(`Error: ${e.message}`));
    });
  });

  $('go').addEventListener('click', ()=>{
    const q = ($('q').value || '').trim();
    if(q){
      search().catch((e)=>renderEmpty(`Error: ${e.message}`));
    }else{
      loadDiscoverRandom(true).catch((e)=>renderEmpty(`Error: ${e.message}`));
    }
  });
  $('q').addEventListener('keydown', (e)=>{ if(e.key==='Enter') search().catch((err)=>renderEmpty(`Error: ${err.message}`)); });

  // Show/hide search type tabs and settings gear on input focus/blur
  let _searchBlurTimer = 0;
  $('q').addEventListener('focus', ()=>{
    clearTimeout(_searchBlurTimer);
    const tabs = $('searchTypeTabs');
    const gear = $('mobileSettingsBtn');
    if(tabs) tabs.classList.remove('hidden');
    if(gear) gear.classList.remove('hidden');
    setDesktopSearchFocus(true);
  });
  $('q').addEventListener('blur', ()=>{
    _searchBlurTimer = setTimeout(()=>{
      const tabs = $('searchTypeTabs');
      const gear = $('mobileSettingsBtn');
      if(tabs) tabs.classList.add('hidden');
      if(gear) gear.classList.add('hidden');
      setDesktopSearchFocus(false);
    }, 200);
  });

  // Search type tabs: focus-aware visibility
  const searchTypeTabs = $('searchTypeTabs');
  function updateGoButton(){
    const q = ($('q').value || '').trim();
    const goBtn = $('go');
    goBtn.textContent = q ? '搜索' : '发现';
    goBtn.classList.toggle('primary', !!q);
  }
  $('q').addEventListener('input', updateGoButton);
  if(searchTypeTabs){
    searchTypeTabs.addEventListener('mousedown', (e)=>{ e.preventDefault(); });
  }
  updateGoButton();
  document.addEventListener('keydown', (e)=>{
    if(!e || e.defaultPrevented) return;
    const key = e.key;

    // Ctrl/Cmd+F: focus search input (always active, prevents browser find dialog)
    if(key === 'f' && (e.metaKey || e.ctrlKey)){
      e.preventDefault();
      $('q').focus();
      return;
    }

    // Space: toggle play/pause (works on both mobile and desktop)
    if(key === ' ' || e.code === 'Space'){
      if(shouldIgnoreSpaceToggle(e.target)) return;
      e.preventDefault();
      togglePlay().catch((err)=>console.error('space toggle failed', err));
      return;
    }

    // Below shortcuts only on desktop layout
    if(isMobileLayout()) return;

    // Arrow keys: prev/next track (not when input/textarea/select/contentEditable is focused,
    // and not when a range input like seek bar or volume slider is focused)
    if(key === 'ArrowLeft'){
      if(shouldIgnoreSpaceToggle(e.target)) return;
      prev();
      return;
    }
    if(key === 'ArrowRight'){
      if(shouldIgnoreSpaceToggle(e.target)) return;
      next();
      return;
    }
    // R key: toggle repeat mode
    if(key === 'r'){
      if(shouldIgnoreSpaceToggle(e.target)) return;
      toggleRepeatMode();
      return;
    }
  });
  $('backTop').addEventListener('click', goBack);
  const dockMenuBtn = $('dockMenuBtn');
  if(dockMenuBtn) dockMenuBtn.addEventListener('click', ()=>{
    if(isMobileLayout()){
      setMobileSidebarOpen(!state.mobileSidebarOpen);
    }
  });
  $('mobileSidebarToggle').addEventListener('click', ()=>setMobileSidebarOpen(!state.mobileSidebarOpen));
  $('mobileSidebarClose').addEventListener('click', ()=>setMobileSidebarOpen(false));
  $('mobileSidebarOverlay').addEventListener('click', ()=>setMobileSidebarOpen(false));
  $('mobileSettingsBtn').addEventListener('click', ()=>toggleMobileSettings());
  $('mobileSettingsBackdrop').addEventListener('click', ()=>setMobileSettingsOpen(false));
  $('qualitySelectMobile').addEventListener('change', ()=>{
    const val = Number($('qualitySelectMobile').value || 5);
    const mainSelect = $('qualitySelect');
    if(mainSelect){
      mainSelect.value = String(val);
      mainSelect.dispatchEvent(new Event('change'));
    }
  });
  $('qualitySelect').addEventListener('change', ()=>{
    const mq = $('qualitySelectMobile');
    if(mq) mq.value = String(currentQuality());
  });
  const sidebar = $('sidebar');
  sidebar.addEventListener('touchstart', onMobileDrawerTouchStart, { passive: true });
  sidebar.addEventListener('touchmove', onMobileDrawerTouchMove, { passive: false });
  sidebar.addEventListener('touchend', onMobileDrawerTouchEnd, { passive: true });
  sidebar.addEventListener('touchcancel', onMobileDrawerTouchEnd, { passive: true });
  $('mobileTabQueue').addEventListener('click', ()=>setMobileSidebarTab('queue'));
  $('mobileTabPlaylists').addEventListener('click', ()=>setMobileSidebarTab('playlists'));
  $('queueSectionToggle').addEventListener('click', ()=>toggleSidebarSection('queue'));
  $('playlistsSectionToggle').addEventListener('click', ()=>toggleSidebarSection('playlists'));
  let _resizeTimer = 0;
  const debouncedResize = ()=> {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(()=>{
      handleViewportChange();
      if(state.downloadMenu.open) positionDownloadMenu(state.downloadMenu.anchorRect);
    }, 80);
  };
  window.addEventListener('resize', debouncedResize);

  $('play').addEventListener('click', ()=>togglePlay());
  $('prev').addEventListener('click', ()=>prev());
  $('next').addEventListener('click', ()=>next());
  $('playQueue').addEventListener('click', async ()=>{
    if(!state.queue.length) return;
    if(state.idx < 0) state.idx = 0;
    try{ await playCurrent('play-queue-btn'); }catch(_e){ console.error('playQueue failed', _e); }
  });
  $('shuffle').addEventListener('click', ()=>{ toggleShuffleMode(); shuffleQueueNow(); });
  $('shuffleMain').addEventListener('click', toggleShuffleMode);
  $('repeat').addEventListener('click', toggleRepeatMode);
  $('repeatMain').addEventListener('click', toggleRepeatMode);
  $('clearQueue').addEventListener('click', ()=>clearQueue());
  $('mute').addEventListener('click', (e)=>{ e.stopPropagation(); toggleVolumePopover(); });
  $('volumeMuteToggle').addEventListener('click', (e)=>{ e.stopPropagation(); toggleMute(); });
  $('volume').addEventListener('input', (e)=>setVolume(Number(e.target.value || 0) / 100));
  $('qualitySelect').value = String(currentQuality());
  $('qualitySelect').addEventListener('change', async ()=>{
    const nextQuality = Number($('qualitySelect').value || 5);
    state.quality = nextQuality;
    safeLocalStorageSet('qdp.web.quality', String(state.quality));
    persistPlayerSession();
    state.streamCache = {};
    saveCacheMap(STREAM_CACHE_KEY, state.streamCache);
    state.prefetchedStreamIds.clear();
    clearPendingStreams();
    if($('audio')?.src && state.idx >= 0){
      await swapCurrentTrackQuality(nextQuality);
      return;
    }
    if(state.queue.length && state.idx >= 0){
      const currentTrack = state.queue[state.idx];
      prefetchAdjacentStreams(state.idx, nextQuality).catch((err)=>console.debug('prefetch after quality change failed', err));
      setPlayerStatus('paused', currentTrackLabel(currentTrack, nextQuality), {
        activeTrack: currentTrack,
        reason: 'quality-default-update',
      });
      return;
    }
    setPlayerStatus('idle', `默认音质：${describeQuality(nextQuality).label}`, { reason: 'quality-default-idle' });
  });
  $('newPlaylist').addEventListener('click', ()=>promptCreatePlaylist());
  $('exportAllPlaylists').addEventListener('click', exportAllPlaylists);
  $('importPlaylists').addEventListener('click', ()=>$('playlistImportInput').click());
  $('playlistImportInput').addEventListener('change', async (e)=>{
    const file = e.target.files && e.target.files[0];
    if(!file) return;
    try{
      await importPlaylistsFromFile(file, { mode: 'merge' });
      showToast('歌单已导入', 'success');
    }catch(err){
      showToast(`导入失败：${err.message}`, 'error');
    }finally{
      e.target.value = '';
    }
  });
  $('accountSelect').addEventListener('change', (e)=>switchAccount(e.target.value));
  $('clearCacheAudio').addEventListener('click', ()=>clearCacheByType('audio'));
  $('clearCacheAll').addEventListener('click', async ()=>{
    const confirmed = await showConfirmModal('清除缓存', '确认清除全部缓存？此操作不可撤销。', '清除', '取消');
    if(!confirmed) return;
    clearCacheByType('all');
  });

  const downloadMenu = $('downloadMenu');
  if(downloadMenu){
    downloadMenu.addEventListener('click', (e)=>{
      if(e.target === downloadMenu) closeDownloadMenu();
    });
  }

  // Download modal bindings
  const downloadModalConfirmBtn = $('downloadModalConfirmBtn');
  if(downloadModalConfirmBtn) downloadModalConfirmBtn.addEventListener('click', ()=>confirmDownloadModal());
  const downloadModalCancelBtn = $('downloadModalCancelBtn');
  if(downloadModalCancelBtn) downloadModalCancelBtn.addEventListener('click', ()=>cancelDownloadModal());
  const downloadModalBrowseBtn = $('downloadModalBrowseBtn');
  if(downloadModalBrowseBtn) downloadModalBrowseBtn.addEventListener('click', ()=>openBrowseDirModal());
  const downloadModalBackdrop = document.querySelector('#downloadModal .downloadModalBackdrop');
  if(downloadModalBackdrop) downloadModalBackdrop.addEventListener('click', ()=>cancelDownloadModal());

  // Browse directory sub-dialog bindings
  const browseDirConfirmBtn = $('browseDirConfirmBtn');
  if(browseDirConfirmBtn) browseDirConfirmBtn.addEventListener('click', ()=>confirmBrowseDir());
  const browseDirCancelBtn = $('browseDirCancelBtn');
  if(browseDirCancelBtn) browseDirCancelBtn.addEventListener('click', ()=>cancelBrowseDir());
  const browseDirBackdrop = document.querySelector('#browseDirModal .browseDirBackdrop');
  if(browseDirBackdrop) browseDirBackdrop.addEventListener('click', ()=>cancelBrowseDir());
  document.addEventListener('keydown', (e)=>{
    if(e.key !== 'Escape') return;
    let handled = false;
    // Close browse dir sub-dialog first if open
    const browseDirModal = $('browseDirModal');
    if(browseDirModal && !browseDirModal.classList.contains('hidden')){
      cancelBrowseDir();
      handled = true;
    } else if(state.downloadMenu.open || _downloadModalState.open){
      closeDownloadMenu();
      handled = true;
    }
    if(state.volumePopoverOpen){ setVolumePopoverOpen(false); handled = true; }
    if(mobileSettingsOpen){ setMobileSettingsOpen(false); handled = true; }
    if(!handled && state.history.length > 0 && document.activeElement === document.body) goBack();
  });
  document.addEventListener('click', (e)=>{
    if(state.volumePopoverOpen){
      const volumeWrap = e.target.closest('.volumeDockWrap');
      if(!volumeWrap) setVolumePopoverOpen(false);
    }
    if(mobileSettingsOpen){
      const settingsBtn = e.target.closest('#mobileSettingsBtn');
      const settingsPanel = e.target.closest('.topbarMetaInline');
      const settingsBackdrop = e.target.closest('.mobileSettingsBackdrop');
      if(!settingsBtn && !settingsPanel && !settingsBackdrop){
        setMobileSettingsOpen(false);
      }
    }
    if(!state.downloadMenu.open) return;
    const card = $('downloadMenuCard');
    if(card?.contains(e.target)) return;
    const trigger = e.target.closest('button, a');
    if(trigger && trigger.querySelector?.('[data-icon="download"]')) return;
    closeDownloadMenu();
  });
  document.addEventListener('visibilitychange', ()=>{
    if(document.visibilityState !== 'visible') return;
    if(!state.playing || state.idx < 0) return;
    const currentTrack = normTrack(state.queue[state.idx]);
    if(!currentTrack?.id) return;
    const audio = $('audio');
    if(!audio) return;
    const staleKey = `${currentTrack.id}:${currentQuality()}`;
    if(streamCacheAge(staleKey) >= STREAM_STALE_MS){
      console.debug('[visibilitychange] stream stale, refreshing');
      const currentTime = audio.currentTime;
      getTrackStream(currentTrack.id, currentQuality()).then((freshStream)=>{
        if(!freshStream?.url) return;
        if(!state.playing || normTrack(state.queue[state.idx])?.id !== currentTrack.id) return;
        audio.src = freshStream.url;
        audio.addEventListener('loadedmetadata', ()=>{ audio.currentTime = currentTime; }, { once: true });
      }).catch((_err)=>{});
    }
  });

  document.addEventListener('pointerdown', (e)=>{
    if(isMobileLayout()) return;
    const inSearch = e.target && e.target.closest && e.target.closest('.topbarSearchPanel');
    if(!inSearch) setDesktopSearchFocus(false);
  });
}

// ═══ Test Hooks ═══

if(new URLSearchParams(location.search).has('debug') || localStorage.getItem('qdp.debug') === '1'){
window.__qdpTestHooks = {
  createPlaylistRecord,
  choosePlaylistForTracks,
  triggerBulkDownload,
  formatAudioSpec,
  renamePlaylistRecord,
  deletePlaylistRecord,
  addTrackToPlaylistRecord,
  removeTrackFromPlaylistRecord,
  reorderPlaylistTracksRecord,
  exportPlaylistsPayload,
  mergeImportedPlaylists,
  normalizePlaylistTrack,
  loadPlaylists,
  savePlaylists,
  getCachedMapValue,
  setCachedMapValue,
  currentQuality,
  queueDownloadHref,
  getTrackStream,
  swapCurrentTrackQuality,
  openDownloadMenu,
  closeDownloadMenu,
  reorderQueueItems,
  commitQueueReorder,
  removeQueueItem,
  clearQueue,
  exportPlaylistById,
  shouldIgnoreSpaceToggle,
  isMobileLayout,
  setMobileSidebarTab,
  setMobileSidebarOpen,
  trackOccurrenceKey,
  findTrackIndexByOccurrence,
  syncQueueFromPlaylistContext,
  queueContextSourceLabel,
  getUiFlags,
  queuePresentationState,
  playerUiSnapshot,
  transitionPlayerUi,
  navigateQueue,
  setVolume,
  toggleMute,
  toggleVolumePopover,
  setSidebarSection,
  toggleSidebarSection,
  isHiResSource,
  buildQueueContext,
  loadDiscoverRandom,
  persistPlayerSession,
  restorePersistedPlayerSession,
  preferredTrackDownloadName,
  handlePlayerError,
  __state: state,
  __appVersion: APP_VERSION,
  __appVersionText: appVersionText,
  __normalizePlayerUiMode: normalizePlayerUiMode,
  __setQueue(tracks, idx = 0, context = null){ queueFromTracks(tracks, idx, context); },
  __next: next,
  __prev: prev,
  __nextIndex: nextIndex,
  toggleRepeatMode,
  syncRepeatUi,
  showToast,
};
}

// ═══ Bootstrap ═══

async function main(){
  /* Ensure volume is never stuck at 0 / muted on launch (physical volume button may be broken) */
  if(state.muted || state.volume <= 0){
    state.muted = false;
    state.volume = state.lastNonZeroVolume || 1;
    persistVolumeState();
  }
  applyVolumeToAudio();
  syncVolumeUi();
  syncAppVersion();
  bindUI();
  bindPlayer();
  syncSidebarSections();
  handleViewportChange();
  $('go').textContent = '发现';
  restorePersistedPlayerSession({ render: false });
  renderQueue();
  renderPlaylists();
  try{
    await loadMeta();
  }catch(err){
    console.warn('failed to load /api/meta', err);
  }
  await loadAccounts();
  await loadMe();
  loadCacheStats();
  // Pre-load default download path so bulk downloads don't land in cwd
  fetchDefaultDownloadPath().then((p)=>{ if(p) _downloadModalState.defaultPath = p; }).catch(()=>{});
  if(!state.queue.length && !($('q').value || '').trim()){
    await loadDiscoverRandom();
  }
}

if(!window.__QDP_SKIP_BOOT__){
  main();
}
