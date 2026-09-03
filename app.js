'use strict';

const runtimeConfig=Object.freeze(window.SENTINEL_RUNTIME_CONFIG||{});
function normalizeApiBase(value){try{const url=new URL(String(value||''),location.origin);if(!['http:','https:'].includes(url.protocol))return location.origin;return url.origin}catch(_){return location.origin}}
const apiBaseUrl=normalizeApiBase(runtimeConfig.apiBaseUrl||location.origin);
const websocketBaseUrl=normalizeApiBase(runtimeConfig.websocketBaseUrl||apiBaseUrl);
const apiUrl=path=>new URL(path,`${apiBaseUrl}/`).toString();
function websocketUrl(path){const url=new URL(path,`${websocketBaseUrl}/`);url.protocol=url.protocol==='https:'?'wss:':'ws:';return url.toString()}
const byId=id=>document.getElementById(id);
const tracks=new Map(),events=new Map(),devices=new Map();
const trackTrails=new Map();
let latestTelemetry=null,latestRange=null,latestVision=null,geofences=[],capabilities=null,readiness=null;
let evidenceVerifications=[],securityAdvisories=[],socket=null,socketHeartbeat=null,previewFailures=0,previewTimer=null,previewInFlight=false,previewRenderedAt=0;
// The vision worker publishes Full-HD preview frames at 10 FPS.  Poll below
// that cadence made a healthy stream look visibly delayed in the grid.
// Keep the operator preview close to the newest annotated frame without
// continuously polling faster than the vision worker can publish it.
const PREVIEW_REFRESH_INTERVAL_MS=75;
let activeWorkspace='flight',activeMapTool='select',activeMapLayer='mission',activeMapView='street',mapZoom=1;
let selectedTrackId='',selectedEventId='',pendingAckEventId='',pendingEventState='ACKNOWLEDGED',socketRetry=0,mapDrawPending=false;
let mapCenterOverride=null,mapDrag=null,mapDragMoved=false,mapMotionFrame=0,lastMapMotionAt=0,connectionRetryTimer=null,currentMapView=null,lastMapCursor=null,mapTileTemplate='https://tile.openstreetmap.org/{z}/{x}/{y}.png',streetViewUrlTemplate='https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat}%2C{lon}';
const mapTiles=new Map(),MAP_TILE_SIZE=256;
const MAP_VIEWS=Object.freeze({
  street:{label:'STREET',template:null,attribution:'© OpenStreetMap contributors',attributionUrl:'https://www.openstreetmap.org/copyright'},
  satellite:{label:'SATELLITE',template:'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',attribution:'Esri World Imagery',attributionUrl:'https://www.esri.com/arcgis-blog/products/arcgis-living-atlas/imagery/world-imagery/'},
  marine:{label:'MARITIME',template:null,overlayTemplate:'https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png',attribution:'© OpenStreetMap · OpenSeaMap',attributionUrl:'https://www.openseamap.org/'},
  tactical:{label:'TACTICAL',template:'',attribution:'Local tactical grid',attributionUrl:''}
});
let missionWaypoints=loadMissionDraft();
let missionRecord=loadMissionRecord();
let missionDirty=false;
let replayMode=false,replayRecords=[];
let accessToken=sessionStorage.getItem('sentinel.access_token')||'',runtimeStarted=false,currentPreviewUrl='',cameraViewMode='fit';
// This deployment is intentionally localhost-only and uses no browser login.
// API authorization is disabled in D:\fpv\.env to match this console mode.
const LOCAL_OPERATOR_MODE=true;

const text=(id,value)=>{const node=byId(id);if(node)node.textContent=value};
const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
const num=(value,digits=1,fallback='--')=>Number.isFinite(Number(value))?Number(value).toFixed(digits):fallback;
const cardinalFromHeading=value=>['N','NE','E','SE','S','SW','W','NW'][Math.round((((value%360)+360)%360)/45)%8];
const empty=label=>{const node=document.createElement('p');node.className='empty';node.textContent=label;return node};
const presentationIcon=kind=>{const paths={track:'<circle cx="12" cy="12" r="6"/><path d="M12 2v4m0 12v4M2 12h4m12 0h4m-4.9-4.9 2.8-2.8M4.1 19.9l2.8-2.8m0-10L4.1 4.3m15.8 15.6-2.8-2.8"/>',alert:'<path d="m12 3 9 17H3Z"/><path d="M12 9v4m0 3h.01"/>'};return `<svg viewBox="0 0 24 24" focusable="false" aria-hidden="true">${paths[kind]||paths.track}</svg>`};
function tableEmpty(body,columnCount,icon,title,detail){const row=document.createElement('tr'),cell=document.createElement('td'),state=document.createElement('div'),mark=document.createElement('span'),heading=document.createElement('b'),copy=document.createElement('p');row.className='table-empty-row';cell.colSpan=columnCount;state.className='table-empty-state';mark.className='empty-icon';mark.setAttribute('aria-hidden','true');mark.innerHTML=presentationIcon(icon);heading.textContent=title;copy.textContent=detail;state.append(mark,heading,copy);cell.append(state);row.append(cell);body.append(row)}
function inspectorEmpty(){const state=document.createElement('div'),mark=document.createElement('span'),heading=document.createElement('b'),copy=document.createElement('p');state.className='inspector-empty';mark.className='empty-icon';mark.setAttribute('aria-hidden','true');mark.innerHTML=presentationIcon('track');heading.textContent='No track selected';copy.textContent='Select a track to view its detection history, motion, and evidence.';state.append(mark,heading,copy);return state}
const statusClass=value=>['processing','connected','active','enabled','ready','receiving','field_ready','online'].includes(String(value).toLowerCase())?'good':['degraded','configured','maintenance','awaiting telemetry','starting','waiting_for_frames'].includes(String(value).toLowerCase())?'warn':'bad';
const LAYER_PRESENTATION=Object.freeze({
  video:{title:'Video Capture',detail:'Camera source connected'},
  detection:{title:'Object Detection',detail:'Identifies supported objects in each frame'},
  tracking:{title:'Object Tracking',detail:'Assigns persistent IDs to confirmed detections'},
  person_crosscheck:{title:'Person Verification',detail:'Independently cross-checks low-confidence detections'},
  fall_detection:{title:'Fall Detection',detail:'Flags falls from skeletal motion for review'},
  face_observation:{title:'Face Observation',detail:'Finds faces and assesses image quality'},
  telemetry:{title:'Flight Telemetry',detail:'Receives GPS, IMU, and LiDAR data'},
  geolocation:{title:'Object Geolocation',detail:'Combines camera, range, and telemetry data'},
  geofence_risk:{title:'Geofence & Risk Rules',detail:'Rule-based, not AI-driven'},
  storage:{title:'Evidence Storage',detail:'Stores track and event records'},
  v2x:{title:'V2X Event Relay',detail:'Shares signed events with connected assets'},
  security_integrity:{title:'Integrity Monitor',detail:'Checks telemetry and V2X messages for replay or tampering'},
  llm_advisory:{title:'Scene Review (Gemini)',detail:'Advisory only — no control over detection or alerts'},
  security_llm_advisory:{title:'Security Summary (Gemini)',detail:'Sanitised findings only — advisory output'}
});
const layerPresentation=layer=>LAYER_PRESENTATION[layer.id]||{title:String(layer.component||layer.id||'Subsystem').replaceAll('_',' '),detail:layer.requires||layer.scope||layer.authority||'Service-reported capability'};

function loadMissionDraft(){
  try{
    const value=JSON.parse(localStorage.getItem('sentinel.mission.draft.v1')||'[]');
    return Array.isArray(value)?value.filter(point=>Number.isFinite(point?.latitude)&&Number.isFinite(point?.longitude)).slice(0,250):[];
  }catch(_){return []}
}
function saveMissionDraft(){
  try{localStorage.setItem('sentinel.mission.draft.v1',JSON.stringify(missionWaypoints))}catch(_){}
}
function loadMissionRecord(){
  try{return JSON.parse(localStorage.getItem('sentinel.mission.record.v1')||'null')}catch(_){return null}
}
function saveMissionRecord(){
  try{localStorage.setItem('sentinel.mission.record.v1',JSON.stringify(missionRecord))}catch(_){}
}
function updateClock(){
  const now=Date.now()/1000;text('mission-clock',new Date().toISOString().slice(11,19));
  if(latestTelemetry){const age=Math.max(0,now-Number(latestTelemetry.timestamp||0));text('gps-state',age>10?'LOST':age>2?`STALE ${age.toFixed(1)}s`:String(latestTelemetry.gps_fix||'UNKNOWN').replaceAll('_',' '));text('sensor-gps-age',`${age.toFixed(1)}s`);}
  if(latestVision){const age=Math.max(0,now-Number(latestVision.timestamp||0));text('sensor-camera-age',`${age.toFixed(1)}s`);if(age>5){text('preview-status',`STALE ${age.toFixed(1)}s`);text('wall-camera-state',`STALE ${age.toFixed(1)}s`);setFooterLight('status-video','bad')}}
  if(latestRange)text('sensor-lidar-age',`${Math.max(0,now-Number(latestRange.timestamp||0)).toFixed(1)}s`);
  updateCameraFrameAge();
}
function setFooterLight(id,grade){const node=byId(id);if(node)node.className=grade||''}
function setCameraStreamState(state){
  ['wall-live-light','wall-live-indicator'].forEach(id=>{const light=byId(id);if(light)light.className=state||''});
}
function updateCameraFrameAge(){
  if(!previewRenderedAt)return;
  const seconds=Math.max(0,(Date.now()-previewRenderedAt)/1000),label=seconds<1?`${Math.round(seconds*1000)} ms ago`:`${seconds.toFixed(1)} s ago`;
  text('wall-frame-age',label);text('preview-frame-age',label);
  if(seconds>5){setCameraStreamState('bad');text('camera-feed-summary','Primary stream stale · 3 offline')}
}
function haversine(a,b){
  const earth=6371000,toRad=Math.PI/180,dLat=(b.latitude-a.latitude)*toRad,dLon=(b.longitude-a.longitude)*toRad;
  const p=Math.sin(dLat/2)**2+Math.cos(a.latitude*toRad)*Math.cos(b.latitude*toRad)*Math.sin(dLon/2)**2;
  return 2*earth*Math.asin(Math.sqrt(p));
}
function geoToWorld(latitude,longitude,zoom){
  const size=MAP_TILE_SIZE*2**zoom,lat=clamp(Number(latitude),-85.05112878,85.05112878),sin=Math.sin(lat*Math.PI/180);
  return{x:(Number(longitude)+180)/360*size,y:(.5-Math.log((1+sin)/(1-sin))/(4*Math.PI))*size};
}
function worldToGeo(x,y,zoom){
  const size=MAP_TILE_SIZE*2**zoom,longitude=x/size*360-180,n=Math.PI-2*Math.PI*y/size,latitude=180/Math.PI*Math.atan(Math.sinh(n));
  return{latitude,longitude};
}
function tileUrl(template,zoom,x,y){return template.replace('{z}',zoom).replace('{x}',x).replace('{y}',y)}
function requestMapTile(source,template,zoom,x,y){
  const count=2**zoom,wrappedX=((x%count)+count)%count;if(y<0||y>=count)return null;const key=`${source}/${zoom}/${wrappedX}/${y}`,existing=mapTiles.get(key);if(existing&&!(existing.status==='failed'&&performance.now()-existing.failedAt>5000))return existing;if(existing)mapTiles.delete(key);
  if(mapTiles.size>180){const removable=[...mapTiles.entries()].find(([,value])=>value.status!=='loading');if(removable)mapTiles.delete(removable[0])}
  const tile={status:'loading',image:new Image(),loadedAt:0};mapTiles.set(key,tile);tile.image.referrerPolicy='strict-origin-when-cross-origin';tile.image.onload=()=>{tile.status='ready';tile.loadedAt=performance.now();drawTacticalPlot()};tile.image.onerror=()=>{tile.status='failed';tile.failedAt=performance.now();drawTacticalPlot()};tile.image.src=tileUrl(template,zoom,wrappedX,y);return tile;
}

function setWorkspace(name){
  const workspaces=['flight','plan','camera','tracks','alerts','sensors','systems','analyze','evidence','settings'];
  activeWorkspace=workspaces.includes(name)?name:'flight';
  document.body.dataset.workspace=activeWorkspace;
  document.querySelectorAll('button[data-workspace]').forEach(button=>button.classList.toggle('active',button.dataset.workspace===activeWorkspace));
  document.querySelectorAll('.workspace-view').forEach(view=>view.classList.toggle('hidden',!String(view.dataset.view||'').split(' ').includes(activeWorkspace)));
  if(activeWorkspace!=='plan'&&activeMapTool==='waypoint')setMapTool('select');
  requestAnimationFrame(drawTacticalPlot);
}
function setMapTool(tool){
  activeMapTool=tool;
  document.querySelectorAll('[data-map-tool]').forEach(button=>button.classList.toggle('active',button.dataset.mapTool===tool));
  byId('map-workspace').classList.toggle('waypoint-mode',tool==='waypoint');
  byId('map-hint').classList.toggle('hidden',tool!=='waypoint');
}
function setMapLayer(layer){
  activeMapLayer=layer;
  document.querySelectorAll('[data-map-layer]').forEach(button=>button.classList.toggle('active',button.dataset.mapLayer===layer));
  drawTacticalPlot();
}
function currentMapStyle(){const view=MAP_VIEWS[activeMapView]||MAP_VIEWS.street;return{...view,template:view.template===null?mapTileTemplate:view.template}}
function setMapView(view){
  activeMapView=MAP_VIEWS[view]?view:'street';
  document.querySelectorAll('[data-map-view]').forEach(button=>button.classList.toggle('active',button.dataset.mapView===activeMapView));
  try{localStorage.setItem('sentinel.map.view',activeMapView)}catch(_){}
  drawTacticalPlot();
}

function applyTelemetry(data){
  if(!data)return;
  latestTelemetry=data;
  text('vehicle-name',String(data.vehicle_id||'UNIDENTIFIED').toUpperCase());text('flight-mode',String(data.flight_mode||'N/A').toUpperCase());
  text('gps-state',String(data.gps_fix||'UNKNOWN').replaceAll('_',' '));text('altitude',num(data.altitude_m));text('speed',num(data.ground_speed_mps));
  const rawHeading=Number(data.heading_deg),headingAvailable=Boolean(data.attitude_valid&&Number.isFinite(rawHeading));
  const headingDegrees=headingAvailable?((rawHeading%360)+360)%360:0;
  text('heading',headingAvailable?`${headingDegrees.toFixed(0).padStart(3,'0')}°`:'—');
  text('heading-cardinal',headingAvailable?cardinalFromHeading(headingDegrees):'NO HEADING');
  text('heading-status',headingAvailable?'LIVE HEADING':'IMU REQUIRED');
  text('heading-note',headingAvailable?'Aircraft-forward reference':'Awaiting flight-controller telemetry');
  const headingRose=byId('heading-rose');if(headingRose)headingRose.style.transform=`rotate(${headingAvailable?-headingDegrees:0}deg)`;
  text('battery',data.battery_percent==null?'--':num(data.battery_percent,0));
  text('rssi',data.link_quality_percent==null?'--':num(data.link_quality_percent,0));
  text('position',`${num(data.latitude,5)}, ${num(data.longitude,5)}`);text('attitude-state',data.attitude_valid?`${num(data.roll_deg,0)}° R / ${num(data.pitch_deg,0)}° P`:'NO ATTITUDE');
  const shift=clamp(Number(data.pitch_deg)||0,-30,30)*.8,rotation=-clamp(Number(data.roll_deg)||0,-60,60);
  ['.attitude-sky','.attitude-ground','.attitude-horizon'].forEach(selector=>{const node=document.querySelector(selector);if(node)node.style.transform=`translateY(${shift}px) rotate(${rotation}deg)`});
  text('sensor-gps-fix',String(data.gps_fix||'UNKNOWN').replaceAll('_',' '));text('sensor-gps-sat',data.satellites_visible==null?'N/A':String(data.satellites_visible));text('sensor-gps-hdop',data.hdop==null?'N/A':num(data.hdop,1));
  text('sensor-imu-state',data.attitude_valid?'LIVE':'UNKNOWN');text('sensor-roll',data.attitude_valid?`${num(data.roll_deg,1)}°`:'N/A');text('sensor-pitch',data.attitude_valid?`${num(data.pitch_deg,1)}°`:'N/A');text('sensor-heading',headingAvailable?`${headingDegrees.toFixed(1)}°`:'N/A');
  text('sensor-battery',data.battery_percent==null?'N/A':`${num(data.battery_percent,0)}%`);text('sensor-link',data.link_quality_percent==null?'N/A':`${num(data.link_quality_percent,0)}%`);text('sensor-vehicle',String(data.vehicle_id||'UNIDENTIFIED'));
  updateMissionStats();drawTacticalPlot();
}
function applyRange(data){if(data){latestRange=data;text('lidar',num(data.distance_m));text('sensor-lidar-state','LIVE');text('sensor-lidar-range',`${num(data.distance_m,2)} m`);text('sensor-lidar-orientation',String(data.orientation||'UNKNOWN').toUpperCase())}}
function applyVision(data){
  if(!data)return;
  latestVision=data;
  const processing=data.status==='processing',model=String(data.model_name||'YOLO11').split('/').pop().toUpperCase();
  text('preview-camera',String(data.source||'camera-01').toUpperCase());text('capture-fps',num(data.capture_fps));text('preview-fps',num(data.inference_fps));
  text('preview-latency',num(data.last_end_to_end_ms,0));text('frame-count',`FRAME ${data.frames_inferred??'--'}`);text('sensor-detections',data.last_detection_count??tracks.size);
  text('model-name',model);text('wall-model-name',model);text('wall-fps',`${num(data.inference_fps)} FPS`);
  text('wall-latency',`${num(data.last_end_to_end_ms,0)} ms`);text('wall-detections',`${data.last_detection_count??tracks.size} track${Number(data.last_detection_count??tracks.size)===1?'':'s'}`);
  text('model-integrity',data.model_integrity_verified?'MODEL VERIFIED':'MODEL UNVERIFIED');
  text('sensor-camera-state',processing?'LIVE':'DEGRADED');text('sensor-camera-fps',`${num(data.capture_fps)} FPS`);text('sensor-camera-source',String(data.source||'N/A'));text('settings-model',model);text('settings-model-integrity',data.model_integrity_verified?'VERIFIED':'UNVERIFIED');text('settings-vision-device',String(data.device||'N/A').toUpperCase());
  text('preview-status',processing?'LIVE':'WAITING');text('wall-camera-state',processing?'LIVE / PROCESSING':String(data.status||'WAITING').toUpperCase());text('camera-feed-summary',processing?'1 live · 3 offline':'1 configured · 3 offline');setCameraStreamState(processing?'good':'warn');
  setFooterLight('status-video',processing?'good':'bad');setFooterLight('status-model',processing?'good':'warn');
}

function rememberTrack(track){
  if(!track?.track_id||!track?.location)return;
  const history=trackTrails.get(track.track_id)||[],point={latitude:Number(track.location.latitude),longitude:Number(track.location.longitude),timestamp:Number(track.timestamp)||Date.now()/1000};
  const previous=history.at(-1);
  if(!previous||previous.latitude!==point.latitude||previous.longitude!==point.longitude)history.push(point);
  trackTrails.set(track.track_id,history.slice(-18));
}

async function verifySelectedEvidence(evidenceId,button){
  const original=button.textContent;button.disabled=true;button.textContent='VERIFYING';
  try{
    const result=await fetchJson(`/api/evidence/${encodeURIComponent(evidenceId)}/verify`);
    button.textContent=result.valid?'INTEGRITY PASS':'INTEGRITY FAIL';button.className=result.valid?'integrity-good':'integrity-bad';
  }catch(_){button.textContent='VERIFY UNAVAILABLE'}
  finally{setTimeout(()=>{button.textContent=original;button.disabled=false;button.className=''},3500)}
}

function renderTrackDetail(){
  const panel=byId('track-detail'),track=tracks.get(selectedTrackId);panel.replaceChildren();
  if(!track){panel.append(empty('Select a contact on the map or list'));return}
  const grid=document.createElement('dl');grid.className='track-detail-grid';
  const confidence=track.display_confidence??track.confidence,location=track.location;
  [
    ['Track ID',track.track_id],['Class',String(track.class||'unknown').toUpperCase()],
    ['Lifecycle',String(track.lifecycle_state||'ACTIVE').toUpperCase()],
    ['Model confidence',`${Math.round((Number(confidence)||0)*100)}%`],['Risk',String(track.risk?.score??0)],
    ['Position',location?`${num(location.latitude,location.uncertainty_status==='VALIDATED'?5:3)}, ${num(location.longitude,location.uncertainty_status==='VALIDATED'?5:3)}`:'NOT GEOLOCATED'],
    ['Location quality',location?(location.uncertainty_m!=null?`${location.uncertainty_status} ±${num(location.uncertainty_m,1)} m`:`${location.method||'APPROXIMATE'} · UNCERTAINTY UNBOUNDED`):'N/A'],
    ['Observed',new Date((Number(track.timestamp)||0)*1000).toISOString().slice(11,23)],
    ['Motion',String(track.motion?.status||'unknown').toUpperCase()],['Model',String(track.model_version||track.model_name||'unreported')]
  ].forEach(([label,value])=>{const cell=document.createElement('div'),term=document.createElement('dt'),description=document.createElement('dd');term.textContent=label;description.textContent=value;cell.append(term,description);grid.append(cell)});
  panel.append(grid);
  const evidence=track.evidence,footer=document.createElement('div');footer.className='track-evidence';
  const status=document.createElement('span');status.textContent=evidence?`EVIDENCE ${String(evidence.sha256||'').slice(0,12)}…`:'NO STORED EVIDENCE';footer.append(status);
  if(evidence?.evidence_id){const verify=document.createElement('button');verify.type='button';verify.textContent='VERIFY HASH';verify.onclick=()=>verifySelectedEvidence(evidence.evidence_id,verify);footer.append(verify)}
  panel.append(footer);
}

function selectTrack(trackId){selectedTrackId=trackId||'';renderTracks();renderTrackDetail();drawTacticalPlot()}

function renderTracks(){
  const list=byId('object-list');text('object-count',tracks.size);text('sensor-detections',tracks.size);list.replaceChildren();
  if(!tracks.size){list.append(empty('No tracks. Confirmed detections appear here.'));renderTrackWorkspace();drawTacticalPlot();return}
  [...tracks.values()].sort((a,b)=>(b.risk?.score||0)-(a.risk?.score||0)).forEach(track=>{
    rememberTrack(track);const row=document.createElement('article');row.className=`object-row ${track.track_id===selectedTrackId?'selected':''}`;row.tabIndex=0;row.setAttribute('role','button');row.setAttribute('aria-label',`Inspect ${track.class||'object'} track ${track.track_id}`);row.onclick=()=>selectTrack(track.track_id);row.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectTrack(track.track_id)}};
    const main=document.createElement('div');main.className='object-main';const label=document.createElement('b');label.textContent=String(track.class||'object').toUpperCase();
    const confidence=track.display_confidence??track.confidence??0,confidenceLabel=document.createElement('span');confidenceLabel.textContent=`${Math.round(confidence*100)}%`;main.append(label,confidenceLabel);
    const id=document.createElement('div');id.className='object-id';id.textContent=`TRACK ${track.track_id||'UNASSIGNED'}`;
    const bar=document.createElement('div');bar.className='confidence-bar';const fill=document.createElement('i');fill.style.width=`${clamp(confidence*100,0,100)}%`;bar.append(fill);
    const meta=document.createElement('div');meta.className='object-meta';const left=document.createElement('span');left.textContent=String(track.motion?.status||'unknown').toUpperCase();
    const right=document.createElement('span');right.textContent=`RISK ${track.risk?.score??0}`;meta.append(left,right);row.append(main,id,bar,meta);list.append(row);
  });
  if(selectedTrackId&&!tracks.has(selectedTrackId))selectedTrackId='';renderTrackDetail();
  renderTrackWorkspace();drawTacticalPlot();
}

function renderTrackWorkspace(){
  const body=byId('track-table-body');if(!body)return;body.replaceChildren();
  const all=[...tracks.values()],query=String(byId('track-filter')?.value||'').trim().toLowerCase(),classFilter=String(byId('track-class-filter')?.value||'').toLowerCase();
  const classMatches=track=>{const value=String(track.class||'unknown').toLowerCase();if(!classFilter)return true;if(classFilter==='vehicle')return['vehicle','car','truck','bus','motorcycle'].includes(value);if(classFilter==='boat')return['boat','vessel','ship'].includes(value);return value===classFilter};
  const filtered=all.filter(track=>classMatches(track)&&(!query||[track.track_id,track.class,track.lifecycle_state,track.motion?.status].some(value=>String(value||'').toLowerCase().includes(query))));
  text('tracks-workspace-count',`${all.length} active`);text('track-stat-confirmed',all.length);text('track-stat-geolocated',all.filter(track=>track.location).length);text('track-stat-risk',all.filter(track=>Number(track.risk?.score||0)>=60).length);
  if(!filtered.length)tableEmpty(body,8,'track',all.length?'No matching tracks':'No tracks',all.length?'Clear or change the current filters.':'Confirmed detections appear here.');
  filtered.sort((a,b)=>(b.timestamp||0)-(a.timestamp||0)).forEach(track=>{const row=document.createElement('tr');row.className=track.track_id===selectedTrackId?'selected':'';row.tabIndex=0;row.onclick=()=>selectTrack(track.track_id);row.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectTrack(track.track_id)}};const age=Math.max(0,Date.now()/1000-Number(track.timestamp||0)),lifecycle=String(track.lifecycle_state||(age>3?'TEMPORARILY_LOST':age>.75?'OCCLUDED':'ACTIVE')).toUpperCase(),locationState=track.location?(track.location.uncertainty_status==='VALIDATED'?'VALIDATED GEO':'APPROXIMATE GEO'):'N/A';[track.track_id,String(track.class||'unknown').toUpperCase(),`${Math.round(Number(track.display_confidence??track.confidence??0)*100)}%`,lifecycle,String(track.motion?.status||'UNKNOWN').toUpperCase(),locationState,String(track.risk?.score??0),`${age.toFixed(1)}s`].forEach(value=>{const cell=document.createElement('td');cell.textContent=value;row.append(cell)});body.append(row)});
  const detail=byId('tracks-workspace-detail'),track=tracks.get(selectedTrackId);detail.replaceChildren();if(!track){detail.append(inspectorEmpty());return}const clone=byId('track-detail').cloneNode(true);clone.removeAttribute('id');detail.append(...clone.childNodes);
}
function openAcknowledgeDialog(eventId){
  openEventTransitionDialog(eventId,'ACKNOWLEDGED');
}
function openEventTransitionDialog(eventId,state){
  const event=events.get(eventId);if(!event||['RESOLVED','DISMISSED'].includes(event.state))return;pendingAckEventId=eventId;pendingEventState=state;selectedEventId=eventId;renderEvents();
  const labels={ACKNOWLEDGED:'Acknowledge security event',UNDER_REVIEW:'Place event under review',RESOLVED:'Resolve security event',DISMISSED:'Dismiss security event'};text('ack-title',labels[state]||'Review security event');text('ack-confirm',state==='ACKNOWLEDGED'?'Record review':`Record ${state.replaceAll('_',' ').toLowerCase()}`);
  text('ack-event-summary',`${String(event.severity||'info').toUpperCase()} · ${String(event.event_type||'event').replaceAll('_',' ')} · ${event.message||''}`);byId('ack-justification').value='';byId('ack-dialog').showModal();requestAnimationFrame(()=>byId('ack-justification').focus());
}
async function submitAcknowledgement(submitEvent){
  submitEvent.preventDefault();const justification=byId('ack-justification').value.trim();if(justification.length<8)return;
  const button=byId('ack-confirm');button.disabled=true;button.textContent='RECORDING';
  try{const acknowledgement=pendingEventState==='ACKNOWLEDGED',path=acknowledgement?`/api/events/${encodeURIComponent(pendingAckEventId)}/acknowledge`:`/api/events/${encodeURIComponent(pendingAckEventId)}/transition`,payload=acknowledgement?{acknowledged:true,justification}:{state:pendingEventState,justification};const response=await authFetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!response.ok)throw new Error();const event=await response.json();events.set(event.id,event);byId('ack-dialog').close();pendingAckEventId='';pendingEventState='ACKNOWLEDGED';renderEvents()}
  catch(_){button.textContent='REVIEW FAILED — RETRY'}finally{button.disabled=false;if(button.textContent==='RECORDING')button.textContent='Record review'}
}
function appendEventActions(container,event){
  const state=event.state||(event.acknowledged?'ACKNOWLEDGED':'NEW'),actions=state==='NEW'?[['REVIEW','ACKNOWLEDGED']]:state==='ACKNOWLEDGED'?[['INVESTIGATE','UNDER_REVIEW'],['RESOLVE','RESOLVED']]:state==='UNDER_REVIEW'?[['RESOLVE','RESOLVED'],['DISMISS','DISMISSED']]:[];
  if(!actions.length){const closed=document.createElement('span');closed.textContent=state;container.append(closed);return}
  actions.forEach(([label,next])=>{const button=document.createElement('button');button.type='button';button.textContent=label;button.onclick=clickEvent=>{clickEvent.stopPropagation();openEventTransitionDialog(event.id,next)};container.append(button)});
}
function renderEvents(){
  const list=byId('event-list'),active=[...events.values()].filter(item=>!item.acknowledged);text('event-count',active.length);list.replaceChildren();
  if(!events.size){list.append(empty('No alerts. Event rules are monitoring confirmed tracks.'));renderAlertWorkspace();return}
  const severity={critical:3,warning:2,info:1};[...events.values()].sort((a,b)=>Number(a.acknowledged)-Number(b.acknowledged)||(severity[b.severity]||0)-(severity[a.severity]||0)||b.timestamp-a.timestamp).slice(0,40).forEach(event=>{
    const row=document.createElement('article');row.className=`event-row ${event.severity||'info'} ${event.id===selectedEventId?'selected':''}`;row.tabIndex=0;row.onclick=()=>{selectedEventId=event.id;renderEvents()};row.onkeydown=keyEvent=>{if(keyEvent.key==='Enter'){selectedEventId=event.id;renderEvents()}else if(keyEvent.key.toLowerCase()==='a')openAcknowledgeDialog(event.id)};
    const top=document.createElement('div');top.className='event-top';const kind=document.createElement('b');kind.textContent=String(event.event_type||'event').replaceAll('_',' ');
    const time=document.createElement('time');time.textContent=new Date(event.timestamp*1000).toLocaleTimeString();top.append(kind,time);
    const message=document.createElement('p');message.textContent=event.message||'Security event received';
    const meta=document.createElement('div');meta.className='event-meta';const details=document.createElement('span');details.textContent=`RISK ${event.risk_score??0} · ${String(event.origin||'local').toUpperCase()}`;meta.append(details);
    appendEventActions(meta,event);
    row.append(top,message,meta);list.append(row);
  });renderAlertWorkspace();
}
function renderAlertWorkspace(){
  const body=byId('alert-table-body');if(!body)return;body.replaceChildren();const all=[...events.values()],open=all.filter(event=>!['RESOLVED','DISMISSED'].includes(event.state||'NEW')),query=String(byId('alert-filter')?.value||'').trim().toLowerCase(),severityFilter=String(byId('alert-severity-filter')?.value||'').toLowerCase();
  const filtered=all.filter(event=>(!severityFilter||String(event.severity||'info').toLowerCase()===severityFilter)&&(!query||[event.event_type,event.origin,event.track_id,event.message,event.state].some(value=>String(value||'').toLowerCase().includes(query))));
  text('alerts-workspace-count',`${open.length} open`);text('alert-stat-open',open.length);text('alert-stat-critical',open.filter(event=>String(event.severity).toLowerCase()==='critical').length);text('alert-stat-review',open.filter(event=>String(event.state).toUpperCase()==='UNDER_REVIEW').length);
  if(!filtered.length)tableEmpty(body,8,'alert',all.length?'No matching alerts':'No alerts',all.length?'Clear or change the current filters.':'Event and geofence rules monitor confirmed tracks.');
  filtered.sort((a,b)=>b.timestamp-a.timestamp).forEach(event=>{const row=document.createElement('tr');row.className=event.severity||'info';[String(event.severity||'info').toUpperCase(),new Date(event.timestamp*1000).toISOString().slice(11,19),String(event.event_type||'event').replaceAll('_',' '),String(event.origin||'local'),event.track_id||'N/A',event.state||(event.acknowledged?'ACKNOWLEDGED':'NEW'),event.message||'N/A'].forEach(value=>{const cell=document.createElement('td');cell.textContent=value;row.append(cell)});const action=document.createElement('td');action.className='event-actions';appendEventActions(action,event);row.append(action);body.append(row)});renderAnalysis();renderEvidenceWorkspace();
}
function renderDevices(){
  const list=byId('v2x-list'),all=[...devices.values()],online=all.filter(device=>device.link_status!=='offline').length;text('v2x-count',`${online} ONLINE`);list.replaceChildren();
  if(!all.length){list.append(empty('No authenticated peers'));return}
  all.sort((a,b)=>String(a.device_id).localeCompare(String(b.device_id))).forEach(device=>{
    const row=document.createElement('article');row.className=`device-row ${device.link_status}`;const light=document.createElement('i'),content=document.createElement('div'),name=document.createElement('b'),details=document.createElement('small'),state=document.createElement('span');
    name.textContent=String(device.device_id).toUpperCase();details.textContent=`${String(device.device_type).toUpperCase()} · ${device.transport} · ${num(device.age_s,1)}s`;content.append(name,details);state.textContent=String(device.link_status).toUpperCase();row.append(light,content,state);list.append(row);
  });
}
function renderAdvisories(){
  const list=byId('advisory-list');list.replaceChildren();
  const rows=[...securityAdvisories.map(item=>({time:item.reviewed_at,title:`SECURITY / ${item.status}`,body:item.summary,provider:item.provider})),...evidenceVerifications.map(item=>({time:item.reviewed_at,title:`EVIDENCE / ${item.verdict}`,body:item.rationale,provider:item.provider}))].sort((a,b)=>b.time-a.time).slice(0,12);
  if(!rows.length){list.append(empty('No advisory reviews'));return}
  rows.forEach(item=>{const row=document.createElement('article');row.className='advisory-row';const title=document.createElement('b');title.textContent=item.title;const body=document.createElement('p');body.textContent=item.body;const source=document.createElement('small');source.textContent=`${String(item.provider||'local').toUpperCase()} · ADVISORY ONLY`;row.append(title,body,source);list.append(row)});
}
function renderAnalysis(){
  const list=byId('analysis-timeline');if(!list)return;list.replaceChildren();
  const source=replayMode?replayRecords:[...[...events.values()].map(item=>({...item,kind:'event'})),...[...tracks.values()].map(item=>({...item,kind:'track'}))];
  const rows=source.map(item=>item.kind==='event'?{timestamp:item.timestamp,type:'EVENT',title:String(item.event_type||'event').replaceAll('_',' '),detail:`${String(item.severity||'info').toUpperCase()} · ${item.state||'NEW'} · ${item.track_id||'NO TRACK'}`}:{timestamp:item.timestamp,type:'TRACK',title:`${String(item.class||'object').toUpperCase()} · ${item.track_id}`,detail:`MODEL CONFIDENCE ${Math.round(Number(item.display_confidence??item.confidence??0)*100)}% · RISK ${item.risk_score??item.risk?.score??0}`}).sort((a,b)=>b.timestamp-a.timestamp).slice(0,500);
  if(!rows.length){list.append(empty(replayMode?'No records in the selected replay window':'No current track or event history'));return}rows.forEach(item=>{const row=document.createElement('article'),time=document.createElement('time'),content=document.createElement('div'),title=document.createElement('b'),detail=document.createElement('span');time.textContent=new Date(item.timestamp*1000).toISOString();title.textContent=`${item.type} · ${item.title}`;detail.textContent=item.detail;content.append(title,detail);row.append(time,content);list.append(row)})
}
function localDateTimeValue(date){return new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16)}
function initializeReplayWindow(){const end=new Date(),start=new Date(end.getTime()-15*60*1000);byId('replay-start').value=localDateTimeValue(start);byId('replay-end').value=localDateTimeValue(end)}
function setReplayMode(enabled,records=[]){replayMode=enabled;replayRecords=enabled?records.slice(0,2000):[];document.body.classList.toggle('replay-mode',enabled);text('analysis-mode',enabled?`REPLAY · READ ONLY · ${replayRecords.length}`:'LIVE HISTORY');byId('replay-exit').disabled=!enabled;renderAnalysis()}
async function loadReplay(){
  const button=byId('replay-load'),start=Date.parse(byId('replay-start').value)/1000,end=Date.parse(byId('replay-end').value)/1000;if(!Number.isFinite(start)||!Number.isFinite(end)||end<=start){text('analysis-mode','INVALID TIME RANGE');return}button.disabled=true;button.textContent='LOADING';
  try{const response=await authFetch(`/api/history?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}&limit=2000`),payload=await response.json();if(!response.ok)throw new Error(payload.detail||`REPLAY FAILED ${response.status}`);if(payload.mode!=='REPLAY'||!Array.isArray(payload.records))throw new Error('INVALID REPLAY RESPONSE');setReplayMode(true,payload.records)}
  catch(error){setReplayMode(false);text('analysis-mode',String(error.message||'REPLAY UNAVAILABLE').toUpperCase())}finally{button.disabled=false;button.textContent='Load replay'}
}
function renderEvidenceWorkspace(){
  const list=byId('evidence-workspace-list');if(!list)return;list.replaceChildren();const evidence=[...tracks.values()].filter(track=>track.evidence).map(track=>({track_id:track.track_id,...track.evidence}));if(!evidence.length&&!evidenceVerifications.length){list.append(empty('No encrypted evidence records in the live snapshot'));return}evidence.forEach(item=>{const card=document.createElement('article'),title=document.createElement('b'),hash=document.createElement('code'),meta=document.createElement('span'),button=document.createElement('button');title.textContent=`TRACK ${item.track_id}`;hash.textContent=String(item.sha256||'HASH UNKNOWN');meta.textContent=`${item.evidence_id||'NO ID'} · AES-256-GCM`;button.textContent='VERIFY EVIDENCE';button.disabled=!item.evidence_id;if(item.evidence_id)button.onclick=()=>verifySelectedEvidence(item.evidence_id,button);card.append(title,hash,meta,button);list.append(card)});evidenceVerifications.slice(-20).reverse().forEach(item=>{const card=document.createElement('article'),title=document.createElement('b'),meta=document.createElement('span'),body=document.createElement('p');title.textContent=`AI ADVISORY · ${String(item.verdict).toUpperCase()}`;meta.textContent=String(item.provider||'provider');body.textContent=item.rationale;card.append(title,meta,body);list.append(card)})
}

function renderLayers(){
  const compact=byId('layer-list'),grid=byId('systems-layer-grid');compact.replaceChildren();grid.replaceChildren();
  const readinessById=new Map((readiness?.checks||[]).map(check=>[check.id,check])),layers=capabilities?.layer_status||[];
  if(!layers.length){compact.append(empty('Layer status unavailable'));grid.append(empty('Layer status unavailable'));return}
  let good=0;
  layers.forEach(layer=>{
    const check=readinessById.get(layer.id),state=check?(check.passed?'ready':'degraded'):layer.state,grade=statusClass(state);if(grade==='good')good+=1;
    const presentation=layerPresentation(layer);const row=document.createElement('div');row.className='layer-row';const light=document.createElement('i');light.className=grade;const name=document.createElement('b');name.textContent=presentation.title;const value=document.createElement('small');value.textContent=String(state).replaceAll('_',' ');row.append(light,name,value);compact.append(row);
    const card=document.createElement('article');card.className=`system-layer-card ${grade}`;const cardLight=document.createElement('i');cardLight.className=grade;const content=document.createElement('div'),cardName=document.createElement('b'),description=document.createElement('small'),cardState=document.createElement('span');cardName.textContent=presentation.title;description.textContent=presentation.detail;cardState.textContent=String(state).replaceAll('_',' ');content.append(cardName,description,cardState);card.append(cardLight,content);grid.append(card);
  });
  text('readiness-score',`${good} / ${layers.length}`);text('systems-summary',`${good} / ${layers.length} READY`);
}
function applyHealth(data){
  const failSafe=data?.fail_safe||{},strip=byId('failsafe-strip'),nominal=data?.status==='ok'&&failSafe.critical_path_healthy;
  if(data?.simulation){strip.className='system-banner degraded';text('failsafe-title','Simulation mode');text('failsafe-detail','Live camera, vehicle and sensor links are not connected.');return}
  strip.className=`system-banner ${nominal?'nominal':failSafe.fail_safe_active?'critical':'degraded'}`;text('failsafe-title',nominal?'System nominal':'Degraded operation');
  text('failsafe-detail',nominal?'Critical surveillance layers are healthy.':'One or more critical layers require operator attention.');
  setFooterLight('status-storage',data?.postgis?'good':'bad');setFooterLight('status-transport',data?.mqtt?'good':'bad');
  const v2x=data?.v2x||{};text('v2x-mode',v2x.enabled?'SIGNED GATEWAY ENABLED':'GATEWAY DISABLED');text('v2x-tls',`TLS: ${v2x.tls_configured?'CONFIGURED':'LOCAL DEV MODE'}`);setFooterLight('status-v2x',v2x.enabled?(v2x.tls_configured?'good':'warn'):'bad');
  const verifier=data?.llm_verifier||{},adviser=data?.security_llm_adviser||{},llmOnline=(verifier.enabled&&verifier.worker)||(adviser.enabled&&adviser.worker);
  const provider=String(verifier.provider||adviser.provider||'local').toLowerCase(),providerNames={openrouter:'OpenRouter',xai:'xAI',grok:'xAI',google:'Google',gemini:'Google'},providerName=providerNames[provider]||provider.toUpperCase();
  const supported=Array.isArray(verifier.supported_providers)?verifier.supported_providers:[],reasons=Array.isArray(verifier.disabled_reasons)?verifier.disabled_reasons:[];
  text('llm-state',llmOnline?'ONLINE':'ISOLATED');text('llm-provider-label',`${providerName} · advisory only`);text('llm-provider-header',`${providerName.toUpperCase()} ${llmOnline?'ON':'OFF'}`);
  text('llm-provider-footer',`ADVISER ${providerName.toUpperCase()} ${llmOnline?'ON':'OFF'}`);setFooterLight('status-adviser',llmOnline?'good':verifier.key_configured?'warn':'bad');
  text('llm-model-value',String(verifier.model||adviser.model||'—'));text('llm-key-state',verifier.key_configured?'Configured':'Missing for selected provider');
  text('llm-egress-state',verifier.external_image_egress_approved?'Approved':'Blocked');text('llm-disabled-reason',llmOnline?'Worker healthy':(reasons[0]||'Provider inactive'));
  text('settings-llm-provider',`${providerName.toUpperCase()} · ${llmOnline?'READY':'DISABLED'}`);text('settings-llm-egress',verifier.external_image_egress_approved?'APPROVED':'BLOCKED');
  const openRouterSelected=provider==='openrouter',openRouterAvailable=supported.includes('openrouter');
  text('openrouter-adapter-state',openRouterSelected?(verifier.key_configured?(llmOnline?'Active':'Selected · inactive'):'Selected · key required'):(openRouterAvailable?'Available · not selected':'Unavailable'));
}
function applySnapshot(data){
  applyTelemetry(data.telemetry);applyRange(data.range_measurement);(data.vision_metrics||[]).forEach(applyVision);geofences=data.geofences||[];
  tracks.clear();(data.tracks||[]).forEach(item=>tracks.set(item.track_id,item));events.clear();(data.events||[]).forEach(item=>events.set(item.id,item));devices.clear();(data.v2x_devices||[]).forEach(item=>devices.set(item.device_id,item));
  evidenceVerifications=data.evidence_verifications||[];securityAdvisories=data.security_advisories||[];renderTracks();renderEvents();renderDevices();renderAdvisories();renderAnalysis();renderEvidenceWorkspace();drawTacticalPlot();
}
function applyMessage(type,data){
  if(type==='snapshot')applySnapshot(data);else if(type==='telemetry')applyTelemetry(data);else if(type==='range')applyRange(data);else if(type==='vision_metrics')applyVision(data);else if(type==='track'){tracks.set(data.track_id,data);rememberTrack(data);renderTracks()}else if(type==='track_expired'){tracks.delete(data.track_id);trackTrails.delete(data.track_id);renderTracks()}else if(type==='event'){events.set(data.id,data);renderEvents()}else if(type==='geofence'){geofences=[...geofences.filter(item=>item.id!==data.id),data];drawTacticalPlot()}else if(type==='v2x_device'){devices.set(data.device_id,data);renderDevices()}else if(type==='evidence_verification'){evidenceVerifications.push(data);renderAdvisories()}else if(type==='security_advisory'){securityAdvisories.push(data);renderAdvisories()}
}

function setConnectionState(label,grade,retryMs=0){const node=byId('connection'),light=document.createElement('i');if(connectionRetryTimer){clearInterval(connectionRetryTimer);connectionRetryTimer=null}node.replaceChildren(light,document.createTextNode(label));node.className=`connection-state ${grade}${retryMs?' retrying':''}`;if(retryMs){const deadline=Date.now()+retryMs;node.style.setProperty('--retry-duration',`${retryMs}ms`);connectionRetryTimer=setInterval(()=>{const remaining=Math.max(0,deadline-Date.now());node.lastChild.textContent=`Reconnecting · ${(remaining/1000).toFixed(1)} s`;if(!remaining){clearInterval(connectionRetryTimer);connectionRetryTimer=null}},100)}}
function connectOperations(){
  if(!LOCAL_OPERATOR_MODE&&!accessToken)return;
  if(socket&&(socket.readyState===WebSocket.CONNECTING||socket.readyState===WebSocket.OPEN))return;
  if(socketHeartbeat)clearInterval(socketHeartbeat);
  const connection=new WebSocket(websocketUrl('/ws/operations'));socket=connection;
  connection.onopen=()=>{if(socket!==connection||connection.readyState!==WebSocket.OPEN)return;setConnectionState('Connecting','warning');connection.send(JSON.stringify({type:'authenticate',access_token:accessToken}))};
  connection.onmessage=event=>{if(socket!==connection)return;try{const message=JSON.parse(event.data);if(message.type==='session'&&message.data?.authenticated){socketRetry=0;setConnectionState('Connected','live');if(socketHeartbeat)clearInterval(socketHeartbeat);socketHeartbeat=setInterval(()=>{if(connection.readyState===WebSocket.OPEN)connection.send('keepalive')},15000);return}applyMessage(message.type,message.data)}catch(_){}};
  connection.onclose=event=>{if(socket!==connection)return;socket=null;if(socketHeartbeat)clearInterval(socketHeartbeat);if(event.code===4401||event.code===4403){clearSession(event.code===4403?'Insufficient role':'Session expired');return}socketRetry+=1;const delay=Math.min(15000,500*2**Math.min(socketRetry,5));setConnectionState(`Reconnecting · ${(delay/1000).toFixed(1)} s`,'warning',delay);setTimeout(connectOperations,delay)};
}
function showLogin(message='Authentication required'){
  if(LOCAL_OPERATOR_MODE)return;byId('login-error').textContent=message;byId('auth-gate').classList.remove('hidden');document.body.classList.add('auth-locked');
}
function hideLogin(){const gate=byId('auth-gate');if(gate)gate.classList.add('hidden');document.body.classList.remove('auth-locked')}
function clearSession(message='Session expired'){
  accessToken='';sessionStorage.removeItem('sentinel.access_token');if(socket)socket.close();if(LOCAL_OPERATOR_MODE){startRuntime();return}showLogin(message);
}
async function authFetch(path,options={}){
  const headers=new Headers(options.headers||{});if(accessToken)headers.set('Authorization',`Bearer ${accessToken}`);
  const response=await fetch(apiUrl(path),{...options,headers,cache:options.cache||'no-store',mode:'cors'});
  if(response.status===401){clearSession();throw new Error('Authentication required')}
  return response;
}
async function fetchJson(path){const response=await authFetch(path);if(!response.ok)throw new Error(`${path} returned ${response.status}`);return response.json()}
async function signIn(event){
  event.preventDefault();const button=byId('login-submit');button.disabled=true;text('login-error','Signing in…');
  try{
    const form=new URLSearchParams({username:byId('login-username').value,password:byId('login-password').value,grant_type:'password'});
    const response=await fetch(apiUrl('/api/auth/token'),{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:form,mode:'cors'});
    if(!response.ok)throw new Error('Invalid username or password');const payload=await response.json();accessToken=payload.access_token;sessionStorage.setItem('sentinel.access_token',accessToken);byId('login-password').value='';hideLogin();startRuntime();
  }catch(error){showLogin(error.message||'Sign-in failed')}finally{button.disabled=false}
}
function applyCapabilitiesPayload(payload){capabilities=payload;const configured=String(capabilities?.map?.tile_url_template||'').trim(),allowed=configured.startsWith('/')||configured.startsWith('https://tile.openstreetmap.org/');if(allowed&&configured.includes('{z}')&&configured.includes('{x}')&&configured.includes('{y}')&&configured!==mapTileTemplate){mapTileTemplate=configured;mapTiles.clear();drawTacticalPlot()}const streetTemplate=String(capabilities?.map?.street_view_url_template||'').trim();if(streetTemplate.startsWith('https://www.google.com/maps/')&&streetTemplate.includes('{lat}')&&streetTemplate.includes('{lon}'))streetViewUrlTemplate=streetTemplate;text('map-attribution-state',String(capabilities?.map?.attribution||'STANDARD TILES').toUpperCase())}
function applyDevicePayload(payload){devices.clear();(payload?.devices||[]).forEach(item=>devices.set(item.device_id,item));renderDevices()}
function applyUiBootstrap(bundle){applyHealth(bundle.health);readiness=bundle.readiness;applyCapabilitiesPayload(bundle.capabilities);applyDevicePayload(bundle.v2x);applySnapshot(bundle.snapshot);renderLayers()}
async function refreshSystemState(){
  try{const bundle=await fetchJson('/api/ui/bootstrap');applyUiBootstrap(bundle);return}catch(_){}
  const [healthResult,readinessResult,capabilitiesResult,devicesResult,snapshotResult]=await Promise.allSettled([fetchJson('/api/health'),fetchJson('/api/readiness'),fetchJson('/api/capabilities'),fetchJson('/api/v2x/devices'),fetchJson('/api/snapshot')]);
  if(healthResult.status==='fulfilled')applyHealth(healthResult.value);else{text('failsafe-title','BACKEND LINK DEGRADED');text('failsafe-detail','Health endpoint unavailable')}
  if(readinessResult.status==='fulfilled')readiness=readinessResult.value;if(capabilitiesResult.status==='fulfilled')applyCapabilitiesPayload(capabilitiesResult.value);
  if(devicesResult.status==='fulfilled')applyDevicePayload(devicesResult.value);
  if(snapshotResult.status==='fulfilled')applySnapshot(snapshotResult.value);
  renderLayers();
}
function renderOperatorAssets(assets=[]){
  const list=byId('operator-asset-list');if(!list)return;list.replaceChildren();
  if(!assets.length){list.append(empty('No additional assets registered.'));return}
  assets.forEach(asset=>{const row=document.createElement('article'),title=document.createElement('b'),detail=document.createElement('small'),state=document.createElement('span');row.className='operator-asset-row';title.textContent=String(asset.device_id||'ASSET').toUpperCase();detail.textContent=`${String(asset.device_type||'asset').toUpperCase()} · ${String(asset.endpoint||'').replace(/^https?:\/\//,'')}`;state.textContent=String(asset.status||'registered').toUpperCase();row.append(title,detail,state);list.append(row)});
}
async function loadOperatorConfiguration(){
  try{const response=await authFetch('/api/operator/config');if(!response.ok)throw new Error(`CONFIG ${response.status}`);const config=await response.json(),input=byId('camera-source-input');if(input&&document.activeElement!==input)input.value=config.camera_source||'';renderOperatorAssets(config.assets||[]);text('camera-source-status',config.camera_source?'Bridge hot reload enabled':'No primary source configured')}catch(error){text('camera-source-status','Configuration unavailable')}
}
async function saveCameraSource(event){
  event.preventDefault();const input=byId('camera-source-input'),button=event.currentTarget.querySelector('button[type="submit"]'),source=input.value.trim();if(!source)return;button.disabled=true;text('camera-source-status','Applying source…');
  try{const response=await authFetch('/api/operator/camera-source',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({source})}),payload=await response.json();if(!response.ok)throw new Error(payload.detail||`UPDATE FAILED ${response.status}`);input.value=payload.source;text('camera-source-status','Saved · bridge reconnecting automatically')}catch(error){text('camera-source-status',String(error.message||'UPDATE FAILED').toUpperCase())}finally{button.disabled=false}
}
async function registerOperatorAsset(event){
  event.preventDefault();const form=event.currentTarget,button=form.querySelector('button[type="submit"]'),device_id=byId('asset-id-input').value.trim(),device_type=byId('asset-type-input').value,endpoint=byId('asset-endpoint-input').value.trim();if(!device_id||!endpoint)return;button.disabled=true;text('asset-registration-status','Registering…');
  try{const response=await authFetch('/api/operator/assets',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({device_id,device_type,endpoint})}),payload=await response.json();if(!response.ok)throw new Error(payload.detail||`REGISTER FAILED ${response.status}`);byId('asset-endpoint-input').value='';text('asset-registration-status','Registered · adapter/V2X provisioning still required');await loadOperatorConfiguration()}catch(error){text('asset-registration-status',String(error.message||'REGISTER FAILED').toUpperCase())}finally{button.disabled=false}
}
function refreshPreview(delay=0){
  if(previewTimer)clearTimeout(previewTimer);
  previewTimer=window.setTimeout(async()=>{
    previewTimer=null;
    // Local operator mode deliberately has no browser token.  The previous
    // guard therefore prevented the camera preview from ever being fetched,
    // even while OpenCV, YOLO and the bridge were publishing valid frames.
    if(!LOCAL_OPERATOR_MODE&&!accessToken)return;
    if(previewInFlight){refreshPreview(PREVIEW_REFRESH_INTERVAL_MS);return}
    previewInFlight=true;
    try{
      const response=await authFetch(`/api/vision/preview.jpg?t=${Date.now()}`);if(!response.ok)throw new Error(`preview ${response.status}`);
      const nextUrl=URL.createObjectURL(await response.blob()),image=new Image();
      await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=reject;image.src=nextUrl});
      const oldUrl=currentPreviewUrl;currentPreviewUrl=nextUrl;
      byId('vision-preview').src=nextUrl;byId('sensor-wall-preview').src=nextUrl;
      if(oldUrl)URL.revokeObjectURL(oldUrl);
      byId('video-wait').classList.add('hidden');byId('wall-video-wait').classList.add('hidden');
      text('preview-resolution',`${image.naturalWidth} × ${image.naturalHeight}`);text('wall-resolution',`${image.naturalWidth} × ${image.naturalHeight}`);
      previewFailures=0;previewRenderedAt=Date.now();updateCameraFrameAge();setCameraStreamState('good');
      if(!latestVision||latestVision.status!=='processing'){text('preview-status','RECEIVING');text('wall-camera-state','LIVE / RECEIVING');text('camera-feed-summary','1 live · 3 offline');setFooterLight('status-video','good')}
      refreshPreview(PREVIEW_REFRESH_INTERVAL_MS);
    }catch(_){previewFailed()}finally{previewInFlight=false}
  },delay);
}
function previewFailed(){
  previewFailures+=1;
  if(previewFailures>2){byId('video-wait').classList.remove('hidden');byId('wall-video-wait').classList.remove('hidden');text('preview-status','WAITING');text('wall-camera-state','WAITING');text('camera-feed-summary','Primary camera unavailable · 3 offline');setCameraStreamState('bad');setFooterLight('status-video','bad')}
  refreshPreview(Math.min(2500,500+previewFailures*250));
}
function applyCameraViewMode(){
  const fill=cameraViewMode==='fill';document.querySelectorAll('.primary-video,.wall-video').forEach(node=>node.classList.toggle('camera-fill',fill));
  const button=byId('camera-fit-toggle');if(button){button.textContent=fill?'FILL':'FIT';button.setAttribute('aria-pressed',String(fill));button.title=fill?'Show the entire frame':'Fill the available camera area'}
}
function toggleCameraFit(){cameraViewMode=cameraViewMode==='fit'?'fill':'fit';try{localStorage.setItem('sentinel.camera.view',cameraViewMode)}catch(_){}applyCameraViewMode()}
function requestCameraRefresh(){previewFailures=0;text('preview-status','REFRESHING');text('wall-camera-state','REFRESHING');refreshPreview(0)}
async function saveCameraSnapshot(){
  const source=currentPreviewUrl||byId('sensor-wall-preview')?.currentSrc;if(!source){text('wall-camera-state','NO FRAME TO SAVE');return}
  try{const response=await fetch(source);if(!response.ok)throw new Error();const blob=await response.blob(),url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=`sentinel-annotated-${new Date().toISOString().replaceAll(':','-').replaceAll('.','-')}.jpg`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);text('wall-camera-state','SNAPSHOT SAVED')}catch(_){text('wall-camera-state','SNAPSHOT UNAVAILABLE')}
}
async function toggleCameraFullscreen(){
  const stage=byId('camera-stage');if(!stage)return;
  try{if(document.fullscreenElement)await document.exitFullscreen();else await stage.requestFullscreen()}catch(_){text('wall-camera-state','FULL SCREEN UNAVAILABLE')}
}

function mapContext(){
  const canvas=byId('tactical-canvas'),rect=canvas.getBoundingClientRect(),ratio=Math.min(window.devicePixelRatio||1,2),width=rect.width,height=rect.height;
  const pixelWidth=Math.max(1,Math.round(width*ratio)),pixelHeight=Math.max(1,Math.round(height*ratio));
  if(canvas.width!==pixelWidth||canvas.height!==pixelHeight){canvas.width=pixelWidth;canvas.height=pixelHeight}
  const ctx=canvas.getContext('2d');ctx.setTransform(ratio,0,0,ratio,0,0);
  const fencePoints=geofences.flatMap(zone=>zone.coordinates||[]),automaticLat=latestTelemetry?.latitude??(fencePoints.length?fencePoints.reduce((sum,p)=>sum+p[0],0)/fencePoints.length:17.6864),automaticLon=latestTelemetry?.longitude??(fencePoints.length?fencePoints.reduce((sum,p)=>sum+p[1],0)/fencePoints.length:83.2185),centerLat=mapCenterOverride?.latitude??automaticLat,centerLon=mapCenterOverride?.longitude??automaticLon,zoomLevel=clamp(16+Math.log2(mapZoom),3,19),tileZoom=Math.floor(zoomLevel),visualScale=2**(zoomLevel-tileZoom),centerWorld=geoToWorld(centerLat,centerLon,tileZoom),resolution=156543.03392*Math.cos(centerLat*Math.PI/180)/2**zoomLevel,scale=1/resolution,visibleRadius=Math.min(width,height)*resolution/2;
  const plot=point=>{const world=geoToWorld(point[0],point[1],tileZoom);return[width/2+(world.x-centerWorld.x)*visualScale,height/2+(world.y-centerWorld.y)*visualScale]},unplot=(x,y)=>worldToGeo(centerWorld.x+(x-width/2)/visualScale,centerWorld.y+(y-height/2)/visualScale,tileZoom);
  return{canvas,ctx,width,height,centerLat,centerLon,visibleRadius,scale,plot,unplot,tileZoom,zoomLevel,visualScale,centerWorld};
}
function drawGridFallback(map,style){
  const{ctx,width,height,scale}=map,major=Math.max(48,100*scale),minor=major/5;
  ctx.fillStyle=style.label==='TACTICAL'?'#071017':'#091016';ctx.fillRect(0,0,width,height);ctx.lineWidth=1;ctx.strokeStyle=style.label==='TACTICAL'?'#163044':'#111d26';
  for(let x=(width/2)%minor;x<width;x+=minor){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke()}
  for(let y=(height/2)%minor;y<height;y+=minor){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(0+width,y);ctx.stroke()}
  ctx.strokeStyle=style.label==='TACTICAL'?'#20526a':'#1b2b36';
  for(let x=(width/2)%major;x<width;x+=major){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke()}
  for(let y=(height/2)%major;y<height;y+=major){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke()}
}
function setMapAttribution(style,mode){
  const link=byId('map-attribution-link');text('map-attribution-state',mode);
  if(link){link.textContent=style.attribution;link.href=style.attributionUrl||'#';link.classList.toggle('hidden',!style.attributionUrl)}
}
function drawVectorBasemap(map){
  const{ctx,width,height,visibleRadius,centerLat,centerLon,tileZoom,visualScale,centerWorld}=map,style=currentMapStyle();
  drawGridFallback(map,style);
  const worldHalfWidth=width/(2*visualScale),worldHalfHeight=height/(2*visualScale),firstX=Math.floor((centerWorld.x-worldHalfWidth)/MAP_TILE_SIZE)-1,lastX=Math.floor((centerWorld.x+worldHalfWidth)/MAP_TILE_SIZE)+1,firstY=Math.floor((centerWorld.y-worldHalfHeight)/MAP_TILE_SIZE)-1,lastY=Math.floor((centerWorld.y+worldHalfHeight)/MAP_TILE_SIZE)+1,drawTileSize=MAP_TILE_SIZE*visualScale;let ready=0,loading=0;
  if(style.template)for(let tileY=firstY;tileY<=lastY;tileY++)for(let tileX=firstX;tileX<=lastX;tileX++){
    const tile=requestMapTile(`${activeMapView}-base`,style.template,tileZoom,tileX,tileY);if(!tile)continue;const drawX=(tileX*MAP_TILE_SIZE-centerWorld.x)*visualScale+width/2,drawY=(tileY*MAP_TILE_SIZE-centerWorld.y)*visualScale+height/2;
    if(tile.status==='ready'){ctx.save();ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.globalAlpha=.97;ctx.drawImage(tile.image,drawX,drawY,drawTileSize+1,drawTileSize+1);ctx.restore();ready+=1}else if(tile.status==='loading')loading+=1;
  }
  if(style.overlayTemplate)for(let tileY=firstY;tileY<=lastY;tileY++)for(let tileX=firstX;tileX<=lastX;tileX++){
    const overlay=requestMapTile(`${activeMapView}-overlay`,style.overlayTemplate,tileZoom,tileX,tileY);if(overlay?.status!=='ready')continue;const drawX=(tileX*MAP_TILE_SIZE-centerWorld.x)*visualScale+width/2,drawY=(tileY*MAP_TILE_SIZE-centerWorld.y)*visualScale+height/2;ctx.save();ctx.globalAlpha=.9;ctx.drawImage(overlay.image,drawX,drawY,drawTileSize+1,drawTileSize+1);ctx.restore();
  }
  const mode=style.template?(ready?`${style.label} · LIVE RASTER`:loading?`${style.label} · LOADING`:`${style.label} · OFFLINE GRID`):'TACTICAL · LOCAL GRID';text('map-source-label',mode);setMapAttribution(style,style.template&&ready?'LIVE MAP':'LOCAL MAP');
  if(ready)ctx.fillStyle=style.label==='SATELLITE'?'rgba(4,11,14,.12)':'rgba(7,15,20,.09)';if(ready)ctx.fillRect(0,0,width,height);
  ctx.strokeStyle='#7a97a5';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(width/2-10,height/2);ctx.lineTo(width/2+10,height/2);ctx.moveTo(width/2,height/2-10);ctx.lineTo(width/2,height/2+10);ctx.stroke();
  ctx.fillStyle='#e1e8ec';ctx.font='600 9px "Cascadia Mono",Consolas,monospace';ctx.fillText(style.label,14,21);
  ctx.fillStyle='#aab7bf';ctx.font='8px "Cascadia Mono",Consolas,monospace';ctx.fillText(`${ready?'LIVE BASEMAP':'LOCAL FALLBACK'} · ${Math.round(visibleRadius)} m RADIUS`,14,36);ctx.fillText(`${centerLat.toFixed(5)}, ${centerLon.toFixed(5)}`,14,50);
}
function updateMapDetails(map){
  const telemetry=latestTelemetry,view=currentMapStyle(),heading=Number(telemetry?.heading_deg);
  text('map-detail-view',view.label);text('map-detail-position',`${map.centerLat.toFixed(5)}, ${map.centerLon.toFixed(5)}`);
  text('map-detail-altitude',telemetry?.altitude_m==null?'NO TELEMETRY':`${num(telemetry.altitude_m,1)} m AGL`);
  text('map-detail-heading',telemetry&&Number.isFinite(heading)?`${heading.toFixed(0).padStart(3,'0')}° ${cardinalFromHeading(heading)}`:'N/A');
  text('map-detail-contacts',`${tracks.size} TRACK${tracks.size===1?'':'S'}`);text('map-detail-geofences',`${geofences.length} ZONE${geofences.length===1?'':'S'}`);text('map-detail-route',`${missionWaypoints.length} WAYPOINT${missionWaypoints.length===1?'':'S'}`);
}
function focusMapOnPoints(points){
  const valid=points.filter(point=>Number.isFinite(Number(point?.latitude))&&Number.isFinite(Number(point?.longitude)));if(!valid.length)return false;
  const latitude=valid.reduce((sum,point)=>sum+Number(point.latitude),0)/valid.length,longitude=valid.reduce((sum,point)=>sum+Number(point.longitude),0)/valid.length;
  let radius=80;valid.forEach(point=>{radius=Math.max(radius,haversine({latitude,longitude},point))});mapCenterOverride={latitude,longitude};
  const previousZoom=mapZoom;mapZoom=1;const baselineRadius=mapContext().visibleRadius;mapZoom=clamp(baselineRadius/Math.max(120,radius*1.5),.25,8);if(!Number.isFinite(mapZoom))mapZoom=previousZoom;drawTacticalPlot();return true;
}
function focusAircraft(){
  if(!latestTelemetry||!focusMapOnPoints([latestTelemetry])){text('plot-state','AIRCRAFT GPS REQUIRED');return}
  text('plot-state','FOCUSED ON AIRCRAFT');
}
function fitOperationalMap(){
  const points=[];if(latestTelemetry)points.push(latestTelemetry);missionWaypoints.forEach(point=>points.push(point));tracks.forEach(track=>{if(track.location)points.push(track.location)});geofences.forEach(zone=>(zone.coordinates||[]).forEach(([latitude,longitude])=>points.push({latitude,longitude})));
  if(!focusMapOnPoints(points)){mapCenterOverride=null;mapZoom=1;drawTacticalPlot();text('plot-state','LOCAL / AWAITING GPS');return}
  text('plot-state',`FIT ${points.length} OPERATIONAL POINT${points.length===1?'':'S'}`);
}
function drawTacticalPlot(){
  if(mapDrawPending)return;mapDrawPending=true;requestAnimationFrame(()=>{mapDrawPending=false;drawTacticalPlotNow()});
}
function drawTacticalPlotNow(){
  const canvas=byId('tactical-canvas');if(!canvas||canvas.closest('.hidden'))return;const rect=canvas.getBoundingClientRect();if(!rect.width||!rect.height)return;
  const map=mapContext(),{ctx,width,height,plot,scale}=map;currentMapView=map;drawVectorBasemap(map);
  geofences.forEach(zone=>{const coords=zone.coordinates||[];if(coords.length<3)return;ctx.save();ctx.beginPath();coords.forEach((point,index)=>{const[x,y]=plot(point);index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.closePath();ctx.fillStyle=zone.restricted?'#e5484d12':'#3fb27f10';ctx.fill();ctx.clip();ctx.strokeStyle=zone.restricted?'#8e353d66':'#2d725766';ctx.lineWidth=1;for(let x=-height;x<width+height;x+=12){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x-height,height);ctx.stroke()}ctx.restore();ctx.beginPath();coords.forEach((point,index)=>{const[x,y]=plot(point);index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.closePath();ctx.strokeStyle=zone.restricted?'#e5484d':'#3fb27f';ctx.lineWidth=activeMapLayer==='geofence'?2.5:1.25;ctx.setLineDash(zone.restricted?[7,5]:[]);ctx.stroke();ctx.setLineDash([]);const[labelX,labelY]=plot(coords[0]);ctx.fillStyle=zone.restricted?'#f07b80':'#70cfa6';ctx.font='600 8px "Cascadia Mono",Consolas,monospace';ctx.fillText(String(zone.name||zone.id).toUpperCase(),labelX+5,labelY-6)});
  if(missionWaypoints.length){ctx.strokeStyle='#8ea3b2';ctx.lineWidth=1.5;ctx.setLineDash([7,5]);ctx.beginPath();missionWaypoints.forEach((point,index)=>{const[x,y]=plot([point.latitude,point.longitude]);index?ctx.lineTo(x,y):ctx.moveTo(x,y)});ctx.stroke();ctx.setLineDash([]);missionWaypoints.forEach((point,index)=>{const[x,y]=plot([point.latitude,point.longitude]);ctx.fillStyle=index===0?'#3fb27f':'#0e151c';ctx.strokeStyle='#dbe4ea';ctx.lineWidth=1.5;ctx.beginPath();ctx.rect(x-7,y-7,14,14);ctx.fill();ctx.stroke();ctx.fillStyle='#e6eaf0';ctx.font='bold 7px "Cascadia Mono",Consolas,monospace';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(String(index+1),x,y);ctx.textAlign='left';ctx.textBaseline='alphabetic'})}
  tracks.forEach(track=>{if(!track.location)return;const history=trackTrails.get(track.track_id)||[];if(history.length>1){ctx.lineWidth=1.25;ctx.beginPath();history.forEach((point,index)=>{const[tx,ty]=plot([point.latitude,point.longitude]);ctx.strokeStyle=`rgba(232,169,62,${.15+index/history.length*.55})`;if(index===0)ctx.moveTo(tx,ty);else{ctx.lineTo(tx,ty);ctx.stroke();ctx.beginPath();ctx.moveTo(tx,ty)}});const previous=history.at(-2),current=history.at(-1),[px,py]=plot([previous.latitude,previous.longitude]),[cx,cy]=plot([current.latitude,current.longitude]),dx=cx-px,dy=cy-py,length=Math.hypot(dx,dy);if(length>.5){ctx.strokeStyle='#e8a93e';ctx.beginPath();ctx.moveTo(cx,cy);ctx.lineTo(cx+dx/length*22,cy+dy/length*22);ctx.stroke()}}
    const[x,y]=plot([track.location.latitude,track.location.longitude]),selected=track.track_id===selectedTrackId,pulse=(Math.sin(performance.now()/260)+1)/2;ctx.save();ctx.translate(x,y);ctx.rotate(Math.PI/4);ctx.fillStyle=selected?'#4cc3e8':'#e8a93e';ctx.strokeStyle='#081016';ctx.lineWidth=2;ctx.fillRect(-5,-5,10,10);ctx.strokeRect(-5,-5,10,10);ctx.restore();if(selected){ctx.strokeStyle=`rgba(76,195,232,${.9-pulse*.45})`;ctx.lineWidth=1.5;ctx.beginPath();ctx.arc(x,y,12+pulse*7,0,Math.PI*2);ctx.stroke()}const tag=`${String(track.track_id||'').slice(-8)}  ${Math.round((track.display_confidence??track.confidence??0)*100)}%`;ctx.font='600 8px "Cascadia Mono",Consolas,monospace';const tagWidth=ctx.measureText(tag).width+8;ctx.fillStyle='#0b1117e8';ctx.fillRect(x+9,y-15,tagWidth,13);ctx.strokeStyle=selected?'#4cc3e8':'#5d4d2a';ctx.strokeRect(x+9,y-15,tagWidth,13);ctx.fillStyle=selected?'#aeeeff':'#f0c671';ctx.fillText(tag,x+13,y-6)});
  if(latestTelemetry){const[x,y]=plot([latestTelemetry.latitude,latestTelemetry.longitude]),pulse=(Math.sin(performance.now()/320)+1)/2;ctx.strokeStyle=`rgba(57,168,232,${.55-pulse*.25})`;ctx.lineWidth=1;ctx.beginPath();ctx.arc(x,y,17+pulse*6,0,Math.PI*2);ctx.stroke();ctx.save();ctx.translate(x,y);ctx.rotate((latestTelemetry.heading_deg||0)*Math.PI/180);ctx.fillStyle='#39a8e8';ctx.strokeStyle='#dff4ff';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(0,-13);ctx.lineTo(8,10);ctx.lineTo(0,6);ctx.lineTo(-8,10);ctx.closePath();ctx.fill();ctx.stroke();ctx.restore()}
  const rawScaleDistance=90/scale,scalePower=10**Math.floor(Math.log10(Math.max(rawScaleDistance,.01))),scaleUnit=rawScaleDistance/scalePower,niceScale=(scaleUnit>=5?5:scaleUnit>=2?2:1)*scalePower,scaleBar=byId('map-scale-bar');if(scaleBar)scaleBar.style.width=`${Math.max(24,Math.round(niceScale*scale))}px`;
  text('plot-state',latestTelemetry?'GEO-REFERENCED':'LOCAL / AWAITING GPS');text('map-scale-label',niceScale>=1000?`${(niceScale/1000).toFixed(niceScale>=10000?0:1)} km`:`${Math.round(niceScale)} m`);updateMapDetails(map);
}
function updateMissionStats(){
  let distance=0,maxRange=0;for(let i=1;i<missionWaypoints.length;i++)distance+=haversine(missionWaypoints[i-1],missionWaypoints[i]);
  const home=latestTelemetry?{latitude:latestTelemetry.latitude,longitude:latestTelemetry.longitude}:missionWaypoints[0];if(home)missionWaypoints.forEach(point=>{maxRange=Math.max(maxRange,haversine(home,point))});
  const waypointSpeeds=missionWaypoints.map(point=>Number(point.speed_mps)).filter(value=>Number.isFinite(value)&&value>0),telemetrySpeed=Number(latestTelemetry?.ground_speed_mps),speed=waypointSpeeds.length?waypointSpeeds.reduce((sum,value)=>sum+value,0)/waypointSpeeds.length:(Number.isFinite(telemetrySpeed)&&telemetrySpeed>0?telemetrySpeed:null),seconds=speed?distance/speed:null,minutes=seconds==null?null:Math.floor(seconds/60),remaining=seconds==null?null:Math.round(seconds%60);
  const distanceLabel=distance<1000?`${Math.round(distance)} m`:`${(distance/1000).toFixed(2)} km`;text('mission-waypoint-count',missionWaypoints.length);text('mission-distance',distanceLabel);text('mission-range',maxRange<1000?`${Math.round(maxRange)} m`:`${(maxRange/1000).toFixed(2)} km`);text('mission-time',distance&&seconds!=null?`${minutes}:${String(remaining).padStart(2,'0')}`:'N/A');text('inspector-waypoint-count',missionWaypoints.length);text('inspector-distance',distanceLabel);text('mission-inspector-state',missionDirty?'UNSAVED':missionRecord?.state||(missionWaypoints.length?'LOCAL DRAFT':'EMPTY'));
  ['mission-undo','mission-clear','mission-export'].forEach(id=>{byId(id).disabled=!missionWaypoints.length});text('mission-state',missionDirty?'UNSAVED CHANGES':missionRecord?.state||(missionWaypoints.length?'LOCAL DRAFT':'EMPTY DRAFT'));
}
function addWaypoint(event){
  const canvas=byId('tactical-canvas'),rect=canvas.getBoundingClientRect(),map=mapContext(),pointerX=event.clientX-rect.left,pointerY=event.clientY-rect.top;
  if(activeMapTool==='select'){
    let nearest=null,distance=16;tracks.forEach(track=>{if(!track.location)return;const[x,y]=map.plot([track.location.latitude,track.location.longitude]),candidate=Math.hypot(pointerX-x,pointerY-y);if(candidate<distance){distance=candidate;nearest=track.track_id}});if(nearest)selectTrack(nearest);return;
  }
  if(activeWorkspace!=='plan'||activeMapTool!=='waypoint')return;const point=map.unplot(pointerX,pointerY),altitude=Math.max(1,Number(byId('mission-default-altitude').value)||50),speed=Math.max(.1,Number(byId('mission-cruise-speed').value)||8),hold=Math.max(0,Number(byId('mission-hold-time').value)||0);missionWaypoints.push({...point,altitude_m:altitude,speed_mps:speed,hold_time_s:hold,command:'WAYPOINT'});missionDirty=true;saveMissionDraft();updateMissionStats();drawTacticalPlot();
}
function cursorCoordinate(event){
  const canvas=byId('tactical-canvas'),rect=canvas.getBoundingClientRect(),map=currentMapView||mapContext(),x=event.clientX-rect.left,y=event.clientY-rect.top;
  return map.unplot(x,y);
}
function updateCursor(event){if(mapDrag)return;const point=cursorCoordinate(event);lastMapCursor=point;text('cursor-coordinate',`${point.latitude.toFixed(5)}, ${point.longitude.toFixed(5)}`)}
function beginMapDrag(event){if(event.button!==0)return;const map=currentMapView||mapContext();mapDrag={pointerId:event.pointerId,x:event.clientX,y:event.clientY,centerWorld:map.centerWorld,tileZoom:map.tileZoom,visualScale:map.visualScale};mapDragMoved=false;event.currentTarget.setPointerCapture?.(event.pointerId);event.currentTarget.classList.add('dragging')}
function moveMapDrag(event){if(!mapDrag||event.pointerId!==mapDrag.pointerId)return;const dx=event.clientX-mapDrag.x,dy=event.clientY-mapDrag.y;if(Math.hypot(dx,dy)>4)mapDragMoved=true;if(!mapDragMoved)return;mapCenterOverride=worldToGeo(mapDrag.centerWorld.x-dx/mapDrag.visualScale,mapDrag.centerWorld.y-dy/mapDrag.visualScale,mapDrag.tileZoom);drawTacticalPlot()}
function endMapDrag(event){if(!mapDrag||event.pointerId!==mapDrag.pointerId)return;event.currentTarget.releasePointerCapture?.(event.pointerId);event.currentTarget.classList.remove('dragging');mapDrag=null}
function zoomMapAt(event){event.preventDefault();const before=currentMapView||mapContext(),rect=before.canvas.getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top,anchor=before.unplot(x,y),factor=Math.exp(-event.deltaY*.0015),nextZoom=clamp(mapZoom*factor,.25,8);if(Math.abs(nextZoom-mapZoom)<.0001)return;mapZoom=nextZoom;const next=mapContext(),anchorWorld=geoToWorld(anchor.latitude,anchor.longitude,next.tileZoom),centerWorld={x:anchorWorld.x-(x-next.width/2)/next.visualScale,y:anchorWorld.y-(y-next.height/2)/next.visualScale};mapCenterOverride=worldToGeo(centerWorld.x,centerWorld.y,next.tileZoom);drawTacticalPlot()}
function openStreetView(){const map=currentMapView||mapContext(),point=lastMapCursor||{latitude:map.centerLat,longitude:map.centerLon};if(!Number.isFinite(point.latitude)||!Number.isFinite(point.longitude))return;const url=streetViewUrlTemplate.replace('{lat}',encodeURIComponent(point.latitude.toFixed(7))).replace('{lon}',encodeURIComponent(point.longitude.toFixed(7)));window.open(url,'_blank','noopener,noreferrer')}
function animateOperationalMap(timestamp){if(timestamp-lastMapMotionAt>125){lastMapMotionAt=timestamp;if((latestTelemetry||selectedTrackId)&&!byId('map-workspace').classList.contains('hidden'))drawTacticalPlot()}mapMotionFrame=requestAnimationFrame(animateOperationalMap)}
function exportMission(){
  if(!missionWaypoints.length)return;const payload={schema:'sentinel-mission/1',created_at:new Date().toISOString(),state:'local-draft-not-uploaded',waypoints:missionWaypoints};const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=`sentinel-mission-${Date.now()}.json`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function missionDraftPayload(){
  const missionId=missionRecord?.id||crypto.randomUUID(),vehicleId=byId('mission-vehicle').value.trim(),name=byId('mission-name').value.trim();
  const cruiseSpeed=Number(byId('mission-cruise-speed').value);return{id:missionId,name,vehicle_id:vehicleId,home:latestTelemetry?{latitude:latestTelemetry.latitude,longitude:latestTelemetry.longitude,approximate:false,method:'reported'}:null,cruise_speed_mps:Number.isFinite(cruiseSpeed)&&cruiseSpeed>0?cruiseSpeed:null,waypoints:missionWaypoints.map((point,index)=>({id:point.id||crypto.randomUUID(),sequence:index,command:point.command||'WAYPOINT',latitude:point.latitude,longitude:point.longitude,altitude_m:Number(point.altitude_m)||0,speed_mps:Number(point.speed_mps)>0?Number(point.speed_mps):null,hold_time_s:Number(point.hold_time_s)>=0?Number(point.hold_time_s):null}))};
}
async function saveMissionToServer(){
  const button=byId('mission-save'),draft=missionDraftPayload();if(!draft.name||!draft.vehicle_id){text('mission-state','NAME / VEHICLE REQUIRED');return}button.disabled=true;button.textContent='VALIDATING';
  try{const response=await authFetch('/api/missions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mission:draft,expected_version:missionRecord?.version||null,justification:'Operator saved and validated mission plan'})});if(response.status===409)throw new Error('VERSION CONFLICT — RELOAD');if(!response.ok)throw new Error(`SAVE FAILED ${response.status}`);const payload=await response.json();missionRecord=payload.mission;missionWaypoints=missionRecord.waypoints;missionDirty=false;saveMissionRecord();saveMissionDraft();text('mission-state',missionRecord.state);const errors=(payload.validation?.issues||[]).filter(issue=>issue.severity==='error').length;text('mission-warning-text',errors?`${errors} VALIDATION ERROR${errors===1?'':'S'}`:'VALIDATED · NOT UPLOADED');byId('mission-upload').disabled=missionRecord.state!=='VALID';byId('mission-upload').textContent=missionRecord.state==='VALID'?'Prepare upload':'Vehicle offline';drawTacticalPlot()}
  catch(error){text('mission-state',error.message||'SAVE FAILED')}finally{button.disabled=false;button.textContent='Save + validate'}
}
async function prepareMissionUpload(){
  if(!missionRecord||missionRecord.state!=='VALID')return;const button=byId('mission-upload');button.disabled=true;button.textContent='CHECKING';try{const response=await authFetch(`/api/missions/${encodeURIComponent(missionRecord.id)}/prepare-upload`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({expected_version:missionRecord.version,justification:'Operator requested mission readiness verification'})});const payload=await response.json();if(!response.ok)throw new Error(payload.detail||'PREPARE FAILED');missionRecord=payload.mission;saveMissionRecord();text('mission-state',missionRecord.state);button.textContent='Hardware adapter required'}catch(error){button.textContent=String(error.message||'PREPARE FAILED').toUpperCase()}finally{button.disabled=true}}

function bindControls(){
  byId('mission-inspector-form').addEventListener('submit',event=>event.preventDefault());
  document.querySelectorAll('button[data-workspace]').forEach(button=>button.addEventListener('click',()=>setWorkspace(button.dataset.workspace)));
  document.querySelectorAll('[data-map-tool]').forEach(button=>button.addEventListener('click',()=>{if(activeWorkspace!=='plan'&&button.dataset.mapTool==='waypoint')setWorkspace('plan');setMapTool(button.dataset.mapTool)}));
  document.querySelectorAll('[data-map-layer]').forEach(button=>button.addEventListener('click',()=>setMapLayer(button.dataset.mapLayer)));
  document.querySelectorAll('[data-map-view]').forEach(button=>button.addEventListener('click',()=>setMapView(button.dataset.mapView)));
  document.querySelectorAll('[data-dock-tab]').forEach(button=>button.addEventListener('click',()=>{document.querySelectorAll('[data-dock-tab]').forEach(item=>item.classList.toggle('active',item===button));byId('object-list').classList.toggle('hidden',button.dataset.dockTab!=='tracks');byId('event-list').classList.toggle('hidden',button.dataset.dockTab!=='events')}));
  byId('track-filter').addEventListener('input',renderTrackWorkspace);byId('track-class-filter').addEventListener('change',renderTrackWorkspace);byId('alert-filter').addEventListener('input',renderAlertWorkspace);byId('alert-severity-filter').addEventListener('change',renderAlertWorkspace);
  byId('mission-new').addEventListener('click',()=>{missionRecord=null;missionDirty=false;saveMissionRecord();missionWaypoints=[];saveMissionDraft();updateMissionStats();setMapTool('waypoint');drawTacticalPlot()});
  byId('mission-undo').addEventListener('click',()=>{missionWaypoints.pop();missionDirty=true;saveMissionDraft();updateMissionStats();drawTacticalPlot()});
  byId('mission-clear').addEventListener('click',()=>{missionWaypoints=[];missionDirty=true;saveMissionDraft();updateMissionStats();drawTacticalPlot()});
  byId('mission-save').addEventListener('click',saveMissionToServer);byId('mission-upload').addEventListener('click',prepareMissionUpload);byId('mission-export').addEventListener('click',exportMission);byId('map-zoom-in').addEventListener('click',()=>{mapZoom=clamp(mapZoom*1.4,.5,8);drawTacticalPlot()});byId('map-zoom-out').addEventListener('click',()=>{mapZoom=clamp(mapZoom/1.4,.5,8);drawTacticalPlot()});byId('map-focus-aircraft').addEventListener('click',focusAircraft);byId('map-fit-operation').addEventListener('click',fitOperationalMap);
  byId('street-view-button').addEventListener('click',openStreetView);byId('camera-source-form').addEventListener('submit',saveCameraSource);byId('asset-registration-form').addEventListener('submit',registerOperatorAsset);
  byId('camera-fit-toggle').addEventListener('click',toggleCameraFit);byId('camera-refresh').addEventListener('click',requestCameraRefresh);byId('camera-snapshot').addEventListener('click',saveCameraSnapshot);byId('camera-fullscreen').addEventListener('click',toggleCameraFullscreen);
  document.addEventListener('fullscreenchange',()=>{const button=byId('camera-fullscreen');if(button)button.textContent=document.fullscreenElement?'EXIT FULL SCREEN':'FULL SCREEN'});
  ['mission-name','mission-vehicle'].forEach(id=>byId(id).addEventListener('input',()=>{missionDirty=true;updateMissionStats()}));
  ['mission-default-altitude','mission-cruise-speed','mission-hold-time'].forEach(id=>byId(id).addEventListener('input',()=>{missionDirty=true;updateMissionStats()}));
  byId('mission-apply-defaults').addEventListener('click',()=>{const altitude=Math.max(1,Number(byId('mission-default-altitude').value)||50),speed=Math.max(.1,Number(byId('mission-cruise-speed').value)||8),hold=Math.max(0,Number(byId('mission-hold-time').value)||0);missionWaypoints=missionWaypoints.map(point=>({...point,altitude_m:altitude,speed_mps:speed,hold_time_s:hold}));missionDirty=true;saveMissionDraft();updateMissionStats()});
  byId('center-map').addEventListener('click',()=>{mapZoom=1;mapCenterOverride=null;setWorkspace('flight');drawTacticalPlot()});
  const tacticalCanvas=byId('tactical-canvas');tacticalCanvas.addEventListener('pointerdown',beginMapDrag);tacticalCanvas.addEventListener('pointermove',moveMapDrag);tacticalCanvas.addEventListener('pointerup',endMapDrag);tacticalCanvas.addEventListener('pointercancel',endMapDrag);tacticalCanvas.addEventListener('click',event=>{if(mapDragMoved){mapDragMoved=false;return}addWaypoint(event)});tacticalCanvas.addEventListener('mousemove',updateCursor);tacticalCanvas.addEventListener('wheel',zoomMapAt,{passive:false});
  byId('ack-form').addEventListener('submit',submitAcknowledgement);byId('ack-close').addEventListener('click',()=>byId('ack-dialog').close());byId('ack-cancel').addEventListener('click',()=>byId('ack-dialog').close());
  byId('replay-load').addEventListener('click',loadReplay);byId('replay-exit').addEventListener('click',()=>setReplayMode(false));
  document.addEventListener('keydown',event=>{
    if(['INPUT','TEXTAREA'].includes(document.activeElement?.tagName))return;
    const key=event.key.toLowerCase();
    if(key==='j'){const open=[...events.values()].filter(item=>!item.acknowledged).sort((a,b)=>b.timestamp-a.timestamp);if(open.length){const index=Math.max(-1,open.findIndex(item=>item.id===selectedEventId));selectedEventId=open[(index+1)%open.length].id;renderEvents();document.querySelector('.event-row.selected')?.focus()}}
    else if(key==='a'){const candidate=events.get(selectedEventId)||[...events.values()].find(item=>!item.acknowledged);if(candidate&&!candidate.acknowledged)openAcknowledgeDialog(candidate.id)}
    else if(key==='c'){mapZoom=1;setWorkspace('flight');drawTacticalPlot()}
    else if(['1','2','3','4','5','6','7','8','9','0'].includes(key))setWorkspace({1:'flight',2:'plan',3:'camera',4:'tracks',5:'alerts',6:'sensors',7:'systems',8:'analyze',9:'evidence',0:'settings'}[key]);
  });
}

function startRuntime(){
  if(runtimeStarted){connectOperations();refreshSystemState();refreshPreview();return}runtimeStarted=true;
  try{cameraViewMode=localStorage.getItem('sentinel.camera.view')==='fill'?'fill':'fit';activeMapView=MAP_VIEWS[localStorage.getItem('sentinel.map.view')]?localStorage.getItem('sentinel.map.view'):'street'}catch(_){}applyCameraViewMode();setMapView(activeMapView);
  bindControls();initializeReplayWindow();if(missionRecord){byId('mission-name').value=missionRecord.name||'Untitled mission';byId('mission-vehicle').value=missionRecord.vehicle_id||'';if(Number(missionRecord.cruise_speed_mps)>0)byId('mission-cruise-speed').value=missionRecord.cruise_speed_mps;const first=missionRecord.waypoints?.[0];if(first){if(Number(first.altitude_m)>0)byId('mission-default-altitude').value=first.altitude_m;if(Number(first.hold_time_s)>=0)byId('mission-hold-time').value=first.hold_time_s}}updateMissionStats();updateClock();setInterval(updateClock,1000);setWorkspace('flight');connectOperations();refreshSystemState();loadOperatorConfiguration();setInterval(refreshSystemState,5000);refreshPreview();drawTacticalPlot();if(!window.matchMedia('(prefers-reduced-motion: reduce)').matches&&!mapMotionFrame)mapMotionFrame=requestAnimationFrame(animateOperationalMap);
}
async function bootstrap(){
  if(LOCAL_OPERATOR_MODE){hideLogin();startRuntime();return}
  byId('login-form').addEventListener('submit',signIn);
  if(!accessToken){showLogin();return}
  try{await fetchJson('/api/auth/me');hideLogin();startRuntime()}catch(_){showLogin('Session expired — sign in again')}
}
window.addEventListener('resize',drawTacticalPlot);new ResizeObserver(drawTacticalPlot).observe(byId('tactical-canvas'));bootstrap();
