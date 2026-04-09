// Split from legacy app.js for lower-risk browser-native loading.

async function loadAccounts(){
  try{
    const data = await api('/api/accounts');
    state.accounts = data?.items || [];
    state.activeAccount = data?.active_account || '';
    renderAccounts();
  }catch(_e){
    $('accountSelect').innerHTML = '<option value="">Accounts unavailable</option>';
  }
}
function renderAccounts(){
  const select = $('accountSelect');
  select.innerHTML = '';
  if(!state.accounts.length){
    select.innerHTML = '<option value="">No accounts</option>';
    return;
  }
  state.accounts.forEach((acc)=>{
    const opt = document.createElement('option');
    opt.value = acc.name;
    opt.textContent = `${acc.name}${acc.label ? ` · ${acc.label}` : ''}${acc.region ? ` · ${acc.region}` : ''}`;
    opt.selected = acc.active;
    select.appendChild(opt);
  });
  select.value = state.activeAccount || state.accounts[0].name;
}
async function switchAccount(name){
  if(!name || name === state.activeAccount) return;
  $('accountSelect').disabled = true;
  $('accountStatus').textContent = '切换中…';
  try{
    const res = await api(`/api/accounts/switch?name=${encodeURIComponent(name)}`, { method: 'POST' });
    state.activeAccount = res?.active_account || name;
    state.artistCache = {};
    state.albumCache = {};
    state.streamCache = {};
    state.prefetchedStreamIds.clear();
    saveCacheMap(ARTIST_CACHE_KEY, state.artistCache);
    saveCacheMap(ALBUM_CACHE_KEY, state.albumCache);
    saveCacheMap(STREAM_CACHE_KEY, state.streamCache);
    await loadAccounts();
    await loadMe();
    if(state.q && !$('urlMode').checked) await search();
    $('accountStatus').textContent = `已切换到 ${state.activeAccount}`;
  }catch(err){
    $('accountStatus').textContent = `切换失败：${err.message}`;
  }finally{
    $('accountSelect').disabled = false;
  }
}
async function loadMe(){
  try{
    const me = await api('/api/me');
    const label = me?.subscription?.label || me?.label || '';
    const name = me?.user?.display_name || me?.user?.login || 'Logged';
    const active = me?.active_account ? ` · ${me.active_account}` : '';
    $('me').textContent = label ? `${name}${active} · ${label}` : `${name}${active}`;
  }catch(_e){
    $('me').textContent = 'Not ready';
  }
}
