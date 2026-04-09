// Split from legacy app.js for lower-risk browser-native loading.

async function api(path, options = {}) {
  const r = await fetch(path, {
    method: options.method || 'GET',
    headers: { 'Accept': 'application/json', ...(options.headers || {}) },
    body: options.body,
  });
  const contentType = String(r?.headers?.get?.('content-type') || '').toLowerCase();
  const isJson = contentType.includes('application/json');
  const payload = isJson ? await r.json() : await r.text();
  if(!r.ok){
    const apiMessage = isJson ? payload?.error?.message : '';
    const fallback = isJson ? JSON.stringify(payload).slice(0, 200) : String(payload).slice(0, 200);
    throw new Error(`${r.status} ${apiMessage || fallback}`.trim());
  }
  if(isJson && payload && typeof payload === 'object' && Object.prototype.hasOwnProperty.call(payload, 'ok')){
    if(payload.ok === false){
      throw new Error(payload?.error?.message || 'API request failed');
    }
    return payload.data;
  }
  return payload;
}
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
  pushView(()=>renderEmpty('Loading album…'));
  const a = await fetchAlbum(id);
  const tracks = a?.tracks || [];
  if(!tracks.length){
    renderEmpty('Album has no tracks.');
    return;
  }
  renderTrackList(a?.title || 'Album', a?.artist || '', a?.image || (tracks[0]||{}).image, tracks, { sourceType: 'album', sourceChip: 'Album', sourceLabel: `来自 Album · ${a?.title || 'Album'}`, audioSpecSource: a, decorate: (root)=>{
    const actions = root.querySelector('.detailActions');
    actions.appendChild(makeAlbumDownloadLink(a, 'Download album'));
  } });
}
async function openPlaylist(id){
  pushView(()=>renderEmpty('Loading playlist…'));
  const p = await api(`/api/playlist?id=${encodeURIComponent(id)}`);
  const tracks = p?.tracks || [];
  if(!tracks.length){
    renderEmpty('Playlist has no tracks.');
    return;
  }
  renderTrackList(p?.title || 'Playlist', p?.owner || '', p?.image || (tracks[0]||{}).image, tracks, { sourceType: 'remote-playlist', sourceChip: 'Playlist', sourceLabel: `来自 Qobuz Playlist · ${p?.title || 'Playlist'}`, audioSpecSource: p, decorate: (root)=>{
    const actions = root.querySelector('.detailActions');
    actions.appendChild(makeBtn('下载全部', ()=>triggerBulkDownload(tracks), 'btn small'));
  } });
}
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
  pushView(()=>renderEmpty('Loading artist…'));
  const a = await fetchArtist(id);
  const root = $('results');
  root.innerHTML = '';

  const detail = document.createElement('div');
  detail.className = 'detail';
  detail.innerHTML = `
    <div class="detailHead">
      <img class="detailCover" src="${esc(a?.image || '')}" alt="" />
      <div class="detailMeta">
        <div class="detailTitle"></div>
        <div class="detailSub"></div>
        <div class="detailNote"></div>
        <div class="detailActions">
          <button id="artistPlayAll" class="btn">Play all fetched tracks</button>
          <button id="back" class="btn">Back</button>
        </div>
      </div>
    </div>
    <div class="tracklist" id="artistAlbums"></div>
  `;
  detail.querySelector('.detailTitle').textContent = a?.name || 'Artist';
  const artistSpec = formatAudioSpec((a?.albums || []).find((al)=>formatAudioSpec(al)) || null);
  detail.querySelector('.detailSub').textContent = joinMetaParts([`${(a?.albums || []).length} albums`, artistSpec]);
  detail.querySelector('.detailSub').title = detail.querySelector('.detailSub').textContent;
  detail.querySelector('.detailNote').textContent = a?.cache?.hit ? 'Artist cache hit' : 'Artist cache miss';
  root.appendChild(detail);

  const albumWrap = detail.querySelector('#artistAlbums');
  const albums = a?.albums || [];
  if(!albums.length){
    albumWrap.innerHTML = '<div class="empty">No albums for this artist.</div>';
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
        makeBtn('Open', ()=>openAlbum(al.id)),
        makeAlbumDownloadLink(al, 'Download album'),
        makeBtn('Add all', async ()=>{
          const full = await fetchAlbum(al.id);
          const tracks = (full?.tracks || []).map(normTrack).filter(Boolean);
          state.queue = state.queue.concat(tracks);
          if(state.idx < 0 && state.queue.length){ state.idx = 0; }
          renderQueue();
          prefetchAdjacentStreams();
        })
      ],
      {
        audioSpec,
        audioSpecSource: al,
        entity: al,
      }
    ));
  }
  detail.querySelector('#artistPlayAll').addEventListener('click', async ()=>{
    const btn = detail.querySelector('#artistPlayAll');
    btn.disabled = true;
    btn.textContent = 'Collecting…';
    const merged = await collectArtistTracks(a);
    if(merged.length){
      queueFromTracks(merged, 0, { sourceType: 'artist', sourceLabel: `来自 Artist 集合 · ${a?.name || 'Artist'}` });
      await playCurrent('artist-play-all');
    }
    btn.disabled = false;
    btn.textContent = 'Play all fetched tracks';
    detail.querySelector('.detailNote').textContent = a.allTracks?.length ? 'Artist tracks ready (cached for this session)' : detail.querySelector('.detailNote').textContent;
  });
  detail.querySelector('#back').addEventListener('click', goBack);
}
async function playTrackNow(track){
  const t = typeof track === 'object' ? normTrack(track) : { id: track };
  queueFromTracks([t], 0, { sourceType: 'single-track', sourceLabel: '单曲队列' });
  await playCurrent('play-now');
}
async function getTrackMeta(track){
  let meta = normTrack(track);
  if(meta?.title && meta.title !== '—') return meta;
  meta = normTrack(await api(`/api/track?id=${encodeURIComponent(track.id)}`));
  return meta;
}
async function getTrackStream(trackId, fmt = currentQuality()){
  const cacheKey = `${trackId}:${fmt}`;
  const cached = getCachedMapValue(state.streamCache, cacheKey);
  if(cached?.url) return cached;
  const data = await api(`/api/track-url?id=${encodeURIComponent(trackId)}&fmt=${encodeURIComponent(fmt)}`);
  setCachedMapValue(state.streamCache, STREAM_CACHE_KEY, cacheKey, data);
  return data;
}
function preloadStreamForTrack(track, fmt = currentQuality()){
  const nextTrack = normTrack(track);
  if(!nextTrack?.id) return Promise.resolve(null);
  const prefetchKey = `${nextTrack.id}:${fmt}`;
  if(state.prefetchedStreamIds.has(prefetchKey)) return Promise.resolve(null);
  state.prefetchedStreamIds.add(prefetchKey);
  return getTrackStream(nextTrack.id, fmt).catch((err)=>{
    state.prefetchedStreamIds.delete(prefetchKey);
    throw err;
  });
}
async function prefetchAdjacentStreams(centerIdx = state.idx, fmt = currentQuality()){
  if(!state.queue.length || centerIdx < 0) return;
  const indexes = [];
  if(centerIdx + 1 < state.queue.length) indexes.push(centerIdx + 1);
  if(centerIdx - 1 >= 0) indexes.push(centerIdx - 1);
  await Promise.allSettled(indexes.map((idx)=>preloadStreamForTrack(state.queue[idx], fmt)));
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

    for(const it of items){
      if(state.type === 'tracks'){
        const t = normTrack(it);
        root.appendChild(card(t.image, t.title, t.artist || '', ()=>playTrackNow(t), [
          makeBtn('Play', ()=>playTrackNow(t)),
          makeTrackDownloadLink(t, 'Download track'),
          makeBtn('+', ()=>choosePlaylistForTrack(t)),
        ], { audioSpec: formatAudioSpec(t), audioSpecSource: t, entity: t }));
      }else if(state.type === 'albums'){
        root.appendChild(card(it.image, it.title, joinMetaParts([it.artist, it.year]), ()=>openAlbum(it.id), [
          makeBtn('Open', ()=>openAlbum(it.id)),
          makeAlbumDownloadLink(it, 'Download album'),
        ], { audioSpec: formatAudioSpec(it), audioSpecSource: it, entity: it }));
      }else if(state.type === 'artists'){
        root.appendChild(card(
          it.image,
          it.name,
          `${it.albums_count || ''} albums`,
          ()=>openArtist(it.id),
          [
            makeBtn('Open', ()=>openArtist(it.id))
          ],
          {
            audioSpec: formatAudioSpec(it),
            audioSpecSource: it,
            entity: it,
          }
        ));
      }else if(state.type === 'playlists'){
        root.appendChild(card(it.image, it.title, joinMetaParts([it.owner, it.tracks_count ? `${it.tracks_count} tracks` : '']), ()=>openPlaylist(it.id), [
          makeBtn('Open', ()=>openPlaylist(it.id)),
          makeBtn('Download', async ()=>{
            const full = await api(`/api/playlist?id=${encodeURIComponent(it.id)}`);
            triggerBulkDownload(full?.tracks || []);
          }),
        ], { audioSpec: formatAudioSpec(it), audioSpecSource: it, entity: it }));
      }
    }
  });
}
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
async function search(){
  const q = ($('q').value || '').trim();
  state.q = q;
  if(!q){
    clearHistory();
    await loadDiscoverRandom();
    return;
  }
  clearHistory();
  renderEmpty('Loading…');

  if($('urlMode').checked){
    await openByUrl(q);
    return;
  }

  const data = await api(`/api/search?q=${encodeURIComponent(q)}&type=${encodeURIComponent(state.type)}&limit=24&offset=0`);
  renderSearchResults(data?.items || []);
}
