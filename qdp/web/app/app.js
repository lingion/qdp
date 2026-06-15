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
  const toggle = $('mobileSidebarToggle');
  const overlay = $('mobileSidebarOverlay');
  const mobileOpen = state.mobileSidebarOpen && isMobileLayout();
  if(toggle) toggle.setAttribute('aria-expanded', String(state.mobileSidebarOpen));
  if(overlay) overlay.setAttribute('aria-hidden', String(!mobileOpen));
  document.body.classList.toggle('mobileSidebarOpen', mobileOpen);
  if(typeof setMobileQueueDrawer === 'function' && isMobileLayout()){
    setMobileQueueDrawer(mobileOpen);
  }
  if(!mobileOpen) resetMobileDrawerTouch();
}

// ═══ Mobile Drawer Control (left nav + right queue) ═══
let mobileNavDrawerOpen = false;
let mobileQueueDrawerOpen = false;

function getMobileNavDrawer(){
  return document.querySelector('.sidebar-nav');
}

function setMobileNavDrawer(open){
  if(!isMobileLayout()) return;
  mobileNavDrawerOpen = !!open;
  const drawer = getMobileNavDrawer();
  const backdrop = $('mobileDrawerBackdrop');
  const menuBtn = $('mobileMenuBtn');
  if(drawer){
    drawer.classList.toggle('is-open', mobileNavDrawerOpen);
    drawer.setAttribute('aria-hidden', String(!mobileNavDrawerOpen));
  }
  if(backdrop){
    backdrop.classList.toggle('is-open', mobileNavDrawerOpen);
    backdrop.setAttribute('aria-hidden', String(!mobileNavDrawerOpen));
  }
  if(menuBtn) menuBtn.setAttribute('aria-expanded', String(mobileNavDrawerOpen));
  // If opening nav, close queue drawer
  if(mobileNavDrawerOpen) setMobileQueueDrawer(false);
  document.body.classList.toggle('mobileNavOpen', mobileNavDrawerOpen);
}

function setMobileQueueDrawer(open){
  if(!isMobileLayout()) return;
  mobileQueueDrawerOpen = !!open;
  const drawer = $('sidebar');
  const backdrop = $('queueDrawerBackdrop');
  const qBtn = $('mobileQueueBtn');
  if(drawer){
    drawer.classList.toggle('is-open', mobileQueueDrawerOpen);
    drawer.setAttribute('aria-hidden', String(!mobileQueueDrawerOpen));
  }
  if(backdrop){
    backdrop.classList.toggle('is-open', mobileQueueDrawerOpen);
    backdrop.setAttribute('aria-hidden', String(!mobileQueueDrawerOpen));
  }
  if(qBtn) qBtn.setAttribute('aria-expanded', String(mobileQueueDrawerOpen));
  // If opening queue, close nav drawer
  if(mobileQueueDrawerOpen) setMobileNavDrawer(false);
}

function closeAllMobileDrawers(){
  setMobileNavDrawer(false);
  setMobileQueueDrawer(false);
}

function syncMobileTopbarTitle(){
  const titleEl = $('mobileTopbarTitle');
  const h1 = $('contentTitle');
  if(titleEl && h1) titleEl.textContent = h1.textContent.trim() || '发现';
}

// Auto-sync mobile topbar whenever #contentTitle text changes (e.g. search results, discover)
(function(){
  const ct = $('contentTitle');
  if(ct){
    new MutationObserver(() => {
      const mt = $('mobileTopbarTitle');
      if(mt) mt.textContent = ct.textContent.trim() || '发现';
    }).observe(ct, { childList: true, subtree: true });
  }
})();

function syncQueueBadge(){
  const badge = $('queueCountBadge');
  if(!badge) return;
  const len = Array.isArray(state.queue) ? state.queue.length : 0;
  if(len > 0){
    badge.hidden = false;
    badge.textContent = String(len);
  } else {
    badge.hidden = true;
  }
}

function hideSearchHistoryPanel(){
  const panel = $('searchHistoryPanel');
  if(panel) panel.classList.add('hidden');
}
function syncSearchInputs(source = 'desktop'){
  const desktop = $('q');
  const mobile = $('mobileQ');
  if(!desktop || !mobile) return;
  if(source === 'mobile') desktop.value = mobile.value;
  else mobile.value = desktop.value;
  const desktopClear = $('searchClear');
  if(desktopClear) desktopClear.style.display = (desktop.value || '').trim() ? 'inline-flex' : 'none';
  const mobileClear = $('mobileSearchClear');
  if(mobileClear) mobileClear.style.display = (mobile.value || '').trim() ? 'inline-flex' : 'none';
}
function renderSearchHistoryPanel(){
  const panel = $('searchHistoryPanel');
  if(!panel) return;
  const items = Array.isArray(state.searchHistory) ? state.searchHistory : [];
  if(!items.length){
    panel.innerHTML = '';
    panel.classList.add('hidden');
    return;
  }
  panel.innerHTML = `<div class="searchHistoryHeader"><span>搜索历史</span><button type="button" class="searchHistoryClearBtn" id="searchHistoryClearBtn">清空</button></div>` +
    items.map((item)=>`<button type="button" class="searchHistoryItem" data-search-history-item="${esc(item)}">${esc(item)}</button>`).join('');
  panel.classList.remove('hidden');
  panel.querySelector('#searchHistoryClearBtn')?.addEventListener('click', (e)=>{
    e.stopPropagation();
    state.searchHistory = [];
    saveSearchHistory([]);
    hideSearchHistoryPanel();
  });
  panel.querySelectorAll('[data-search-history-item]').forEach((btn)=>{
    btn.addEventListener('click', ()=>{
      const q = btn.getAttribute('data-search-history-item') || '';
      $('q').value = q;
      syncSearchInputs('desktop');
      hideSearchHistoryPanel();
      search().catch((err)=>renderEmpty(`Error: ${err.message}`));
    });
  });
}
function maybeShowSearchHistoryPanel(){
  const q = ($('q')?.value || '').trim();
  if(q) return hideSearchHistoryPanel();
  renderSearchHistoryPanel();
}
// ═══ UI Bindings ═══

function handleViewportChange(){
  const mobile = isMobileLayout();
  document.body.classList.toggle('mobileLayout', mobile);
  document.body.classList.toggle('mobileSidebarOpen', mobile && state.mobileSidebarOpen);
  if(!mobile){
    setMobileSidebarOpen(false);
    setMobileSettingsOpen(false);
    closeAllMobileDrawers();
  }
  setMobileSidebarTab(state.mobileSidebarTab);
  syncSidebarSections();
  setVolumePopoverOpen(false);
  document.documentElement.style.setProperty('--app-height', `${window.innerHeight || document.documentElement.clientHeight || 0}px`);
  syncMobileTopbarTitle();
  syncQueueBadge();
}
function setDesktopSearchFocus(open){
  if(isMobileLayout()) return;
  document.body.classList.toggle('searchFocusedDesktop', !!open);
}

function bindUI(){
  const navDiscover = $('navDiscover');
  const navSearch = $('navSearch');
  const navQueue = $('navQueue');
  const navPlaylists = $('navPlaylists');

  document.querySelectorAll('.tab').forEach((b)=>{
    b.addEventListener('click', ()=>{
      clearTimeout(_searchBlurTimer);
      setActiveTab(b.dataset.type);
      const currentQuery = isMobileLayout() ? (($('mobileQ')?.value || '').trim()) : (($('q')?.value || '').trim());
      if(currentQuery){
        state.q = currentQuery;
        if(isMobileLayout()) syncSearchInputs('mobile');
      }
      document.querySelectorAll('.mobile-tab').forEach((mb)=>{
        if(mb.dataset.type === b.dataset.type) mb.classList.add('active');
        else mb.classList.remove('active');
      });
      if((state.q || currentQuery) && !$('urlMode').checked){
        setRoute({ kind: 'search', q: currentQuery || state.q, type: b.dataset.type || 'tracks' }, 'replace');
        search({ skipRoute: true, preserveHistory: true }).catch((e)=>renderEmpty(`Error: ${e.message}`));
      }
    });
  });

  // Mobile drawer triggers
  const menuBtn = $('mobileMenuBtn');
  if(menuBtn) menuBtn.addEventListener('click', ()=> setMobileNavDrawer(!mobileNavDrawerOpen));
  const queueBtn = $('mobileQueueBtn');
  if(queueBtn) queueBtn.addEventListener('click', ()=> setMobileQueueDrawer(!mobileQueueDrawerOpen));
  const navBackdrop = $('mobileDrawerBackdrop');
  if(navBackdrop) navBackdrop.addEventListener('click', ()=> setMobileNavDrawer(false));
  const qBackdrop = $('queueDrawerBackdrop');
  if(qBackdrop) qBackdrop.addEventListener('click', ()=> setMobileQueueDrawer(false));
  // Mobile drawer nav items
  document.querySelectorAll('.mobileNavItem, .sidebar-nav .navItem').forEach((a)=>{
    a.addEventListener('click', ()=>{
      const target = a.dataset.target;
      if(target === 'discover'){ $('navDiscover')?.click(); }
      else if(target === 'search'){ $('navSearch')?.click(); }
      else if(target === 'playlists'){ $('navPlaylists')?.click(); }
      else if(target === 'account'){ $('avatarBtn')?.click(); }
      setMobileNavDrawer(false);
    });
  });
  // Mobile queue input syncs into main input
  const qMobile = $('qMobile');
  if(qMobile){
    qMobile.addEventListener('input', ()=>{
      const main = $('q');
      if(main) main.value = qMobile.value;
      // Trigger same X toggle logic
      const clearBtn = $('searchClear');
      if(clearBtn) clearBtn.style.display = (qMobile.value || '').trim() ? 'inline-flex' : 'none';
    });
    qMobile.addEventListener('keydown', (e)=>{
      if(e.key === 'Enter'){
        e.preventDefault();
        const main = $('q');
        if(main) main.value = qMobile.value;
        setMobileNavDrawer(false);
        $('go')?.click();
      }
    });
  }

  $('go').addEventListener('click', ()=>{
    syncSearchInputs('desktop');
    hideSearchHistoryPanel();
    const q = ($('q').value || '').trim();
    if(q){
      search().catch((e)=>renderEmpty(`Error: ${e.message}`));
    }else{
      loadDiscoverRandom(true).then(()=>setRoute({ kind: 'discover' })).catch((e)=>renderEmpty(`Error: ${e.message}`));
    }
  });
  $('q').addEventListener('keydown', (e)=>{ if(e.key==='Enter'){ syncSearchInputs('desktop'); hideSearchHistoryPanel(); search().catch((err)=>renderEmpty(`Error: ${err.message}`)); } });
  $('mobileQ')?.addEventListener('keydown', (e)=>{ if(e.key==='Enter'){ syncSearchInputs('mobile'); hideSearchHistoryPanel(); search().catch((err)=>renderEmpty(`Error: ${err.message}`)); } });

  // Show/hide search type tabs and settings gear on input focus/blur
  let _searchBlurTimer = 0;
  $('q').addEventListener('focus', ()=>{
    clearTimeout(_searchBlurTimer);
    const tabs = $('searchTypeTabs');
    const gear = $('mobileSettingsBtn');
    const mobileTabs = $('mobileSearchTypeTabs');
    if(tabs && !isMobileLayout()) tabs.classList.remove('hidden');
    if(gear) gear.classList.remove('hidden');
    if(mobileTabs && isMobileLayout()) mobileTabs.classList.remove('hidden');
    setDesktopSearchFocus(true);
    maybeShowSearchHistoryPanel();
  });
  $('mobileQ')?.addEventListener('focus', ()=>{
    clearTimeout(_searchBlurTimer);
    $('mobileSearchTypeTabs')?.classList.remove('hidden');
    syncSearchInputs('mobile');
  });
  $('q').addEventListener('blur', ()=>{
    _searchBlurTimer = setTimeout(()=>{
      const tabs = $('searchTypeTabs');
      const gear = $('mobileSettingsBtn');
      const mobileTabs = $('mobileSearchTypeTabs');
      if(tabs) tabs.classList.add('hidden');
      if(gear) gear.classList.add('hidden');
      if(mobileTabs) mobileTabs.classList.add('hidden');
      setDesktopSearchFocus(false);
      hideSearchHistoryPanel();
    }, 200);
  });
  $('mobileQ')?.addEventListener('blur', ()=>{
    _searchBlurTimer = setTimeout(()=> $('mobileSearchTypeTabs')?.classList.add('hidden'), 200);
  });

  // Search type tabs: focus-aware visibility
  const searchTypeTabs = $('searchTypeTabs');
  function updateGoButton(){
    const q = ($('q').value || '').trim();
    const goBtn = $('go');
    goBtn.textContent = q ? '搜索' : '发现';
    goBtn.classList.toggle('primary', !!q);
  }
  $('q').addEventListener('input', ()=>{
    syncSearchInputs('desktop');
    updateGoButton();
    maybeShowSearchHistoryPanel();
  });
  $('mobileQ')?.addEventListener('input', ()=>{
    syncSearchInputs('mobile');
    state.q = ($('mobileQ').value || '').trim();
    updateGoButton();
  });
  $('searchClear')?.addEventListener('click', ()=>{
    $('q').value = '';
    syncSearchInputs('desktop');
    $('q').focus();
    updateGoButton();
    maybeShowSearchHistoryPanel();
  });
  $('mobileSearchClear')?.addEventListener('click', ()=>{
    $('mobileQ').value = '';
    syncSearchInputs('mobile');
    $('mobileQ').focus();
    updateGoButton();
  });
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
  if(navDiscover) navDiscover.addEventListener('click', async ()=>{
    hideSearchHistoryPanel();
    if(($('q').value || '').trim()){
      setRoute({ kind: 'search', q: ($('q').value || '').trim(), type: state.type || 'tracks' });
      await search({ replaceRoute: true, preserveHistory: true });
    }else{
      setRoute({ kind: 'discover' });
      await loadDiscoverRandom(true);
    }
  });
  if(navSearch) navSearch.addEventListener('click', async ()=>{
    hideSearchHistoryPanel();
    setRoute({ kind: 'search', q: ($('q').value || '').trim(), type: state.type || 'tracks' });
    await search({ replaceRoute: true, preserveHistory: true });
  });
  if(navQueue) navQueue.addEventListener('click', ()=>{
    setRoute({ kind: 'queue' });
    state.activeSidePanel = 'queue';
    state.sidebarSections.queue = true;
    syncSidebarSections();
    if(isMobileLayout()) setMobileQueueDrawer(true);
    else {
      const panel = $('sidebar');
      if(panel) panel.classList.add('open');
    }
  });
  if(navPlaylists) navPlaylists.addEventListener('click', ()=>{
    setRoute({ kind: 'playlists' });
    state.activeSidePanel = 'playlists';
    state.sidebarSections.playlists = true;
    syncSidebarSections();
    if(isMobileLayout()) setMobileQueueDrawer(true);
    else {
      const panel = $('sidebar');
      if(panel) panel.classList.add('open');
    }
  });
  $('backTop').addEventListener('click', goBack);
  const desktopBackBtn = $('desktopBackBtn');
  if(desktopBackBtn) desktopBackBtn.addEventListener('click', goBack);
  const dockMenuBtn = $('dockMenuBtn');
  if(dockMenuBtn) dockMenuBtn.addEventListener('click', ()=>{
    if(isMobileLayout()){
      setMobileSidebarOpen(!state.mobileSidebarOpen);
    } else {
      const panel = $('sidebar');
      if(panel){
        if(panel.classList.contains('open')){
          panel.classList.remove('open');
          state.activeSidePanel = null;
          syncSidebarSections();
        } else {
          panel.classList.add('open');
          if(!state.activeSidePanel){
            state.activeSidePanel = 'queue';
            state.sidebarSections.queue = true;
            syncSidebarSections();
          }
        }
      }
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
  const muteOld = $('mute');
  if(muteOld) muteOld.addEventListener('click', (e)=>{ e.stopPropagation(); toggleVolumePopover(); });
  const muteBtn = $('volumeMuteToggle');
  if(muteBtn) muteBtn.addEventListener('click', (e)=>{ e.stopPropagation(); toggleMute(); });
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
    // Close sidebar on outside click (desktop)
    const sidebar = $('sidebar');
    const sidebarNav = e.target.closest('.sidebar-nav');
    if(sidebar && sidebar.classList.contains('open') && !isMobileLayout() && !sidebarNav){
      const dockMenuBtn = $('dockMenuBtn');
      if(!sidebar.contains(e.target) && e.target !== dockMenuBtn && !(dockMenuBtn && dockMenuBtn.contains(e.target))){
        sidebar.classList.remove('open');
        state.activeSidePanel = null;
        syncSidebarSections();
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
  initImageFallback();
  paintIcons(document);

  // Check for search query in URL params
  const urlParams = new URLSearchParams(location.search);
  const searchQ = urlParams.get('q');
  const albumId = urlParams.get('album');
  if(searchQ){
    $('q').value = searchQ;
    // Set clear button visibility directly
    const clearBtn = $('searchClear');
    if(clearBtn){
      clearBtn.hidden = false;
      clearBtn.style.display = 'inline-flex';
    }
    // Also dispatch a synthetic input event so any other input-driven UI (e.g., go button) stays in sync
    $('q').dispatchEvent(new Event('input', { bubbles: true }));
  }
  if(albumId){
    // will be triggered after init completes
  }
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

  if(location.pathname !== '/app/' && location.pathname !== '/app'){
    await restoreRouteFromLocation();
    return;
  }
  if(!state.queue.length && !($('q').value || '').trim()){
    // Check for deep-link hash before loading discover
    const h = location.hash.slice(1);
    const params = new URLSearchParams(location.search);
    const deepId = params.get('album') || params.get('artist') || params.get('playlist');
    const deepType = params.get('album') ? 'album' : (params.get('artist') ? 'artist' : (params.get('playlist') ? 'playlist' : ''));
    if(deepId && deepType){
      console.debug('[main] deep-link query param detected:', deepType, deepId);
      setTimeout(()=>{
        if(deepType === 'album') openAlbum(deepId);
        else if(deepType === 'artist') openArtist(deepId);
        else if(deepType === 'playlist') openPlaylist(deepId);
      }, 200);
    } else if(h.startsWith('/album/') || h.startsWith('/artist/') || h.startsWith('/playlist/')){
      console.debug('[main] deep-link hash detected, skipping discover');
      setTimeout(()=>{
        const id = h.split('/')[2];
        if(h.startsWith('/album/')) openAlbum(id);
        else if(h.startsWith('/artist/')) openArtist(id);
        else if(h.startsWith('/playlist/')) openPlaylist(id);
      }, 200);
    } else {
      console.debug('[main] loading discover random...');
      try{
        const albums = await loadDiscoverRandom();
        console.debug('[main] discover loaded', albums?.length, 'albums');
        if(!albums?.length){
          $('results').innerHTML = '<div class="empty">推荐专辑为空。搜索试试？</div>';
        }
      }catch(err){
        console.error('[main] discover failed', err);
        $('results').innerHTML = '<div class="empty">推荐加载失败：' + esc(err.message) + '</div>';
      }
    }
  } else {
    console.debug('[main] skipping discover, queue or search active');
  }

  // Handle deep-link search/album after all init is done
  if(searchQ){
    console.debug('[main] executing deep-link search:', searchQ);
    try{ await search(); }catch(err){ console.error('[main] deep-link search failed', err); }
  } else if(albumId){
    console.debug('[main] executing deep-link album:', albumId);
    try{ await openAlbum(albumId); }catch(err){ console.error('[main] deep-link album failed', err); }
  }
}

if(!window.__QDP_SKIP_BOOT__){
  main();
}

// ── Hash-based deep linking (manual nav) ──
// Only trigger on actual hash changes, not on initial load
window.addEventListener('hashchange', ()=>{
  const h = location.hash.slice(1);
  if(h.startsWith('/album/')){
    const id = h.split('/')[2];
    if(id) openAlbum(id);
  } else if(h.startsWith('/artist/')){
    const id = h.split('/')[2];
    if(id) openArtist(id);
  } else if(h.startsWith('/playlist/')){
    const id = h.split('/')[2];
    if(id) openPlaylist(id);
  }
});

window.addEventListener('popstate', ()=>{
  restoreRouteFromLocation().catch((err)=>console.error('route restore failed', err));
});
