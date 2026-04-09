// Split from legacy app.js for lower-risk browser-native loading.

function syncQueueFromPlaylistContext(){
  const ctx = state.queueContext;
  if(!ctx || ctx.sourceType !== 'local-playlist' || !ctx.playlistId) return;
  const playlist = state.playlists.find((pl)=>pl.id === ctx.playlistId);
  if(!playlist) return;
  const wasPlaying = !!state.playing;
  const audio = $('audio');
  const currentTrack = state.queue[state.idx];
  const activeKey = currentTrack ? trackOccurrenceKey(currentTrack, state.queue, state.idx) : ctx.activeOccurrenceKey;
  state.queue = playlist.tracks.map(normTrack).filter(Boolean);
  if(!state.queue.length){
    state.idx = -1;
    state.queueContext.activeOccurrenceKey = null;
    if(audio){
      audio.pause();
      audio.removeAttribute('src');
      audio.load();
    }
    state.playing = false;
    setPlayIcon(ICONS.play);
    setPlayerUiState('idle');
    syncNowPlaying({ title: '—', artist: '—', image: '' });
    return;
  }
  let nextIdx = findTrackIndexByOccurrence(state.queue, activeKey);
  if(nextIdx < 0) nextIdx = Math.max(0, Math.min(state.idx, state.queue.length - 1));
  state.idx = nextIdx;
  state.queueContext.activeOccurrenceKey = trackOccurrenceKey(state.queue[state.idx], state.queue, state.idx);
  renderQueue();
  if(wasPlaying && audio && !audio.paused){
    syncNowPlaying(normTrack(state.queue[state.idx]));
  }
}
function persistPlaylists(nextPlaylists){
  state.playlists = nextPlaylists.map(normalizePlaylist).filter(Boolean);
  savePlaylists();
  syncQueueFromPlaylistContext();
  renderPlaylists();
}
function promptCreatePlaylist(prefill = ''){
  const name = prompt('新建 playlist 名称', prefill);
  if(!name) return null;
  try{
    const next = createPlaylistRecord(state.playlists, name);
    persistPlaylists(next);
    return next[next.length - 1];
  }catch(err){
    alert(err.message);
    return null;
  }
}
function choosePlaylistForTrack(track){
  const t = normalizePlaylistTrack(track);
  if(!t) return;
  if(!state.playlists.length){
    const created = promptCreatePlaylist();
    if(!created) return;
    persistPlaylists(addTrackToPlaylistRecord(state.playlists, created.id, t));
    return;
  }
  const names = state.playlists.map((p, i)=>`${i+1}. ${p.name}`).join('\n');
  const pick = prompt(`加入哪个 playlist？输入序号，或输入新名称新建：\n${names}`);
  if(!pick) return;
  const idx = Number(pick) - 1;
  try{
    if(Number.isInteger(idx) && idx >= 0 && idx < state.playlists.length){
      persistPlaylists(addTrackToPlaylistRecord(state.playlists, state.playlists[idx].id, t));
    }else{
      const created = promptCreatePlaylist(pick);
      if(!created) return;
      persistPlaylists(addTrackToPlaylistRecord(state.playlists, created.id, t));
    }
  }catch(err){
    alert(err.message);
  }
}
function choosePlaylistForTracks(tracks){
  const normalized = (Array.isArray(tracks) ? tracks : []).map(normalizePlaylistTrack).filter(Boolean);
  if(!normalized.length) return false;
  if(!state.playlists.length){
    const created = promptCreatePlaylist();
    if(!created) return false;
    let next = state.playlists;
    normalized.forEach((track)=>{ next = addTrackToPlaylistRecord(next, created.id, track); });
    persistPlaylists(next);
    return true;
  }
  const names = state.playlists.map((p, i)=>`${i+1}. ${p.name}`).join('\n');
  const pick = prompt(`将 ${normalized.length} 首歌曲加入哪个 playlist？输入序号，或输入新名称新建：\n${names}`);
  if(!pick) return false;
  const idx = Number(pick) - 1;
  try{
    let playlistId = '';
    let next = state.playlists;
    if(Number.isInteger(idx) && idx >= 0 && idx < state.playlists.length){
      playlistId = state.playlists[idx].id;
    }else{
      const created = promptCreatePlaylist(pick);
      if(!created) return false;
      next = state.playlists;
      playlistId = created.id;
    }
    normalized.forEach((track)=>{ next = addTrackToPlaylistRecord(next, playlistId, track); });
    persistPlaylists(next);
    return true;
  }catch(err){
    alert(err.message);
    return false;
  }
}
function playlistCoverMarkup(pl){
  const tracks = Array.isArray(pl?.tracks) ? pl.tracks : [];
  const images = tracks.map((t)=>normTrack(t)?.image).filter(Boolean).slice(0, 4);
  if(images.length >= 2){
    return `<div class="playlistThumb collage">${images.map((src)=>`<img src="${esc(src)}" alt="" />`).join('')}</div>`;
  }
  if(images.length === 1){
    return `<img class="playlistThumb single" src="${esc(images[0])}" alt="" />`;
  }
  return '<div class="playlistThumb placeholder">♪</div>';
}
function renderPlaylists(){
  syncSidebarSections();
  const root = $('myPlaylists');
  root.innerHTML = '';
  if(!state.playlists.length){
    root.className = 'playlists sectionBody collapsed emptyMini';
    root.textContent = 'No playlists yet.';
    return;
  }
  root.className = 'playlists sectionBody';
  state.playlists.forEach((pl)=>{
    const el = document.createElement('div');
    el.className = 'playlistItem';
    el.innerHTML = `
      ${playlistCoverMarkup(pl)}
      <div class="queueMeta">
        <div class="playlistName"></div>
        <div class="playlistMeta"></div>
      </div>
      <div class="queueActions"></div>
    `;
    el.querySelector('.playlistName').textContent = pl.name;
    el.querySelector('.playlistMeta').textContent = `${pl.tracks.length}`;
    el.querySelector('.queueMeta').addEventListener('click', ()=>openLocalPlaylist(pl.id));
    const actions = el.querySelector('.queueActions');
    actions.appendChild(makeBtn('Open', ()=>openLocalPlaylist(pl.id)));
    actions.appendChild(makeBtn('Export', ()=>exportPlaylistById(pl.id)));
    actions.appendChild(makeBtn('Play', async ()=>{
      if(!pl.tracks.length) return;
      queueFromTracks(pl.tracks, 0, { sourceType: 'local-playlist', playlistId: pl.id, sourceLabel: `来自 Playlist · ${pl.name}`, writablePlaylist: true });
      await playCurrent('playlist-play-all');
    }));
    root.appendChild(el);
  });
}
function downloadJsonFile(filename, payload){
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 1000);
}
function exportPlaylistById(id){
  const playlist = state.playlists.find((pl)=>pl.id === id);
  if(!playlist) return null;
  const payload = exportPlaylistsPayload([playlist]);
  const safeName = playlist.name.replace(/[^a-z0-9-_]+/gi, '_').replace(/^_+|_+$/g, '') || 'playlist';
  downloadJsonFile(`${safeName}.json`, payload);
  return payload;
}
function exportAllPlaylists(){
  downloadJsonFile('playlists.json', exportPlaylistsPayload(state.playlists));
}
async function importPlaylistsFromFile(file, options = {}){
  const text = await file.text();
  const payload = JSON.parse(text);
  const next = mergeImportedPlaylists(state.playlists, payload, { mode: options.mode || 'merge' });
  persistPlaylists(next);
  return next;
}
function localPlaylistActions(pl, root){
  const wrap = root.querySelector('.detailActions');
  wrap.appendChild(makeBtn('下载全部', ()=>triggerBulkDownload(pl.tracks || []), 'btn small'));
  wrap.appendChild(makeBtn('导出当前 Playlist JSON', ()=>exportPlaylistById(pl.id), 'btn small primary'));
  wrap.appendChild(makeBtn('重命名', ()=>{
    const nextName = prompt('Playlist 新名称', pl.name);
    if(!nextName) return;
    try{
      persistPlaylists(renamePlaylistRecord(state.playlists, pl.id, nextName));
      openLocalPlaylist(pl.id, true);
    }catch(err){
      alert(err.message);
    }
  }));
  wrap.appendChild(makeBtn('删除', ()=>{
    if(!confirm(`删除 playlist “${pl.name}”？`)) return;
    persistPlaylists(deletePlaylistRecord(state.playlists, pl.id));
    renderEmpty('Playlist deleted.');
    state.history.pop();
    $('backTop').classList.toggle('hidden', state.history.length === 0);
  }));
}
function buildTrackDragHandlers(row, i, playlistId, options = {}){
  if(!options.draggablePlaylist) return;
  row.classList.add('draggable');
  row.draggable = true;
  row.dataset.trackIndex = String(i);
  row.addEventListener('dragstart', (e)=>{
    row.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(i));
  });
  row.addEventListener('dragend', ()=>{
    row.classList.remove('dragging');
    document.querySelectorAll('.trackrow.dragOver').forEach((el)=>el.classList.remove('dragOver'));
  });
  row.addEventListener('dragover', (e)=>{
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    row.classList.add('dragOver');
  });
  row.addEventListener('dragleave', ()=>row.classList.remove('dragOver'));
  row.addEventListener('drop', (e)=>{
    e.preventDefault();
    row.classList.remove('dragOver');
    const fromIndex = Number(e.dataTransfer.getData('text/plain'));
    const toIndex = i;
    if(!Number.isInteger(fromIndex) || fromIndex === toIndex) return;
    persistPlaylists(reorderPlaylistTracksRecord(state.playlists, playlistId, fromIndex, toIndex));
    openLocalPlaylist(playlistId, true);
  });
}
function trackRow(track, i, tracks, options = {}){
  const t = normTrack(track);
  const row = document.createElement('div');
  const viewKey = options.viewKey || buildTrackListViewKey(options, options.title || '');
  const audioSpec = formatAudioSpec(t);
  row.className = 'trackrow';
  row.innerHTML = `
    <label class="trackSelect checkWrap"><input type="checkbox" class="trackCheckbox checkInput" aria-label="选择 ${esc(t.title || 'track')}" /><span class="checkMark" aria-hidden="true"></span></label>
    <div class="n">${i+1}</div>
    <div class="trackMain">
      <div class="tt"></div>
      <div class="trackMetaLine">
        <div class="aa"></div>
        <div class="trackSpec ${audioSpec ? '' : 'hidden'}"></div>
      </div>
    </div>
    <div class="rowActions"></div>`;
  row.querySelector('.tt').textContent = t.title || '—';
  row.querySelector('.aa').textContent = t.artist || '';
  row.querySelector('.trackSpec').textContent = audioSpec;
  row.querySelector('.trackSpec').dataset.hires = String(isHiResSource(t));
  row.querySelector('.trackCheckbox').checked = isTrackSelected(viewKey, t, i);
  row.querySelector('.trackCheckbox').addEventListener('change', (e)=>{
    toggleTrackSelection(viewKey, t, i, !!e.target.checked);
    options.onSelectionChange?.();
  });
  row.querySelector('.tt').addEventListener('click', async ()=>{
    const context = options.playlistId ? { sourceType: 'local-playlist', playlistId: options.playlistId, sourceLabel: options.sourceLabel || '', writablePlaylist: true } : (options.source ? { sourceType: options.source, sourceLabel: options.sourceLabel || '' } : null);
    queueFromTracks(tracks, i, context);
    await playCurrent(options.source || 'track-row');
  });
  const actions = row.querySelector('.rowActions');
  if(options.draggablePlaylist) actions.appendChild(makeBtn('↕', ()=>{}, 'btn small dragBtn'));
  actions.appendChild(makeTrackDownloadLink(t, 'Download track'));
  actions.appendChild(makeBtn('+', ()=>choosePlaylistForTrack(t)));
  if(typeof options.onRemove === 'function') actions.appendChild(makeBtn('移除', ()=>options.onRemove(i)));
  buildTrackDragHandlers(row, i, options.playlistId, options);
  return row;
}
function renderTrackList(title, subtitle, cover, tracks, options = {}){
  setView((root)=>{
    const viewKey = buildTrackListViewKey(options, title);
    ensureTrackSelectionView(viewKey);
    const heroSource = options.audioSpecSource || tracks.find((track)=>formatAudioSpec(track)) || null;
    const heroSpec = options.audioSpec || formatAudioSpec(heroSource);
    const heroHiRes = isHiResSource(heroSource);
    const head = document.createElement('div');
    head.className = 'detail';
    head.innerHTML = `
      <div class="detailHead">
        <img class="detailCover" src="${esc(cover || '')}" alt="" />
        <div class="detailMeta">
          <div class="detailEyebrow">${esc(options.sourceChip || options.sourceType || 'detail')}</div>
          <div class="detailTitle"></div>
          <div class="detailSub"></div>
          <div class="detailMetaBadges${heroSpec ? '' : ' hidden'}"></div>
          <div class="detailActions">
            <button id="playAll" class="btn primary">Play all</button>
            <button id="back" class="btn">Back</button>
          </div>
        </div>
      </div>
      <div class="tracklistTools"></div>
      <div class="tracklist" id="tracklist"></div>
    `;
    head.querySelector('.detailTitle').textContent = title || '—';
    head.querySelector('.detailSub').textContent = buildTrackListSubtitle(subtitle, options, tracks);
    const badgeWrap = head.querySelector('.detailMetaBadges');
    if(heroSpec && badgeWrap){
      const pill = document.createElement('span');
      pill.className = `metaBadge metaBadgeSpec${heroHiRes ? ' metaBadgeHiRes' : ''}`;
      pill.textContent = heroSpec;
      badgeWrap.appendChild(pill);
    }
    root.appendChild(head);

    const list = head.querySelector('#tracklist');
    const selectionUi = renderTrackBulkBar(head.querySelector('.tracklistTools'), viewKey, tracks, ()=>{
      list.querySelectorAll('.trackCheckbox').forEach((node, index)=>{
        node.checked = isTrackSelected(viewKey, tracks[index], index);
      });
    });
    head.querySelector('.tracklistTools').appendChild(selectionUi.bar);

    const rowOptions = { ...options, viewKey, title, onSelectionChange: ()=>selectionUi.sync() };
    tracks.forEach((t, i)=> list.appendChild(trackRow(t, i, tracks, rowOptions)));
    selectionUi.sync();

    head.querySelector('#playAll').addEventListener('click', async ()=>{
      const context = options.playlistId ? { sourceType: 'local-playlist', playlistId: options.playlistId, sourceLabel: options.sourceLabel || '', writablePlaylist: true } : (options.source ? { sourceType: options.source, sourceLabel: options.sourceLabel || '' } : null);
      queueFromTracks(tracks, 0, context);
      await playCurrent(options.source || 'play-all');
    });
    head.querySelector('#back').addEventListener('click', goBack);
    if(typeof options.decorate === 'function') options.decorate(head);
  });
}
function openLocalPlaylist(id, replaceCurrent = false){
  const current = state.playlists.find((x)=>x.id === id);
  if(!current){
    renderEmpty('Playlist not found.');
    return;
  }
  const options = {
    source: 'local-playlist',
    playlistId: current.id,
    sourceLabel: `来自 Playlist · ${current.name}`,
    draggablePlaylist: true,
    onRemove: (idx)=>{
      persistPlaylists(removeTrackFromPlaylistRecord(state.playlists, current.id, idx));
      openLocalPlaylist(id, true);
    },
    decorate: (root)=> localPlaylistActions(current, root),
  };
  if(replaceCurrent){
    renderTrackList(`Local Playlist · ${current.name}`, `${current.tracks.length} tracks`, (current.tracks[0]||{}).image, current.tracks, { ...options, sourceChip: 'Playlist', showTrackCount: false });
    return;
  }
  pushView(()=>renderTrackList(`Local Playlist · ${current.name}`, `${current.tracks.length} tracks`, (current.tracks[0]||{}).image, current.tracks, { ...options, sourceChip: 'Playlist', showTrackCount: false }));
}
