// Split from legacy app.js for lower-risk browser-native loading.

// ═══ API Fetch Wrapper ═══

const _API_TIMEOUT_MS = 15000;

async function api(path, options = {}) {
  let r;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), options.timeout || _API_TIMEOUT_MS);
  try {
    r = await fetch(path, {
      method: options.method || 'GET',
      headers: { 'Accept': 'application/json', ...(options.headers || {}) },
      body: options.body,
      signal: controller.signal,
    });
  } catch (networkErr) {
    clearTimeout(timeout);
    if(networkErr?.name === 'AbortError'){
      showToast('请求超时，请检查网络', 'error');
      throw new Error('API request timed out');
    }
    if (networkErr instanceof TypeError) {
      showToast('Network error — check your connection', 'error');
    }
    throw networkErr;
  }
  clearTimeout(timeout);
  const contentType = String(r?.headers?.get?.('content-type') || '').toLowerCase();
  const isJson = contentType.includes('application/json');
  const payload = isJson ? await r.json() : await r.text();
  if (!r.ok) {
    if (r.status === 429) {
      showToast('Rate limited — try again in a moment', 'warning');
    } else if (r.status === 401) {
      showToast('Authentication failed — check your account', 'error');
    } else {
      const apiMessage = isJson ? payload?.error?.message : '';
      const fallback = isJson ? JSON.stringify(payload).slice(0, 200) : String(payload).slice(0, 200);
      const msg = `${r.status} ${apiMessage || fallback}`.trim();
      showToast(msg, 'error');
    }
    const apiMessage = isJson ? payload?.error?.message : '';
    const fallback = isJson ? JSON.stringify(payload).slice(0, 200) : String(payload).slice(0, 200);
    throw new Error(`${r.status} ${apiMessage || fallback}`.trim());
  }
  if (isJson && payload && typeof payload === 'object' && Object.prototype.hasOwnProperty.call(payload, 'ok')) {
    if (payload.ok === false) {
      showToast(payload?.error?.message || 'API request failed', 'error');
      throw new Error(payload?.error?.message || 'API request failed');
    }
    return payload.data;
  }
  return payload;
}
// ═══ Stream Request Dedup ═══

const _pendingStreams = new Map();

function clearPendingStreams(){
  _pendingStreams.clear();
}

// ═══ Album ═══

async function fetchAlbum(id){
  const cached = getCachedMapValue(state.albumCache, id);
  if(cached){
    console.debug('[album-cache] hit', id);
    return { ...cached, cache: { hit: true, source: 'frontend' } };
  }
  const data = await api(`/api/album?id=${encodeURIComponent(id)}`);
  setCachedMapValue(state.albumCache, ALBUM_CACHE_KEY, id, data);
  console.debug('[album-cache] miss', id);
  return data;
}
async function openAlbum(id){
  if(state.currentView) state.history.push(state.currentView);
  setView(()=>renderLoadingSkeleton('cards'));
  try{
    const a = await fetchAlbum(id);
    const tracks = a?.tracks || [];
    if(!tracks.length){
      renderEmpty('Album has no tracks.');
      state.currentView = () => openAlbum(id);
      return;
    }
    renderTrackList(a?.title || 'Album', a?.artist || '', a?.image || (tracks[0]||{}).image, tracks, { sourceType: 'album', sourceChip: 'Album', sourceLabel: `来自 Album · ${a?.title || 'Album'}`, audioSpecSource: a, decorate: (root)=>{
      const actions = root.querySelector('.detailActions');
      actions.appendChild(makeAlbumDownloadLink(a, 'Download album'));
    } });
    state.currentView = () => openAlbum(id);
  }catch(err){
    renderEmpty(`加载失败: ${err.message}`);
    showToast(`加载失败: ${err.message}`, 'error');
  }
}
// ═══ Playlist ═══

async function openPlaylist(id){
  if(state.currentView) state.history.push(state.currentView);
  setView(()=>renderLoadingSkeleton('cards'));
  try{
    const p = await api(`/api/playlist?id=${encodeURIComponent(id)}`);
    const tracks = p?.tracks || [];
    if(!tracks.length){
      renderEmpty('Playlist has no tracks.');
      state.currentView = () => openPlaylist(id);
      return;
    }
    renderTrackList(p?.title || 'Playlist', p?.owner || '', p?.image || (tracks[0]||{}).image, tracks, { sourceType: 'remote-playlist', sourceChip: 'Playlist', sourceLabel: `来自 Qobuz Playlist · ${p?.title || 'Playlist'}`, audioSpecSource: p, decorate: (root)=>{
      const actions = root.querySelector('.detailActions');
      actions.appendChild(makeIconButton('download', ()=>triggerBulkDownload(tracks), 'Download all'));
    } });
    state.currentView = () => openPlaylist(id);
  }catch(err){
    renderEmpty(`加载失败: ${err.message}`);
    showToast(`加载失败: ${err.message}`, 'error');
  }
}
// ═══ Artist ═══

async function fetchArtist(id){
  const cached = getCachedMapValue(state.artistCache, id);
  if(cached){
    console.debug('[artist-cache] hit', id);
    return { ...cached, cache: { hit: true, source: 'frontend' } };
  }
  const data = await api(`/api/artist?id=${encodeURIComponent(id)}`);
  setCachedMapValue(state.artistCache, ARTIST_CACHE_KEY, id, data);
  console.debug('[artist-cache] miss', id);
  return data;
}
async function collectArtistTracks(artist){
  if(artist.allTracks && artist.allTracks.length) return artist.allTracks;
  const merged = [];
  for(const al of (artist.albums || [])){
    try{
      const full = await fetchAlbum(al.id);
      merged.push(...(full?.tracks || []).map(normTrack).filter(Boolean));
    }catch(_e){}
  }
  artist.allTracks = merged;
  setCachedMapValue(state.artistCache, ARTIST_CACHE_KEY, artist.id, artist);
  return merged;
}
async function openArtist(id){
  if(state.currentView) state.history.push(state.currentView);
  setView(()=>renderLoadingSkeleton('cards'));
  try{
    const a = await fetchArtist(id);
    const root = $('results');
    root.innerHTML = '';

    const detail = document.createElement('div');
    detail.className = 'detail';
    const artistSpec = formatAudioSpec((a?.albums || []).find((al)=>formatAudioSpec(al)) || null);
    const cacheTag = a?.cache?.hit ? ' · cached' : '';
    const artistSub = joinMetaParts([`${(a?.albums || []).length} albums`, artistSpec]) + cacheTag;
    detail.innerHTML = `
      <div class="detailHead">
        <img class="detailCover" src="${esc(a?.image || '')}" alt="" onerror="this.onerror=null;this.src='/app/placeholder.svg'" />
        <div class="detailMeta">
          <div class="detailMainRow">
            <div class="detailInfo">
              <div class="detailTitle"></div>
              <div class="detailSub"></div>
            </div>
            <div class="detailRight">
              <div class="detailActions">
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="tracklist" id="artistAlbums"></div>
    `;
    detail.querySelector('.detailTitle').textContent = a?.name || 'Artist';
    detail.querySelector('.detailSub').textContent = artistSub;
    detail.querySelector('.detailSub').title = artistSub;
    root.appendChild(detail);

    const albumWrap = detail.querySelector('#artistAlbums');
    const albums = a?.albums || [];
    if(!albums.length){
      albumWrap.innerHTML = '<div class="empty">No albums for this artist.</div>';
      state.currentView = () => openArtist(id);
      return;
    }
    for(const al of albums){
      const audioSpec = formatAudioSpec(al);
      albumWrap.appendChild(card(
        al.image,
        al.title,
        joinMetaParts([a?.name || '', al.year]),
        ()=>openAlbum(al.id),
        [
          makeAlbumDownloadLink(al, 'Download album'),
          makeIconButton('play', ()=>playAlbumNow(al.id), 'Play album'),
          makeIconButton('plus', async ()=>{
            const full = await fetchAlbum(al.id);
            const tracks = (full?.tracks||[]).map(normTrack).filter(Boolean);
            choosePlaylistForTracks(tracks);
          }, 'Add to playlist')
        ],
        {
          audioSpec,
          audioSpecSource: al,
          entity: al,
        }
      ));
    }
    const artistActions = detail.querySelector('.detailActions');
    artistActions.appendChild(makeIconButton('play', async ()=>{
      const merged = await collectArtistTracks(a);
      if(merged.length){
        queueFromTracks(merged, 0, { sourceType: 'artist', sourceLabel: `来自 Artist 集合 · ${a?.name || 'Artist'}` });
        await playCurrent('artist-play-all');
      }
    }, 'Play all'));
    state.currentView = () => openArtist(id);
  }catch(err){
    renderEmpty(`加载失败: ${err.message}`);
    showToast(`加载失败: ${err.message}`, 'error');
  }
}
// ═══ Track Stream ═══

async function playTrackNow(track){
  // Warm up the audio element while we're still in a user-gesture context
  const audio = $('audio');
  if(audio){
    setAudioEventGate('play');
    try{ await audio.play(); }catch(_e){}
    setAudioEventGate('pause');
    audio.pause();
  }
  const t = typeof track === 'object' ? normTrack(track) : { id: track };
  queueFromTracks([t], 0, { sourceType: 'single-track', sourceLabel: '单曲队列' });
  await playCurrent('play-now');
}
async function playAlbumNow(albumId){
  // Warm up the audio element while we're still in a user-gesture context
  const audio = $('audio');
  if(audio){
    setAudioEventGate('play');
    try{ await audio.play(); }catch(_e){}
    setAudioEventGate('pause');
    audio.pause();
  }
  try{
    const a = await fetchAlbum(albumId);
    const tracks = (a?.tracks || []).map(normTrack).filter(Boolean);
    if(!tracks.length){ showToast('专辑没有可播放的曲目', 'warning'); return; }
    queueFromTracks(tracks, 0, {
      sourceType: 'album',
      sourceLabel: `来自 Album · ${a?.title || 'Album'}`,
    });
    await playCurrent('play-album');
  }catch(err){
    showToast(`播放失败: ${err.message || '网络错误'}`, 'error');
  }
}
async function playPlaylistNow(playlistId){
  // Warm up the audio element while we're still in a user-gesture context
  const audio = $('audio');
  if(audio){
    setAudioEventGate('play');
    try{ await audio.play(); }catch(_e){}
    setAudioEventGate('pause');
    audio.pause();
  }
  try{
    const p = await api(`/api/playlist?id=${encodeURIComponent(playlistId)}`);
    const tracks = (p?.tracks || []).map(normTrack).filter(Boolean);
    if(!tracks.length){ showToast('播放列表没有可播放的曲目', 'warning'); return; }
    queueFromTracks(tracks, 0, {
      sourceType: 'remote-playlist',
      sourceLabel: `来自 Playlist · ${p?.title || 'Playlist'}`,
    });
    await playCurrent('play-playlist');
  }catch(err){
    showToast(`播放失败: ${err.message || '网络错误'}`, 'error');
  }
}
async function playArtistNow(artist){
  // Warm up the audio element while we're still in a user-gesture context
  const audio = $('audio');
  if(audio){
    setAudioEventGate('play');
    try{ await audio.play(); }catch(_e){}
    setAudioEventGate('pause');
    audio.pause();
  }
  try{
    const tracks = await collectArtistTracks(artist);
    if(!tracks.length){ showToast('该艺术家没有可播放的曲目', 'warning'); return; }
    queueFromTracks(tracks, 0, {
      sourceType: 'artist',
      sourceLabel: `来自 Artist · ${artist?.name || 'Artist'}`,
    });
    await playCurrent('play-artist');
  }catch(err){
    showToast(`播放失败: ${err.message || '网络错误'}`, 'error');
  }
}
async function getTrackMeta(track){
  let meta = normTrack(track);
  if(meta?.title && meta.title !== '—') return meta;
  meta = normTrack(await api(`/api/track?id=${encodeURIComponent(track.id)}`));
  return meta;
}
async function getTrackStream(trackId, fmt = currentQuality()){
  const acctSeq = state.streamAccountSeq || 0;
  const cacheKey = `${trackId}:${fmt}`;
  const cached = getCachedMapValue(state.streamCache, cacheKey);
  if(cached?.url){
    const age = streamCacheAge(cacheKey);
    if(age < STREAM_STALE_MS) return cached;
    console.debug(`[stream-cache] stale (${Math.round(age / 1000)}s), refreshing`, cacheKey);
  }
  if(_pendingStreams.has(cacheKey)) return _pendingStreams.get(cacheKey);
  const promise = api(`/api/track-url?id=${encodeURIComponent(trackId)}&fmt=${encodeURIComponent(fmt)}`).then((data)=>{
    _pendingStreams.delete(cacheKey);
    if(acctSeq !== (state.streamAccountSeq || 0)) return null;
    if(!data?.url) throw new Error('Server returned empty stream URL');
    setCachedMapValue(state.streamCache, STREAM_CACHE_KEY, cacheKey, data);
    return data;
  }).catch((err)=>{
    _pendingStreams.delete(cacheKey);
    throw err;
  });
  _pendingStreams.set(cacheKey, promise);
  return promise;
}
async function getTrackStreamWithRetry(trackId, fmt = currentQuality(), maxRetries = 2){
  const cacheKey = `${trackId}:${fmt}`;
  let lastError;
  for(let attempt = 0; attempt <= maxRetries; attempt++){
    try{
      if(attempt > 0){
        if(state.streamCache && state.streamCache[cacheKey]){
          delete state.streamCache[cacheKey];
          saveCacheMap(STREAM_CACHE_KEY, state.streamCache);
        }
        await new Promise((r)=>setTimeout(r, 1000 * Math.pow(2, attempt - 1)));
      }
      return await getTrackStream(trackId, fmt);
    }catch(err){
      lastError = err;
    }
  }
  throw lastError;
}
function preloadAudioData(url){
  if(!url) return Promise.resolve();
  return fetch(url, { headers: { Range: 'bytes=0-524287' } })
    .then((resp)=>{
      if(!resp.body) return;
      const reader = resp.body.getReader();
      return reader.read()
        .then(()=>{ reader.cancel(); })
        .catch(()=>{})
        .finally(()=>{ try{ reader.cancel(); }catch(_e){} });
    })
    .catch(()=>{});
}
// ═══ Cached Track Fallback ═══

function getCachedTrackUrl(trackId, fmt){
  return `/api/cached-track?id=${encodeURIComponent(trackId)}&fmt=${encodeURIComponent(fmt || currentQuality())}`;
}

async function checkCachedTrack(trackId, fmt){
  try{
    const url = getCachedTrackUrl(trackId, fmt);
    const r = await fetch(url, { headers: { Range: 'bytes=0-0' } });
    return r.ok || r.status === 206;
  }catch(_e){
    return false;
  }
}
function preloadStreamForTrack(track, fmt = currentQuality(), maxAgeMs){
  const nextTrack = normTrack(track);
  if(!nextTrack?.id) return Promise.resolve(null);
  const prefetchKey = `${nextTrack.id}:${fmt}`;
  const effectiveMaxAge = maxAgeMs != null ? maxAgeMs : STREAM_PREFETCH_MAX_AGE_MS;
  if(state.prefetchedStreamIds.has(prefetchKey)){
    const age = streamCacheAge(prefetchKey);
    if(age < effectiveMaxAge) return Promise.resolve(null);
    console.debug(`[prefetch] stale (${Math.round(age / 1000)}s), re-prefetching`, prefetchKey);
    state.prefetchedStreamIds.delete(prefetchKey);
  }
  state.prefetchedStreamIds.add(prefetchKey);
  return getTrackStream(nextTrack.id, fmt).then((stream)=>{
    if(stream?.url) preloadAudioData(stream.url);
    return stream;
  }).catch((err)=>{
    state.prefetchedStreamIds.delete(prefetchKey);
    throw err;
  });
}
async function prefetchAdjacentStreams(centerIdx = state.idx, fmt = currentQuality()){
  if(state.shuffle){
    // In shuffle mode, prefetch random tracks from the queue as heuristic
    const indexes = [];
    const picked = new Set();
    const count = Math.min(2, state.queue.length - 1);
    for(let attempt = 0; attempt < count * 3 && indexes.length < count; attempt++){
      const pick = Math.floor(Math.random() * state.queue.length);
      if(pick !== centerIdx && !picked.has(pick)){
        picked.add(pick);
        indexes.push(pick);
      }
    }
    if(indexes.length === 0) return;
    await Promise.allSettled(indexes.map((idx)=>preloadStreamForTrack(state.queue[idx], fmt)));
    return;
  }
  if(!state.queue.length || centerIdx < 0) return;
  const indexes = [];
  for(let offset = 1; offset <= 3; offset++){
    if(centerIdx + offset < state.queue.length) indexes.push(centerIdx + offset);
  }
  if(centerIdx - 1 >= 0) indexes.push(centerIdx - 1);
  await Promise.allSettled(indexes.map((idx)=>preloadStreamForTrack(state.queue[idx], fmt)));
}
// ═══ Search ═══

const SEARCH_PAGE_SIZE = 24;

function appendSearchCards(root, items){
  for(const it of items){
    if(state.type === 'tracks'){
      const t = normTrack(it);
      root.appendChild(card(t.image, t.title, t.artist || '', ()=>playTrackNow(t), [
        makeTrackDownloadLink(t, 'Download track'),
        makeIconButton('play', ()=>playTrackNow(t), 'Play'),
        makeIconButton('plus', ()=>choosePlaylistForTrack(t), 'Add to playlist'),
      ], { audioSpec: formatAudioSpec(t), audioSpecSource: t, entity: t }));
    }else if(state.type === 'albums'){
      root.appendChild(card(it.image, it.title, joinMetaParts([it.artist, it.year]), ()=>openAlbum(it.id), [
        makeAlbumDownloadLink(it, 'Download album'),
        makeIconButton('play', ()=>playAlbumNow(it.id), 'Play album'),
        makeIconButton('plus', async ()=>{ const full = await fetchAlbum(it.id); const tracks = (full?.tracks||[]).map(normTrack).filter(Boolean); choosePlaylistForTracks(tracks); }, 'Add to playlist'),
      ], { audioSpec: formatAudioSpec(it), audioSpecSource: it, entity: it }));
    }else if(state.type === 'artists'){
      root.appendChild(card(
        it.image,
        it.name,
        `${it.albums_count || ''} albums`,
        ()=>openArtist(it.id),
        [
          makeIconButton('play', ()=>playArtistNow(it), 'Play artist'),
          makeIconButton('plus', async ()=>{
            const full = await collectArtistTracks(it);
            if(full.length) choosePlaylistForTracks(full);
          }, 'Add to playlist'),
        ],
        {
          audioSpec: formatAudioSpec(it),
          audioSpecSource: it,
          entity: it,
        }
      ));
    }else if(state.type === 'playlists'){
      root.appendChild(card(it.image, it.title, joinMetaParts([it.owner, it.tracks_count ? `${it.tracks_count} tracks` : '']), ()=>openPlaylist(it.id), [
        makeIconButton('download', async ()=>{
          const full = await api(`/api/playlist?id=${encodeURIComponent(it.id)}`);
          triggerBulkDownload(full?.tracks || []);
        }, 'Download'),
        makeIconButton('play', ()=>playPlaylistNow(it.id), 'Play playlist'),
        makeIconButton('plus', async ()=>{
          const full = await api(`/api/playlist?id=${encodeURIComponent(it.id)}`);
          const tracks = (full?.tracks || []).map(normTrack).filter(Boolean);
          choosePlaylistForTracks(tracks);
        }, 'Add to playlist'),
      ], { audioSpec: formatAudioSpec(it), audioSpecSource: it, entity: it }));
    }
  }
}

function updateLoadMoreButton(root, itemCount){
  const existing = root.querySelector('.loadMoreWrap');
  if(existing) existing.remove();

  state.searchHasMore = itemCount >= SEARCH_PAGE_SIZE;

  if(state.searchHasMore){
    const wrap = document.createElement('div');
    wrap.className = 'loadMoreWrap';
    const btn = makeBtn('Load more', ()=>loadMore());
    wrap.appendChild(btn);
    root.appendChild(wrap);
  }
}

function renderSearchResults(items){
  setView((root)=>{
    if(!items.length){
      const d = document.createElement('div');
      d.className = 'empty';
      d.textContent = 'No results.';
      root.appendChild(d);
      return;
    }

    appendSearchCards(root, items);
    updateLoadMoreButton(root, items.length);
  });
}

async function loadMore(){
  const root = $('results');
  const btn = root.querySelector('.loadMoreWrap .btn');
  if(!btn) return;
  btn.textContent = 'Loading\u2026';
  btn.disabled = true;

  const seq = _searchSeq;
  state.searchOffset += SEARCH_PAGE_SIZE;

  try{
    const data = await api(`/api/search?q=${encodeURIComponent(state.q)}&type=${encodeURIComponent(state.type)}&limit=${SEARCH_PAGE_SIZE}&offset=${state.searchOffset}`);
    if(seq !== _searchSeq) return;
    const items = data?.items || [];
    appendSearchCards(root, items);
    updateLoadMoreButton(root, items.length);
  }catch(e){
    if(seq !== _searchSeq) return;
    state.searchOffset -= SEARCH_PAGE_SIZE;
    const restoreBtn = root.querySelector('.loadMoreWrap .btn');
    if(restoreBtn){ restoreBtn.textContent = 'Load more'; restoreBtn.disabled = false; }
    if(typeof showToast === 'function') showToast(`加载更多失败: ${e.message}`, 'error');
  }
}
// ═══ URL Resolution ═══

async function resolveQobuzUrl(input){
  try{
    return await api(`/api/resolve-url?url=${encodeURIComponent(input)}`);
  }catch(_e){
    let u;
    try{ u = new URL(input); }catch(__e){ throw new Error('Invalid URL'); }
    const host = u.hostname.toLowerCase();
    if(!/qobuz\.com$/.test(host)) throw new Error('Not a qobuz.com URL');
    const parts = u.pathname.split('/').filter(Boolean);
    const mapType = { track:'track', album:'album', artist:'artist', playlist:'playlist' };
    let type = null;
    let id = null;
    for(let i=0;i<parts.length;i++){
      const p = parts[i].toLowerCase();
      if(mapType[p] && parts[i+1]){ type = mapType[p]; id = parts[i+1]; break; }
    }
    if(!type || !id) throw new Error('Unsupported Qobuz URL');
    return { type, id };
  }
}
async function openByUrl(url){
  const parsed = await resolveQobuzUrl(url);
  if(parsed.type === 'track') return playTrackNow(parsed.id);
  if(parsed.type === 'album') return openAlbum(parsed.id);
  if(parsed.type === 'artist') return openArtist(parsed.id);
  if(parsed.type === 'playlist') return openPlaylist(parsed.id);
}
// ═══ Search Entry ═══

let _searchSeq = 0;

async function search(){
  const q = ($('q').value || '').trim();
  state.q = q;
  state.searchOffset = 0;
  state.searchHasMore = false;
  if(!q){
    clearHistory();
    await loadDiscoverRandom();
    return;
  }
  clearHistory();
  renderLoadingSkeleton('cards');

  if($('urlMode').checked){
    await openByUrl(q);
    return;
  }

  const seq = ++_searchSeq;
  const data = await api(`/api/search?q=${encodeURIComponent(q)}&type=${encodeURIComponent(state.type)}&limit=${SEARCH_PAGE_SIZE}&offset=0`);
  if(seq !== _searchSeq) return;
  renderSearchResults(data?.items || []);
}
