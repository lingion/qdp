// Split from legacy app.js for lower-risk browser-native loading.

function shouldIgnoreSpaceToggle(target){
  if(!target) return false;
  const tag = String(target.tagName || '').toLowerCase();
  if(['input', 'textarea', 'select', 'button'].includes(tag)) return true;
  if(target.isContentEditable) return true;
  return false;
}
function isMobileLayout(){
  return window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`).matches;
}
function appVersionText(){
  const version = runtimeVersion || APP_VERSION;
  return version ? `v${version}` : `v${APP_VERSION_LOADING}`;
}
function syncAppVersion(){
  const node = $('appVersion');
  if(node) node.textContent = appVersionText();
}
async function loadMeta(){
  const meta = await api('/api/meta');
  runtimeVersion = String(meta?.version || meta?.web_player_version || '').trim();
  syncAppVersion();
  return meta;
}
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
function handleViewportChange(){
  const mobile = isMobileLayout();
  document.body.classList.toggle('mobileLayout', mobile);
  document.body.classList.toggle('mobileSidebarOpen', mobile && state.mobileSidebarOpen);
  if(!mobile) setMobileSidebarOpen(false);
  setMobileSidebarTab(state.mobileSidebarTab);
  syncSidebarSections();
  if(!mobile) setVolumePopoverOpen(false);
  document.documentElement.style.setProperty('--app-height', `${window.innerHeight || document.documentElement.clientHeight || 0}px`);
}
function bindUI(){
  document.querySelectorAll('.tab').forEach((b)=>{
    b.addEventListener('click', ()=>{
      setActiveTab(b.dataset.type);
      if(state.q && !$('urlMode').checked) search().catch((e)=>renderEmpty(`Error: ${e.message}`));
    });
  });

  $('go').addEventListener('click', ()=>search().catch((e)=>renderEmpty(`Error: ${e.message}`)));
  $('q').addEventListener('keydown', (e)=>{ if(e.key==='Enter') search().catch((err)=>renderEmpty(`Error: ${err.message}`)); });
  document.addEventListener('keydown', (e)=>{
    if(!e || e.defaultPrevented) return;
    if(isMobileLayout()) return;
    if(e.key !== ' ' && e.code !== 'Space') return;
    if(shouldIgnoreSpaceToggle(e.target)) return;
    e.preventDefault();
    togglePlay().catch((err)=>console.error('space toggle failed', err));
  });
  $('backTop').addEventListener('click', goBack);
  $('mobileSidebarToggle').addEventListener('click', ()=>setMobileSidebarOpen(!state.mobileSidebarOpen));
  $('mobileSidebarClose').addEventListener('click', ()=>setMobileSidebarOpen(false));
  $('mobileSidebarOverlay').addEventListener('click', ()=>setMobileSidebarOpen(false));
  const sidebar = $('sidebar');
  sidebar.addEventListener('touchstart', onMobileDrawerTouchStart, { passive: true });
  sidebar.addEventListener('touchmove', onMobileDrawerTouchMove, { passive: false });
  sidebar.addEventListener('touchend', onMobileDrawerTouchEnd, { passive: true });
  sidebar.addEventListener('touchcancel', onMobileDrawerTouchEnd, { passive: true });
  $('mobileTabQueue').addEventListener('click', ()=>setMobileSidebarTab('queue'));
  $('mobileTabPlaylists').addEventListener('click', ()=>setMobileSidebarTab('playlists'));
  $('queueSectionToggle').addEventListener('click', ()=>toggleSidebarSection('queue'));
  $('playlistsSectionToggle').addEventListener('click', ()=>toggleSidebarSection('playlists'));
  window.addEventListener('resize', handleViewportChange);

  $('play').addEventListener('click', ()=>togglePlay());
  $('prev').addEventListener('click', ()=>prev());
  $('next').addEventListener('click', ()=>next());
  $('shuffle').addEventListener('click', ()=>{ toggleShuffleMode(); shuffleQueueNow(); });
  $('shuffleMain').addEventListener('click', toggleShuffleMode);
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
      alert('Playlists imported.');
    }catch(err){
      alert(`导入失败：${err.message}`);
    }finally{
      e.target.value = '';
    }
  });
  $('accountSelect').addEventListener('change', (e)=>switchAccount(e.target.value));

  const downloadMenu = $('downloadMenu');
  if(downloadMenu){
    downloadMenu.addEventListener('click', (e)=>{
      if(e.target === downloadMenu) closeDownloadMenu();
    });
  }
  document.addEventListener('keydown', (e)=>{
    if(e.key === 'Escape' && state.downloadMenu.open){
      closeDownloadMenu();
    }
    if(e.key === 'Escape' && state.volumePopoverOpen){
      setVolumePopoverOpen(false);
    }
  });
  document.addEventListener('click', (e)=>{
    if(state.volumePopoverOpen){
      const volumeWrap = e.target.closest('.volumeDockWrap');
      if(!volumeWrap) setVolumePopoverOpen(false);
    }
    if(!state.downloadMenu.open) return;
    const card = $('downloadMenuCard');
    if(card?.contains(e.target)) return;
    const trigger = e.target.closest('button, a');
    if(trigger && trigger.querySelector?.('[data-icon="download"]')) return;
    closeDownloadMenu();
  });
  window.addEventListener('resize', ()=>{
    if(state.downloadMenu.open){
      state.downloadMenu.mobile = isMobileLayout();
      $('downloadMenu')?.classList.toggle('mobileSheet', state.downloadMenu.mobile);
      buildDownloadMenuContent(state.downloadMenu.track, state.downloadMenu.mobile);
      positionDownloadMenu(state.downloadMenu.anchorRect);
    }
  });
}

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
};

async function main(){
  syncAppVersion();
  bindUI();
  bindPlayer();
  syncSidebarSections();
  handleViewportChange();
  $('go').textContent = 'Search';
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
  if(!state.queue.length && !($('q').value || '').trim()){
    await loadDiscoverRandom();
  }
}

if(!window.__QDP_SKIP_BOOT__){
  main();
}
