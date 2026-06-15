// Demo/static mode shim for Pages/static hosting.
// Intercepts /api/* calls and returns mock JSON so the app can render without qdp.web.server.
(function(){
  const host = location.hostname || '';
  const isStaticDemo = /pages\.dev$/i.test(host) || new URLSearchParams(location.search).get('demo') === '1';
  if(!isStaticDemo) return;

  const cover = '/app/placeholder.svg';
  const sampleAudio = 'https://www.soundhelix.com/examples/mp3/SoundHelix-Song-1.mp3';
  const fmtLabel = (bit, khz)=> ({ maximum_bit_depth: bit, maximum_sampling_rate: khz * 1000 });
  const tracks = [
    { id: 35533518, title: 'Yellow', artist: 'Coldplay', image: cover, duration: 269, ...fmtLabel(24, 192) },
    { id: 33170291, title: 'The Scientist', artist: 'Coldplay', image: cover, duration: 309, ...fmtLabel(24, 192) },
    { id: 11223344, title: 'Fix You', artist: 'Coldplay', image: cover, duration: 295, ...fmtLabel(24, 192) },
    { id: 22334455, title: 'Clocks', artist: 'Coldplay', image: cover, duration: 307, ...fmtLabel(24, 192) },
    { id: 99887766, title: 'Viva La Vida', artist: 'Coldplay', image: cover, duration: 242, ...fmtLabel(16, 44) },
    { id: 88776655, title: 'Paradise', artist: 'Coldplay', image: cover, duration: 278, ...fmtLabel(16, 44) },
  ];
  const albums = [
    { id: 'alb-parachutes', title: 'Parachutes', artist: 'Coldplay', image: cover, year: '2000', tracks: [tracks[0], tracks[5]], ...fmtLabel(24, 192) },
    { id: 'alb-arobtth', title: 'A Rush of Blood to the Head', artist: 'Coldplay', image: cover, year: '2002', tracks: [tracks[1], tracks[3]], ...fmtLabel(24, 192) },
    { id: 'alb-xy', title: 'X&Y', artist: 'Coldplay', image: cover, year: '2005', tracks: [tracks[2]], ...fmtLabel(24, 192) },
    { id: 'alb-viva', title: 'Viva la Vida or Death and All His Friends', artist: 'Coldplay', image: cover, year: '2008', tracks: [tracks[4]], ...fmtLabel(16, 44) },
  ];
  const artists = [
    { id: '40226', name: 'Coldplay', image: cover, albums: albums.map(a => ({ id: a.id, title: a.title, image: a.image, year: a.year, maximum_bit_depth: a.maximum_bit_depth, maximum_sampling_rate: a.maximum_sampling_rate })) },
    { id: 'daft-punk', name: 'Daft Punk', image: cover, albums: [{ id: 'dp-random', title: 'Random Access Memories', image: cover, year: '2013', ...fmtLabel(24, 88) }] }
  ];
  const playlists = [
    { id: 'pl-coldplay-hits', title: 'Coldplay Hits', owner: 'QDP Demo', image: cover, tracks: tracks.slice(0, 4), ...fmtLabel(24, 192) },
    { id: 'pl-soft-night', title: 'Late Night Demo', owner: 'QDP Demo', image: cover, tracks: [tracks[1], tracks[4], tracks[5]], ...fmtLabel(16, 44) }
  ];
  const trackMap = new Map(tracks.map(t => [String(t.id), t]));
  const albumMap = new Map(albums.map(a => [String(a.id), a]));
  const artistMap = new Map(artists.map(a => [String(a.id), a]));
  const playlistMap = new Map(playlists.map(p => [String(p.id), p]));

  function clone(obj){ return JSON.parse(JSON.stringify(obj)); }
  function ok(data){ return new Response(JSON.stringify({ ok: true, data, error: null }), { status: 200, headers: { 'Content-Type': 'application/json' } }); }
  function err(status, message){ return new Response(JSON.stringify({ ok: false, error: { message } }), { status, headers: { 'Content-Type': 'application/json' } }); }
  function q(path, name){ return new URL(path, location.origin).searchParams.get(name) || ''; }
  function matchTrack(text, t){
    const s = String(text || '').toLowerCase();
    return [t.title, t.artist].join(' ').toLowerCase().includes(s);
  }
  function matchAlbum(text, a){
    const s = String(text || '').toLowerCase();
    return [a.title, a.artist].join(' ').toLowerCase().includes(s);
  }
  function matchArtist(text, a){
    return String(a.name || '').toLowerCase().includes(String(text || '').toLowerCase());
  }
  function matchPlaylist(text, p){
    const s = String(text || '').toLowerCase();
    return [p.title, p.owner].join(' ').toLowerCase().includes(s);
  }
  async function handleApi(input, init){
    const url = typeof input === 'string' ? input : input.url;
    const u = new URL(url, location.origin);
    const path = u.pathname;
    if(path === '/api/meta') return ok({ version: '2.13.0-demo', web_player_version: '2.13.0-demo', image_proxy_base: '', demo_mode: true });
    if(path === '/api/accounts') return ok({ items: [{ name: 'demo', label: 'Static Demo', region: 'Pages', active: true }], active_account: 'demo' });
    if(path === '/api/accounts/switch') return ok({ active_account: 'demo' });
    if(path === '/api/me') return ok({ user: { display_name: 'Demo User', login: 'demo' }, subscription: { label: 'Static demo mode' }, active_account: 'demo' });
    if(path === '/api/cache-stats') return ok({ audio: { size_bytes: 0, count: 0 }, total: { size_bytes: 0, count: 0 } });
    if(path === '/api/cache-clear') return ok({ ok: true, cleared_bytes: 0, type: 'demo' });
    if(path === '/api/download-settings') return ok({ default_path: '/demo/downloads', workers: 3 });
    if(path === '/api/cached-track') return err(404, 'static demo has no local cache');
    if(path === '/api/track-url') {
      const id = q(url, 'id');
      const track = trackMap.get(String(id)) || tracks[0];
      return ok({ url: sampleAudio, cached_url: sampleAudio, cacheReady: false, download_url: sampleAudio, track });
    }
    if(path === '/api/discover-random-albums') return ok({ seed: 'demo', items: clone(albums) });
    if(path === '/api/search') {
      const term = q(url, 'q');
      const type = q(url, 'type') || 'tracks';
      const limit = Number(q(url, 'limit') || 24);
      const offset = Number(q(url, 'offset') || 0);
      let items = [];
      if(type === 'tracks') items = tracks.filter(t => matchTrack(term, t));
      else if(type === 'albums') items = albums.filter(a => matchAlbum(term, a));
      else if(type === 'artists') items = artists.filter(a => matchArtist(term, a));
      else if(type === 'playlists') items = playlists.filter(p => matchPlaylist(term, p));
      return ok({ items: clone(items.slice(offset, offset + limit)), total: items.length, has_more: offset + limit < items.length });
    }
    if(path === '/api/album') {
      const id = q(url, 'id');
      const album = albumMap.get(String(id));
      return album ? ok(clone(album)) : err(404, 'album not found');
    }
    if(path === '/api/artist') {
      const id = q(url, 'id');
      const artist = artistMap.get(String(id));
      return artist ? ok(clone(artist)) : err(404, 'artist not found');
    }
    if(path === '/api/playlist') {
      const id = q(url, 'id');
      const playlist = playlistMap.get(String(id));
      return playlist ? ok(clone(playlist)) : err(404, 'playlist not found');
    }
    if(path === '/api/track') {
      const id = q(url, 'id');
      const track = trackMap.get(String(id));
      return track ? ok(clone(track)) : err(404, 'track not found');
    }
    if(path === '/api/resolve-url') return ok({ type: 'album', id: 'alb-parachutes' });
    return null;
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function(input, init){
    const url = typeof input === 'string' ? input : input.url;
    if(/^\/api\//.test(new URL(url, location.origin).pathname)){
      const mocked = await handleApi(input, init);
      if(mocked) return mocked;
    }
    return originalFetch(input, init);
  };

  window.__QDP_DEMO_MODE__ = true;
})();
