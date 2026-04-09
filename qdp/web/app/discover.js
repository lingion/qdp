// Split from legacy app.js for lower-risk browser-native loading.

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
          makeBtn('打开', ()=>openAlbum(it.id)),
          makeAlbumDownloadLink(it, 'Download album'),
        ], { audioSpec: formatAudioSpec(it), audioSpecSource: it, entity: it }));
      });
    }
    section.querySelector('#refreshDiscover').addEventListener('click', ()=>loadDiscoverRandom(true).catch((e)=>renderEmpty(`Error: ${e.message}`)));
  });
}
async function loadDiscoverRandom(force = false){
  if(state.discoverRandom.loading && !force) return state.discoverRandom.albums;
  state.discoverRandom.loading = true;
  state.discoverRandom.error = '';
  try{
    const data = await api('/api/discover-random-albums');
    state.discoverRandom.seed = String(data?.seed || '');
    state.discoverRandom.albums = Array.isArray(data?.items) ? data.items : [];
    renderDiscoverRandom(state.discoverRandom.albums, state.discoverRandom.seed);
    return state.discoverRandom.albums;
  }catch(err){
    state.discoverRandom.error = err.message;
    renderEmpty(`推荐专辑加载失败：${err.message}`);
    return [];
  }finally{
    state.discoverRandom.loading = false;
  }
}
