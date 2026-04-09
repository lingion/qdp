#!/usr/bin/env node
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const REPO_ROOT = '/Users/lingion/Documents/qdp-main';
const WEB_APP_ROOT = path.join(REPO_ROOT, 'qdp/web/app');
const INDEX_HTML = path.join(WEB_APP_ROOT, 'index.html');

function createClassList(node) {
  const classes = new Set();
  const sync = () => { node.className = Array.from(classes).join(' '); };
  return {
    toggle(name, force){
      if(force === true){ classes.add(name); sync(); return true; }
      if(force === false){ classes.delete(name); sync(); return false; }
      if(classes.has(name)){ classes.delete(name); sync(); return false; }
      classes.add(name); sync(); return true;
    },
    add(...names){ names.forEach((name)=>classes.add(name)); sync(); },
    remove(...names){ names.forEach((name)=>classes.delete(name)); sync(); },
    contains(name){ return classes.has(name); },
  };
}

function createNode(tag = 'div') {
  const node = {
    tagName: String(tag).toUpperCase(),
    dataset: {},
    style: { setProperty(){}, removeProperty(){} },
    className: '',
    innerHTML: '',
    textContent: '',
    value: '',
    src: '',
    href: '',
    title: '',
    download: '',
    disabled: false,
    checked: false,
    files: null,
    scrollTop: 0,
    paused: true,
    ended: false,
    currentTime: 0,
    duration: 0,
    volume: 1,
    children: [],
    attributes: new Map(),
    parentNode: null,
    eventHandlers: new Map(),
    contains(target){ return this === target || this.children.includes(target); },
    appendChild(child){ child.parentNode = this; this.children.push(child); return child; },
    remove(){ if(this.parentNode) this.parentNode.children = this.parentNode.children.filter((item)=>item !== this); this.parentNode = null; },
    setAttribute(name, value){ this.attributes.set(name, String(value)); if(name === 'id') this.id = String(value); },
    getAttribute(name){ return this.attributes.get(name) || null; },
    removeAttribute(name){ this.attributes.delete(name); },
    addEventListener(name, handler){ if(!this.eventHandlers.has(name)) this.eventHandlers.set(name, []); this.eventHandlers.get(name).push(handler); },
    removeEventListener(name, handler){ if(!this.eventHandlers.has(name)) return; this.eventHandlers.set(name, this.eventHandlers.get(name).filter((fn)=>fn !== handler)); },
    dispatchEvent(evt){ (this.eventHandlers.get(evt?.type) || []).forEach((fn)=>fn(evt)); return true; },
    querySelector(){ return createNode('div'); },
    querySelectorAll(){ return []; },
    closest(){ return null; },
    click(){},
    load(){},
    play: async function(){ this.paused = false; },
    pause: function(){ this.paused = true; },
    getBoundingClientRect(){ return { left: 0, right: 0, top: 0, bottom: 0, width: 0, height: 0 }; },
  };
  node.classList = createClassList(node);
  return node;
}

function discoverScriptFiles() {
  const html = fs.readFileSync(INDEX_HTML, 'utf8');
  return Array.from(html.matchAll(/<script src="\/app\/([^"?]+)(?:\?[^"}]*)?"/g)).map((match)=>match[1]);
}

function loadApp() {
  const scriptFiles = discoverScriptFiles();
  const elements = new Map();
  const ensure = (id) => {
    if(!elements.has(id)) elements.set(id, createNode('div'));
    return elements.get(id);
  };
  [
    'qualitySelect','playerStatus','player','queue','title','subtitle','cover','audio',
    'nowSourcePill','queueSourceBadge','downloadMenu','downloadMenuCard',
    'volume','mute','volumeValue','results','q','seek','tcur','tdur','sidebar',
    'queueSectionToggle','playlistsSectionToggle','volumePopover','volumeMuteToggle',
    'mobileSidebarToggle','mobileSidebarClose','mobileSidebarOverlay','mobileTabQueue','mobileTabPlaylists',
    'play','prev','next','shuffle','shuffleMain','newPlaylist','exportAllPlaylists','importPlaylists',
    'playlistImportInput','accountSelect','backTop','go','urlMode','myPlaylists','appVersion','qualitySwitchBadge'
  ].forEach(ensure);
  ensure('qualitySelect').value = '5';
  ensure('volume').value = '100';
  ensure('q').value = '';
  ensure('urlMode').checked = false;
  ensure('play').querySelector = () => ({ dataset: {}, classList: createClassList({ className: '' }) });
  ensure('mute').querySelector = () => ({ dataset: {}, classList: createClassList({ className: '' }) });
  const audio = ensure('audio');
  audio.paused = true;
  audio.currentTime = 0;
  audio.duration = 300;
  audio.volume = 1;
  audio.play = async function(){ this.paused = false; };
  audio.pause = function(){ this.paused = true; };
  audio.load = function(){};

  const documentBody = createNode('body');
  const documentElement = createNode('html');
  const context = {
    console,
    window: {
      __QDP_SKIP_BOOT__: true,
      setTimeout,
      clearTimeout,
      matchMedia: () => ({ matches: false }),
      addEventListener(){},
      removeEventListener(){},
      innerWidth: 1440,
      innerHeight: 900,
    },
    document: {
      body: documentBody,
      documentElement,
      getElementById: ensure,
      createElement: createNode,
      querySelector(){ return createNode('div'); },
      querySelectorAll(){ return []; },
      addEventListener(){},
      removeEventListener(){},
    },
    localStorage: (()=>{
      const store = new Map();
      return {
        getItem(key){ return store.has(key) ? store.get(key) : null; },
        setItem(key, value){ store.set(key, String(value)); },
        removeItem(key){ store.delete(key); },
      };
    })(),
    sessionStorage: (()=>{
      const store = new Map();
      return {
        getItem(key){ return store.has(key) ? store.get(key) : null; },
        setItem(key, value){ store.set(key, String(value)); },
        removeItem(key){ store.delete(key); },
      };
    })(),
    fetch: async () => ({ ok: true, headers: { get(){ return 'application/json'; } }, json: async () => ({}), text: async () => '' }),
    Blob: function(parts){ this.parts = parts; },
    URL: { createObjectURL(){ return 'blob:test'; }, revokeObjectURL(){} },
    alert(){},
    confirm(){ return true; },
    prompt(){ return ''; },
    requestAnimationFrame(fn){ return fn(); },
    setTimeout,
    clearTimeout,
  };
  context.window.document = context.document;
  context.window.localStorage = context.localStorage;
  context.window.sessionStorage = context.sessionStorage;
  context.window.fetch = (...args) => context.fetch(...args);
  context.window.URL = context.URL;
  context.window.Blob = context.Blob;
  context.window.requestAnimationFrame = context.requestAnimationFrame;
  context.window.alert = context.alert;
  context.window.confirm = context.confirm;
  context.window.prompt = context.prompt;
  vm.createContext(context);
  scriptFiles.forEach((file)=>{
    const source = fs.readFileSync(path.join(WEB_APP_ROOT, file), 'utf8');
    vm.runInContext(source, context, { filename: file });
  });
  return { context, hooks: context.window.__qdpTestHooks, audio, ensure, scriptFiles };
}

function assert(condition, message) {
  if(!condition) throw new Error(message);
}

async function testPlayPauseTransition() {
  const { hooks, audio } = loadApp();
  const state = hooks.__state;
  hooks.__setQueue([{ id: 't1', title: 'Track 1', artist: 'A' }], 0, { type: 'single-track', label: '单曲队列' });
  state.playing = false;
  audio.src = '/stream?t1';
  audio.paused = true;
  await hooks.transitionPlayerUi('paused', 'Track 1 · MP3', { activeTrack: state.queue[0] });
  await hooks.transitionPlayerUi('loading', '恢复播放 · Track 1 · MP3', { activeTrack: state.queue[0], pendingTrack: state.queue[0] });
  audio.paused = false;
  await hooks.transitionPlayerUi('playing', 'Track 1 · MP3', { activeTrack: state.queue[0] });
  assert(hooks.playerUiSnapshot().mode === 'playing', 'play/pause: expected final mode=playing');
  assert(state.playerUi.pendingTrackId === '', 'play/pause: pendingTrackId should clear after playing');
  await hooks.transitionPlayerUi('paused', 'Track 1 · MP3', { activeTrack: state.queue[0] });
  assert(hooks.playerUiSnapshot().mode === 'paused', 'play/pause: expected paused mode');
}

async function testNextPrevConsistency() {
  const { hooks, context, audio } = loadApp();
  const state = hooks.__state;
  hooks.__setQueue([
    { id: 'a', title: 'A', artist: 'AA' },
    { id: 'b', title: 'B', artist: 'BB' },
    { id: 'c', title: 'C', artist: 'CC' },
  ], 0, { sourceType: 'album', sourceLabel: '来自 Album · Test' });
  context.fetch = async (url) => {
    if(String(url).includes('/api/track-url')) return { ok: true, json: async () => ({ url: `/stream/${state.queue[state.idx].id}` }), text: async () => '' };
    if(String(url).includes('/api/track?')) return { ok: true, json: async () => state.queue[state.idx], text: async () => '' };
    return { ok: true, json: async () => ({}), text: async () => '' };
  };
  context.window.fetch = context.fetch;
  audio.play = async function(){ this.paused = false; };
  await hooks.__next();
  await hooks.__next();
  await hooks.__prev();
  assert(state.idx === 1, `nav: expected idx=1, got ${state.idx}`);
  const snapshot = hooks.playerUiSnapshot();
  assert(snapshot.mode === 'playing', `nav: expected mode=playing, got ${snapshot.mode}`);
  assert(snapshot.activeTrackId === 'b', `nav: expected activeTrackId=b, got ${snapshot.activeTrackId}`);
  const queueState = hooks.queuePresentationState();
  assert(queueState.currentIndex === 1, `nav: expected queue currentIndex=1, got ${queueState.currentIndex}`);
}

async function testQualitySwitchStateContract() {
  const { hooks } = loadApp();
  const state = hooks.__state;
  hooks.__setQueue([{ id: 'q1', title: 'Q1', artist: 'QA' }], 0, { sourceType: 'single-track', sourceLabel: '单曲队列' });
  hooks.transitionPlayerUi('switching-quality', 'FLAC', { activeTrack: state.queue[0], pendingTrack: state.queue[0], reason: 'quality-switch' });
  let snapshot = hooks.playerUiSnapshot();
  assert(snapshot.mode === 'switching-quality', `quality: expected switching-quality, got ${snapshot.mode}`);
  assert(snapshot.pendingTrackId === 'q1', `quality: expected pendingTrackId=q1, got ${snapshot.pendingTrackId}`);
  hooks.transitionPlayerUi('paused', 'Q1 · FLAC', { activeTrack: state.queue[0], reason: 'quality-switch-complete' });
  snapshot = hooks.playerUiSnapshot();
  assert(snapshot.mode === 'paused', `quality: expected paused after settle, got ${snapshot.mode}`);
  assert(snapshot.pendingTrackId === '', 'quality: pendingTrackId should clear after settle');
}

async function testRapidNextPrevKeepsLastIntent() {
  const { hooks, context } = loadApp();
  const state = hooks.__state;
  hooks.__setQueue([
    { id: 'n1', title: 'N1', artist: 'AA' },
    { id: 'n2', title: 'N2', artist: 'BB' },
    { id: 'n3', title: 'N3', artist: 'CC' },
  ], 0, { sourceType: 'album', sourceLabel: '来自 Album · Nav' });
  context.playCurrent = async () => { state.playing = true; return true; };
  await hooks.__next();
  await hooks.__next();
  await hooks.__prev();
  assert(state.idx === 1, `rapid nav: expected idx=1, got ${state.idx}`);
}

async function testEndedAutoNextContract() {
  const { hooks } = loadApp();
  const state = hooks.__state;
  hooks.__setQueue([
    { id: 'e1', title: 'E1', artist: 'AA' },
    { id: 'e2', title: 'E2', artist: 'BB' },
  ], 0, { sourceType: 'album', sourceLabel: '来自 Album · Ended' });
  const nextIdx = hooks.__nextIndex();
  assert(nextIdx === 1, `ended: expected next idx=1, got ${nextIdx}`);
  hooks.transitionPlayerUi('loading', '自动前进到下一首', { activeTrack: state.queue[0], pendingTrack: state.queue[1], reason: 'ended-next' });
  const snapshot = hooks.playerUiSnapshot();
  assert(snapshot.mode === 'loading', `ended: expected loading mode, got ${snapshot.mode}`);
  assert(snapshot.pendingTrackId === 'e2', `ended: expected pendingTrackId=e2, got ${snapshot.pendingTrackId}`);
}

async function testQueueReorderKeepsCurrentOccurrence() {
  const { hooks } = loadApp();
  const state = hooks.__state;
  hooks.__setQueue([
    { id: 'dup', title: 'Dup 1', artist: 'AA' },
    { id: 'x2', title: 'X2', artist: 'BB' },
    { id: 'dup', title: 'Dup 2', artist: 'CC' },
  ], 2, { sourceType: 'local-playlist', sourceLabel: '来自 Playlist · Keep', writablePlaylist: true, playlistId: 'pl-1' });
  hooks.commitQueueReorder(0, 2);
  assert(state.idx === 1, `reorder: expected current duplicate move to idx=1, got ${state.idx}`);
  assert(state.queue[state.idx].title === 'Dup 2', `reorder: expected current track to remain Dup 2, got ${state.queue[state.idx].title}`);
}

async function testVolumeMutePersistenceContract() {
  const { hooks } = loadApp();
  const state = hooks.__state;
  hooks.setVolume(0.42);
  assert(Math.abs(state.volume - 0.42) < 1e-9, `volume: expected 0.42, got ${state.volume}`);
  hooks.toggleMute();
  assert(state.muted === true, 'volume: expected muted=true after toggle');
  hooks.toggleMute();
  assert(state.muted === false, 'volume: expected muted=false after second toggle');
}

async function testQueueRestoreConsistencyContract() {
  const { hooks, ensure } = loadApp();
  hooks.__setQueue([
    { id: 'r1', title: 'Restore 1', artist: 'RA', image: 'cover-1' },
    { id: 'r2', title: 'Restore 2', artist: 'RB', image: 'cover-2' },
  ], 1, { sourceType: 'album', sourceLabel: '来自 Album · Restore' });
  hooks.__state.playing = true;
  hooks.__state.quality = 6;
  hooks.setVolume(0.35);
  hooks.persistPlayerSession();
  hooks.__state.queue = [];
  hooks.__state.idx = -1;
  hooks.__state.queueContext = null;
  hooks.restorePersistedPlayerSession();
  const queueState = hooks.queuePresentationState();
  assert(queueState.currentIndex === 1, `restore: expected idx=1, got ${queueState.currentIndex}`);
  assert(queueState.currentTrackId === 'r2', `restore: expected currentTrackId=r2, got ${queueState.currentTrackId}`);
  assert(queueState.queueLength === 2, `restore: expected queueLength=2, got ${queueState.queueLength}`);
  assert(hooks.__state.queueContext?.sourceType === 'album', 'restore: expected queueContext sourceType=album');
  assert(ensure('title').textContent === 'Restore 2', `restore: expected title=Restore 2, got ${ensure('title').textContent}`);
  assert(hooks.playerUiSnapshot().mode === 'paused', `restore: expected paused mode, got ${hooks.playerUiSnapshot().mode}`);
  assert(String(ensure('qualitySelect').value) === '6', `restore: expected quality=6, got ${ensure('qualitySelect').value}`);
}

async function testQualitySwitchPausePlayEndedChainContract() {
  const { hooks } = loadApp();
  hooks.__setQueue([
    { id: 'qc1', title: 'Chain 1', artist: 'AA' },
    { id: 'qc2', title: 'Chain 2', artist: 'BB' },
  ], 0, { sourceType: 'album', sourceLabel: '来自 Album · Chain' });
  hooks.transitionPlayerUi('switching-quality', 'FLAC', { activeTrack: hooks.__state.queue[0], pendingTrack: hooks.__state.queue[0], reason: 'quality-switch' });
  hooks.transitionPlayerUi('paused', 'Chain 1 · FLAC', { activeTrack: hooks.__state.queue[0], reason: 'quality-switch-complete' });
  hooks.transitionPlayerUi('playing', 'Chain 1 · FLAC', { activeTrack: hooks.__state.queue[0], reason: 'resume' });
  hooks.transitionPlayerUi('loading', '自动前进到下一首', { activeTrack: hooks.__state.queue[0], pendingTrack: hooks.__state.queue[1], reason: 'ended-next' });
  const snapshot = hooks.playerUiSnapshot();
  assert(snapshot.mode === 'loading', `quality-chain: expected loading mode, got ${snapshot.mode}`);
  assert(snapshot.pendingTrackId === 'qc2', `quality-chain: expected pendingTrackId=qc2, got ${snapshot.pendingTrackId}`);
}

async function testCentralizedErrorFallbackContract() {
  const { hooks } = loadApp();
  hooks.__setQueue([{ id: 'er1', title: 'Err Track', artist: 'EA' }], 0, { sourceType: 'single-track', sourceLabel: '单曲队列' });
  hooks.handlePlayerError(new Error('boom'), {
    activeTrack: hooks.__state.queue[0],
    fallbackMode: 'paused',
    reason: 'contract-error',
    settleDetail: 'Err Track · MP3',
    logLabel: false,
  });
  const immediate = hooks.playerUiSnapshot();
  assert(immediate.mode === 'error' || immediate.mode === 'paused', `error-contract: expected error/paused, got ${immediate.mode}`);
  await new Promise((resolve)=>setTimeout(resolve, 0));
  const settled = hooks.playerUiSnapshot();
  assert(settled.mode === 'paused', `error-contract: expected settled paused, got ${settled.mode}`);
  assert(settled.activeTrackId === 'er1', `error-contract: expected activeTrackId=er1, got ${settled.activeTrackId}`);
}

async function testSplitScriptDependencyLoadContract() {
  const { hooks, scriptFiles } = loadApp();
  assert(Array.isArray(scriptFiles) && scriptFiles.length >= 8, `split-load: expected multiple scripts, got ${scriptFiles}`);
  assert(scriptFiles.includes('core.js'), 'split-load: missing core.js');
  assert(scriptFiles.includes('queue.js'), 'split-load: missing queue.js');
  assert(scriptFiles.includes('playlists.js'), 'split-load: missing playlists.js');
  assert(scriptFiles.includes('api.js'), 'split-load: missing api.js');
  assert(scriptFiles.includes('discover.js'), 'split-load: missing discover.js');
  assert(scriptFiles.includes('player.js'), 'split-load: missing player.js');
  assert(scriptFiles.includes('app.js'), 'split-load: missing app.js');
  assert(typeof hooks.createPlaylistRecord === 'function', 'split-load: createPlaylistRecord should be available');
  assert(typeof hooks.commitQueueReorder === 'function', 'split-load: commitQueueReorder should be available');
  assert(typeof hooks.swapCurrentTrackQuality === 'function', 'split-load: swapCurrentTrackQuality should be available');
}

async function testQueueReorderPersistsPlaylistLinkage() {
  const { hooks } = loadApp();
  hooks.__state.playlists = [{
    id: 'pl-queue',
    name: 'Queue Persist',
    tracks: [
      { id: 'a1', title: 'A1', artist: 'AA' },
      { id: 'a2', title: 'A2', artist: 'BB' },
      { id: 'a3', title: 'A3', artist: 'CC' },
    ],
    createdAt: Date.now(),
    updatedAt: Date.now(),
  }];
  hooks.__setQueue(hooks.__state.playlists[0].tracks, 1, {
    sourceType: 'local-playlist',
    playlistId: 'pl-queue',
    sourceLabel: '来自 Playlist · Queue Persist',
    writablePlaylist: true,
  });
  hooks.commitQueueReorder(2, 0);
  assert(hooks.__state.queue[0].id === 'a3', `queue-persist: expected queue[0]=a3, got ${hooks.__state.queue[0]?.id}`);
  assert(hooks.__state.playlists[0].tracks[0].id === 'a3', `queue-persist: expected playlist[0]=a3, got ${hooks.__state.playlists[0].tracks[0]?.id}`);
  assert(hooks.__state.idx === 2, `queue-persist: expected active idx=2 after reorder, got ${hooks.__state.idx}`);
}

async function testQueueEmptyRootGuardContract() {
  const { hooks } = loadApp();
  hooks.__setQueue([{ id: 'g1', title: 'Guard 1', artist: 'GA' }], 0, { sourceType: 'single-track', sourceLabel: '单曲队列' });
  hooks.__state.queue = [];
  hooks.__state.idx = -1;
  hooks.__state.queueContext = null;
  hooks.__state.queueDrag.fromIndex = 3;
  hooks.__state.queueDrag.overIndex = 4;
  hooks.__setQueue(null, 0, null);
  const snapshot = hooks.queuePresentationState();
  assert(snapshot.queueLength === 0, `queue-guard: expected empty queue, got ${snapshot.queueLength}`);
  assert(snapshot.dragFromIndex === -1 && snapshot.dragOverIndex === -1, `queue-guard: expected drag reset, got ${snapshot.dragFromIndex}/${snapshot.dragOverIndex}`);
}

(async function main(){
  const results = [];
  for(const [label, fn] of [
    ['split script dependency load contract', testSplitScriptDependencyLoadContract],
    ['play/pause state transition', testPlayPauseTransition],
    ['next/prev final idx and ui state', testNextPrevConsistency],
    ['quality switch settle contract', testQualitySwitchStateContract],
    ['rapid next/prev keeps last intent', testRapidNextPrevKeepsLastIntent],
    ['ended auto next contract', testEndedAutoNextContract],
    ['queue reorder keeps current occurrence', testQueueReorderKeepsCurrentOccurrence],
    ['queue reorder persists playlist linkage', testQueueReorderPersistsPlaylistLinkage],
    ['queue empty root guard contract', testQueueEmptyRootGuardContract],
    ['volume mute persistence contract', testVolumeMutePersistenceContract],
    ['queue restore consistency contract', testQueueRestoreConsistencyContract],
    ['quality switch pause/play/ended chain contract', testQualitySwitchPausePlayEndedChainContract],
    ['centralized error fallback contract', testCentralizedErrorFallbackContract],
  ]){
    try{
      await fn();
      results.push({ label, ok: true });
    }catch(err){
      results.push({ label, ok: false, detail: err.message });
    }
  }
  const failed = results.filter((item) => !item.ok);
  console.log(JSON.stringify({ ok: failed.length === 0, results }, null, 2));
  process.exit(failed.length ? 1 : 0);
})();
