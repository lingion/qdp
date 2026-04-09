// Split from legacy app.js for lower-risk browser-native loading.

function queueFromTracks(tracks, startIndex = 0, context = null){
  state.queue = (Array.isArray(tracks) ? tracks : []).map(normTrack).filter(Boolean);
  state.idx = state.queue.length ? Math.max(0, Math.min(startIndex, state.queue.length - 1)) : -1;
  state.queueContext = context ? buildQueueContext(context) : null;
  state.queueDrag.fromIndex = -1;
  state.queueDrag.overIndex = -1;
  if(state.queueContext && state.idx >= 0){
    state.queueContext.activeOccurrenceKey = trackOccurrenceKey(state.queue[state.idx], state.queue, state.idx);
  }
  renderQueue();
  syncAuxiliaryUi();
  persistPlayerSession();
}
function reorderQueueItems(queue, fromIndex, toIndex, activeIndex){
  const items = Array.isArray(queue) ? queue.slice() : [];
  const normalizedFrom = Number(fromIndex);
  const normalizedTo = Number(toIndex);
  if(normalizedFrom === normalizedTo || normalizedFrom < 0 || normalizedTo < 0 || normalizedFrom >= items.length || normalizedTo >= items.length){
    return { queue: items, idx: activeIndex };
  }
  const activeItem = items[activeIndex] || null;
  const activeKey = activeItem ? trackOccurrenceKey(activeItem, items, activeIndex) : null;
  const [moved] = items.splice(normalizedFrom, 1);
  items.splice(normalizedTo, 0, moved);
  const nextIdx = activeItem ? items.indexOf(activeItem) : (activeKey ? findTrackIndexByOccurrence(items, activeKey) : activeIndex);
  return { queue: items, idx: nextIdx };
}
function canReorderCurrentQueue(){
  return !!(state.queueContext?.writablePlaylist || state.queue.length > 1);
}
function syncPlaylistContextAfterQueueReorder(){
  const ctx = state.queueContext;
  if(!ctx || ctx.sourceType !== 'local-playlist' || !ctx.playlistId || !ctx.writablePlaylist) return;
  persistPlaylists(state.playlists.map((pl)=>{
    if(pl.id !== ctx.playlistId) return pl;
    return { ...pl, tracks: state.queue.map(normTrack).filter(Boolean), updatedAt: Date.now() };
  }));
}
function commitQueueReorder(fromIndex, toIndex){
  if(!canReorderCurrentQueue()) return { queue: state.queue.slice(), idx: state.idx };
  const reordered = reorderQueueItems(state.queue, fromIndex, toIndex, state.idx);
  state.queue = reordered.queue;
  state.idx = reordered.idx;
  state.queueDrag.fromIndex = -1;
  state.queueDrag.overIndex = -1;
  if(state.queueContext && state.idx >= 0){
    state.queueContext.activeOccurrenceKey = trackOccurrenceKey(state.queue[state.idx], state.queue, state.idx);
  }
  syncPlaylistContextAfterQueueReorder();
  renderQueue();
  syncAuxiliaryUi();
  persistPlayerSession();
  return reordered;
}
function clearQueueDragStyles(){
  document.querySelectorAll?.('.queueItem.dragging, .queueItem.dragOver').forEach((el)=>el.classList.remove('dragging', 'dragOver'));
}
function bindQueueDragHandlers(row, i){
  if(!row || !canReorderCurrentQueue()) return;
  row.draggable = true;
  row.dataset.queueIndex = String(i);
  row.addEventListener('dragstart', (e)=>{
    state.queueDrag.fromIndex = i;
    state.queueDrag.overIndex = i;
    syncAuxiliaryUi();
    row.classList.add('dragging');
    if(e.dataTransfer){
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(i));
    }
  });
  row.addEventListener('dragover', (e)=>{
    e.preventDefault();
    state.queueDrag.overIndex = i;
    row.classList.add('dragOver');
    if(e.dataTransfer) e.dataTransfer.dropEffect = 'move';
  });
  row.addEventListener('dragleave', ()=>row.classList.remove('dragOver'));
  row.addEventListener('dragend', ()=>{
    state.queueDrag.fromIndex = -1;
    state.queueDrag.overIndex = -1;
    syncAuxiliaryUi();
    renderQueue();
    clearQueueDragStyles();
  });
  row.addEventListener('drop', (e)=>{
    e.preventDefault();
    row.classList.remove('dragOver');
    const fromIndex = Number(e.dataTransfer?.getData('text/plain') || state.queueDrag.fromIndex);
    const toIndex = i;
    if(Number.isInteger(fromIndex) && Number.isInteger(toIndex) && fromIndex !== toIndex) commitQueueReorder(fromIndex, toIndex);
  });
}
function renderQueue(){
  syncSidebarSections();
  const root = $('queue');
  if(!root) return;
  root.innerHTML = '';
  syncAuxiliaryUi();
  if(!state.queue.length){
    root.className = 'queue sectionBody emptyMini';
    root.textContent = 'No queue yet.';
    return;
  }
  root.className = 'queue sectionBody';
  state.queue.forEach((item, i)=>{
    const t = normTrack(item);
    if(!t) return;
    const pending = state.loadingTrackId && state.loadingTrackId === String(t.id || '');
    const row = document.createElement('div');
    row.className = `queueItem${i === state.idx ? ' active' : ''}${pending ? ' pending' : ''}`;
    row.innerHTML = `
      <div class="queueDragHandle" aria-hidden="true"><span class="queueGrip"></span></div>
      <img class="queueThumb" src="${esc(t.image)}" alt="" />
      <div class="queueMeta">
        <div class="queueTitle"></div>
        <div class="queueSub"></div>
      </div>
      <div class="queueActions"></div>
    `;
    const titleNode = row.querySelector('.queueTitle');
    const subNode = row.querySelector('.queueSub');
    const metaNode = row.querySelector('.queueMeta');
    const actions = row.querySelector('.queueActions');
    if(titleNode) titleNode.textContent = t.title;
    if(subNode) subNode.textContent = buildQueueItemSubtitle(t, i);
    if(metaNode){
      metaNode.addEventListener('click', async ()=>{
        state.idx = i;
        if(state.queueContext) state.queueContext.activeOccurrenceKey = trackOccurrenceKey(state.queue[i], state.queue, i);
        renderQueue();
        syncAuxiliaryUi();
        await playCurrent('queue-click');
      });
    }
    if(actions){
      actions.appendChild(makeTrackDownloadLink(t, 'Download track'));
      actions.appendChild(makeBtn('+', ()=>choosePlaylistForTrack(t)));
    }
    bindQueueDragHandlers(row, i);
    root.appendChild(row);
  });
}
