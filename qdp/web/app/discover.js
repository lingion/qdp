// Split from legacy app.js for lower-risk browser-native loading.

// ═══ Discover Rendering ═══

let _discoverSeq = 0;

function renderDiscoverRandom(albums, seed = ''){
  setView((root)=>{
    const section = document.createElement('section');
    section.className = 'discoverSection';
    section.innerHTML = `
      <div class="discoverHead">
        <div>
          <div class="discoverTitle">随机专辑</div>
          <div class="discoverSub">${esc(seed ? `基于 ${seed} 的随机结果` : '给首页一点内容，不再留白')}</div>
        </div>
        <button id="refreshDiscover" class="btn small">换一批</button>
      </div>
      <div id="discoverGrid" class="results discoverGrid"></div>
    `;
    root.appendChild(section);
    const grid = section.querySelector('#discoverGrid');
    if(!albums.length){
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = '暂无随机专辑。';
      grid.appendChild(empty);
    }else{
      albums.forEach((it)=>{
        grid.appendChild(card(it.image, it.title, joinMetaParts([it.artist, it.year]), ()=>openAlbum(it.id), [
          makeAlbumDownloadLink(it, 'Download album'),
          makeIconButton('play', ()=>playAlbumNow(it.id), 'Play album'),
          makeIconButton('plus', async ()=>{ const full = await fetchAlbum(it.id); const tracks = (full?.tracks||[]).map(normTrack).filter(Boolean); choosePlaylistForTracks(tracks); }, 'Add to playlist'),
        ], { audioSpec: formatAudioSpec(it), audioSpecSource: it, entity: it }));
      });
    }
    section.querySelector('#refreshDiscover').addEventListener('click', ()=>loadDiscoverRandom(true).catch((e)=>renderEmpty(`Error: ${e.message}`)));
  });
}
// ═══ Discover Data ═══

async function loadDiscoverRandom(force = false){
  if(state.discoverRandom.loading && !force) return state.discoverRandom.albums;
  state.discoverRandom.loading = true;
  state.discoverRandom.error = '';
  const seq = ++_discoverSeq;
  try{
    const data = await api('/api/discover-random-albums');
    if(seq !== _discoverSeq) return state.discoverRandom.albums;
    state.discoverRandom.seed = String(data?.seed || '');
    state.discoverRandom.albums = Array.isArray(data?.items) ? data.items : [];
    renderDiscoverRandom(state.discoverRandom.albums, state.discoverRandom.seed);
    return state.discoverRandom.albums;
  }catch(err){
    if(seq !== _discoverSeq) return state.discoverRandom.albums;
    state.discoverRandom.error = err.message;
    renderEmpty(`推荐专辑加载失败：${err.message}`);
    return [];
  }finally{
    if(seq === _discoverSeq) state.discoverRandom.loading = false;
  }
}
