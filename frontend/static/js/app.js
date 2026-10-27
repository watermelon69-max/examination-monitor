'use strict';
const $ = (id) => document.getElementById(id);
const busyStates = new Set(['starting', 'running', 'stopping']);
let selectedKind = 'demo';
let selectedSource = 'demo';
let previewUrl = '/api/demo/preview';
let latestStatus = {status: 'idle', session_id: null, students: [], stats: {}};
let uploadedVideos = [];
let pending = false;
let uploading = false;
let socket = null;
let reconnectTimer = null;
let pollTimer = null;
let toastTimer = null;
let historyEvents = [];
let historyTotal = 0;
let historyRequest = 0;
let streaming = false;
let lastError = null;
let editorImage = null;
let editorBoxes = [];
let dragStart = null;
let dragEnd = null;
let audioContext = null;

function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
}

function clock(seconds) {
    seconds = Math.max(0, Math.floor(Number(seconds) || 0));
    return String(Math.floor(seconds / 60)).padStart(2, '0') + ':' + String(seconds % 60).padStart(2, '0');
}

function title(type) { return String(type || '').replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase()); }

function toast(message, error = false) {
    const target = $('toast');
    target.textContent = message;
    target.className = 'toast' + (error ? ' error' : '');
    target.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { target.hidden = true; }, error ? 8000 : 4500);
}

async function api(path, options = {}) {
    const response = await fetch(path, options);
    if (!response.ok) {
        let message = response.statusText;
        try {
            const body = await response.json();
            message = typeof body.detail === 'string' ? body.detail : 'The request could not be validated.';
        } catch (_) { /* Retain HTTP status for non-JSON errors. */ }
        throw new Error(message);
    }
    return response.json();
}

function updateControls() {
    const busy = busyStates.has(latestStatus.status);
    $('startBtn').disabled = busy || pending || uploading || !selectedSource;
    $('stopBtn').disabled = !busy || pending || latestStatus.status === 'stopping';
    $('startBtn').textContent = latestStatus.status === 'starting' ? 'Loading vision models?' : '? Start monitoring';
    $('configSeatsBtn').disabled = busy || pending || uploading || !selectedSource || selectedKind === 'demo';
    document.querySelectorAll('[data-source]').forEach((button) => { button.disabled = busy || pending || uploading; });
    ['videoFile', 'savedVideos', 'cameraIndex', 'previewCameraBtn'].forEach((id) => { $(id).disabled = busy || pending || uploading; });
}

function showPreview(url, message = '') {
    streaming = false;
    const image = $('liveView');
    image.hidden = !url;
    $('videoMessage').textContent = message;
    $('videoMessage').hidden = !message;
    if (url) image.src = url;
    else image.removeAttribute('src');
}

async function refreshSeatCount() {
    if (!selectedSource) {
        $('seatCount').textContent = 'No source selected';
        return;
    }
    try {
        const layout = await api('/api/seats?source=' + encodeURIComponent(selectedSource));
        const count = Object.keys(layout.seats).length;
        $('seatCount').textContent = count + (selectedKind === 'demo' ? ' preset seats' : ' saved seats');
    } catch (error) { $('seatCount').textContent = 'Seat layout unavailable'; }
}

async function selectSource(kind, sourceId) {
    selectedKind = kind;
    selectedSource = kind === 'demo' ? 'demo' : kind === 'camera' ? 'camera:' + $('cameraIndex').value : sourceId || $('savedVideos').value;
    document.querySelectorAll('[data-source]').forEach((button) => {
        button.classList.toggle('selected', button.dataset.source === kind);
        button.setAttribute('aria-pressed', String(button.dataset.source === kind));
    });
    $('uploadControls').hidden = kind !== 'upload';
    $('cameraControls').hidden = kind !== 'camera';
    $('videoBadge').textContent = kind === 'demo' ? 'SIMULATION' : kind === 'camera' ? 'CAMERA PREVIEW' : 'VIDEO PREVIEW';
    if (kind === 'demo') {
        previewUrl = '/api/demo/preview';
        $('sourceTitle').textContent = 'Simulation preview';
        $('sourceHelp').textContent = 'Simulation uses synthetic students and observations. No real footage is analyzed.';
        showPreview(previewUrl);
    } else if (kind === 'upload') {
        const item = uploadedVideos.find((video) => video.id === selectedSource);
        previewUrl = item ? item.preview_url : '';
        $('sourceTitle').textContent = item ? item.name : 'Recorded examination';
        $('sourceHelp').textContent = 'Draw the assigned seat areas before monitoring to enable leaving-seat and gathering observations.';
        showPreview(previewUrl, item ? '' : 'Upload a video or select a saved recording to begin.');
    } else {
        previewUrl = '/api/camera/preview?camera=' + $('cameraIndex').value;
        $('sourceTitle').textContent = 'Connected camera ' + $('cameraIndex').value;
        $('sourceHelp').textContent = 'Uses a camera attached to the computer running this app. Preview it, then configure the seats.';
        showPreview('', 'Use Preview camera to check the view before monitoring.');
    }
    $('videoProgress').style.width = '0%';
    await refreshSeatCount();
    updateControls();
}

async function refreshVideos(selectedId) {
    uploadedVideos = await api('/api/videos');
    const select = $('savedVideos');
    select.replaceChildren(node('option', '', 'Choose an uploaded video'));
    select.firstChild.value = '';
    for (const video of uploadedVideos) {
        const option = node('option', '', video.name + ' ? ' + clock(video.duration));
        option.value = video.id;
        select.append(option);
    }
    if (selectedId) select.value = selectedId;
}

function upload(file) {
    if (!file) return;
    uploading = true;
    updateControls();
    $('uploadStatus').textContent = 'Uploading?';
    const request = new XMLHttpRequest();
    request.open('POST', '/api/videos');
    request.responseType = 'json';
    request.upload.onprogress = (event) => {
        $('uploadStatus').textContent = event.lengthComputable ? 'Uploading ' + Math.round(event.loaded / event.total * 100) + '%' : 'Uploading?';
    };
    request.onload = async () => {
        try {
            if (request.status !== 201) throw new Error(request.response?.detail || 'Video upload failed.');
            await refreshVideos(request.response.id);
            await selectSource('upload', request.response.id);
            $('uploadStatus').textContent = 'Ready ? ' + request.response.width + ' ? ' + request.response.height;
            toast('Video uploaded. Configure the assigned seats, then start monitoring.');
        } catch (error) {
            $('uploadStatus').textContent = 'Upload failed';
            toast(error.message, true);
        } finally {
            uploading = false;
            $('videoFile').value = '';
            updateControls();
        }
    };
    request.onerror = () => {
        uploading = false;
        $('uploadStatus').textContent = 'Upload failed';
        toast('Could not reach the server. Check the connection and try again.', true);
        updateControls();
    };
    const body = new FormData();
    body.append('file', file);
    request.send(body);
}

async function command(path, body) {
    pending = true;
    updateControls();
    try {
        const options = {method: 'POST'};
        if (body) { options.headers = {'Content-Type': 'application/json'}; options.body = JSON.stringify(body); }
        applyStatus(await api(path, options));
        await refreshHistory();
    } catch (error) { toast(error.message, true); }
    finally { pending = false; updateControls(); }
}

function badge(state) {
    return node('span', 'state-badge state-' + state, state);
}

function updateStudents(students) {
    const body = $('studentsTable');
    if (!students.length) {
        const row = node('tr');
        const cell = node('td', 'empty-cell', 'Start a session to see student states.');
        cell.colSpan = 5;
        row.append(cell);
        body.replaceChildren(row);
        return;
    }
    const rows = students.map((student) => {
        const row = node('tr');
        row.append(node('td', 'student-id', 'Student ' + student.track_id), node('td', 'muted', student.seat_id == null ? 'Unassigned' : 'Seat ' + student.seat_id));
        const state = node('td');
        state.append(badge(student.state));
        const risk = node('td');
        const wrap = node('div', 'risk-cell');
        const track = node('span', 'risk-track');
        const fill = node('i');
        fill.style.width = Math.max(0, Math.min(100, student.risk_score)) + '%';
        track.append(fill);
        wrap.append(node('span', 'mono', Number(student.risk_score).toFixed(1)), track);
        risk.append(wrap);
        row.append(state, risk, node('td', 'muted mono', student.recent_events));
        return row;
    });
    body.replaceChildren(...rows);
}

function updateActive(students) {
    const alerts = students.filter((student) => ['SUSPICIOUS', 'ALERT'].includes(student.state)).sort((a, b) => b.risk_score - a.risk_score);
    $('activeCount').textContent = alerts.length;
    const target = $('activeAlerts');
    if (!alerts.length) {
        const empty = node('div', 'empty-state');
        empty.append(node('span', 'empty-icon', '?'), node('strong', '', 'All clear'), node('p', '', 'Students with elevated risk will appear here.'));
        target.replaceChildren(empty);
        return;
    }
    target.replaceChildren(...alerts.map((student) => {
        const card = node('div', 'active-card');
        const row = node('div', 'row');
        row.append(node('strong', '', 'Student ' + student.track_id), badge(student.state));
        card.append(row, node('p', '', (student.seat_id == null ? 'Unassigned seat' : 'Seat ' + student.seat_id) + ' ? Risk ' + Number(student.risk_score).toFixed(1) + '/100 ? ' + student.recent_events + ' recent observations'));
        return card;
    }));
}

function applyStatus(status) {
    const changedSession = status.session_id !== latestStatus.session_id;
    latestStatus = status;
    const busy = busyStates.has(status.status);
    $('status').textContent = title(status.status);
    $('status').className = 'status-pill ' + status.status;
    $('errorBanner').hidden = !status.error;
    $('errorBanner').textContent = status.error || '';
    if (status.error && status.error !== lastError) { toast(status.error, true); lastError = status.error; }
    if (!status.error) lastError = null;
    for (const [id, key] of [['statStudents', 'total_students'], ['statEvents', 'total_events'], ['statHigh', 'high_risk'], ['statMedium', 'medium_risk']]) {
        $(id).textContent = status.stats?.[key] || 0;
    }
    $('videoMetrics').textContent = clock(status.elapsed) + ' ? ' + (status.fps ? status.fps.toFixed(1) + ' FPS' : title(status.status));
    $('videoProgress').style.width = (status.progress || 0) + '%';
    $('trackerLabel').textContent = status.tracker || 'Waiting for a session';
    if (busy && !streaming && status.status !== 'starting') {
        $('liveView').hidden = false;
        $('videoMessage').hidden = true;
        $('liveView').src = '/api/video/stream?session=' + encodeURIComponent(status.session_id);
        streaming = true;
    }
    if (status.status === 'starting') {
        $('videoMessage').textContent = 'Preparing monitoring pipeline?';
        $('videoMessage').hidden = false;
    } else if (streaming) {
        $('videoMessage').hidden = true;
    }
    if (status.session_id && (busy || streaming)) {
        $('videoBadge').textContent = status.mode === 'demo' ? 'SIMULATION' : status.mode === 'camera' ? 'CAMERA' : 'RECORDED VIDEO';
    }
    updateStudents(status.students || []);
    updateActive(status.students || []);
    const exportParams = new URLSearchParams();
    if ($('modeFilter').value === 'session' && status.session_id) exportParams.set('session_id', status.session_id);
    if ($('modeFilter').value === 'real') exportParams.set('is_demo', 'false');
    if ($('modeFilter').value === 'demo') exportParams.set('is_demo', 'true');
    $('exportBtn').href = '/api/events/export?' + exportParams;
    updateControls();
    if (changedSession) refreshHistory().catch((error) => toast(error.message, true));
}

async function refreshHistory(append = false) {
    const sequence = ++historyRequest;
    const parameters = new URLSearchParams({limit: '40', offset: String(append ? historyEvents.length : 0)});
    const mode = $('modeFilter').value;
    if (mode === 'session') parameters.set('session_id', latestStatus.session_id || '__no_session__');
    if (mode === 'demo') parameters.set('is_demo', 'true');
    if (mode === 'real') parameters.set('is_demo', 'false');
    if ($('riskFilter').value) parameters.set('risk_level', $('riskFilter').value);
    const result = await api('/api/events?' + parameters);
    if (sequence !== historyRequest) return;
    historyEvents = append ? historyEvents.concat(result.events) : result.events;
    historyTotal = result.total;
    $('historyCount').textContent = historyTotal + ' events';
    $('loadMoreBtn').hidden = historyEvents.length >= historyTotal;
    const target = $('alertHistory');
    if (!historyEvents.length) {
        target.replaceChildren(node('p', 'empty-text', 'No observations match this view.'));
        return;
    }
    target.replaceChildren(...historyEvents.map((event) => {
        const button = node('button', 'history-item');
        const row = node('div', 'row');
        row.append(node('span', 'history-title', title(event.event_type)), node('span', 'risk-tag risk-' + event.risk_level, event.risk_level));
        const meta = node('div', 'history-meta');
        const date = new Date(event.timestamp);
        meta.append(node('span', '', 'Student ' + event.student_id), node('span', '', clock(event.video_time) + ' into video'), node('span', '', date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', second: '2-digit'})));
        if (event.is_demo) meta.append(node('span', 'demo-tag', 'SIMULATION'));
        button.append(row, meta);
        button.addEventListener('click', () => showEvidence(event));
        return button;
    }));
}

function showEvidence(event) {
    $('evidenceTitle').textContent = title(event.event_type);
    const image = $('evidenceImg');
    image.hidden = !event.evidence_url;
    $('evidenceUnavailable').hidden = !!event.evidence_url;
    if (event.evidence_url) image.src = event.evidence_url;
    else image.removeAttribute('src');
    const fields = [
        ['Recorded', new Date(event.timestamp).toLocaleString()],
        ['Source', event.is_demo ? 'Simulation (synthetic observations)' : 'Real footage'],
        ['Video time', clock(event.video_time)],
        ['Student / seat', 'Student ' + event.student_id + ' / ' + (event.seat_id == null ? 'Unassigned' : 'Seat ' + event.seat_id)],
        ['Risk', event.risk_level + ' ? ' + Number(event.risk_score).toFixed(1) + '/100'],
        ['Confidence', (event.confidence * 100).toFixed(1) + '%'],
        ['Duration', Number(event.duration).toFixed(1) + ' seconds'],
        ['Reasoning', event.reasoning],
    ];
    $('evidenceDetails').replaceChildren(...fields.flatMap(([label, value]) => [node('dt', '', label), node('dd', '', value)]));
    $('evidenceModal').showModal();
}

function beep() {
    if (!$('soundEnabled').checked || !audioContext) return;
    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();
    oscillator.connect(gain);
    gain.connect(audioContext.destination);
    oscillator.frequency.value = 740;
    gain.gain.setValueAtTime(.06, audioContext.currentTime);
    gain.gain.exponentialRampToValueAtTime(.001, audioContext.currentTime + .18);
    oscillator.start();
    oscillator.stop(audioContext.currentTime + .18);
}

function connection(online) {
    $('connection').className = 'connection ' + (online ? 'online' : 'offline');
    $('connection').replaceChildren(node('i'), document.createTextNode(online ? 'Connected' : 'Reconnecting'));
}

function connectWebSocket() {
    clearTimeout(reconnectTimer);
    socket = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
    socket.onopen = () => {
        connection(true);
        clearInterval(pollTimer);
        pollTimer = null;
        refreshHistory().catch(() => {});
    };
    socket.onmessage = (message) => {
        try {
            const data = JSON.parse(message.data);
            if (data.type === 'status') applyStatus(data.data);
            if (data.type === 'alert') { refreshHistory().catch(() => {}); beep(); }
            if (data.type === 'error') toast(data.message, true);
        } catch (error) { console.error('Invalid monitoring update', error); }
    };
    socket.onclose = () => {
        connection(false);
        reconnectTimer = setTimeout(connectWebSocket, 2000);
        if (!pollTimer) pollTimer = setInterval(() => {
            api('/api/status').then(applyStatus).catch(() => {});
        }, 2000);
    };
    socket.onerror = () => socket.close();
}

function drawSeats() {
    if (!editorImage) return;
    const canvas = $('seatCanvas');
    const context = canvas.getContext('2d');
    context.drawImage(editorImage, 0, 0, canvas.width, canvas.height);
    const boxes = [...editorBoxes];
    if (dragStart && dragEnd) boxes.push([Math.min(dragStart.x, dragEnd.x), Math.min(dragStart.y, dragEnd.y), Math.max(dragStart.x, dragEnd.x), Math.max(dragStart.y, dragEnd.y)]);
    boxes.forEach((box, index) => {
        context.fillStyle = '#c2dd8925';
        context.strokeStyle = '#d2f09b';
        context.lineWidth = Math.max(2, canvas.width / 500);
        context.fillRect(box[0], box[1], box[2] - box[0], box[3] - box[1]);
        context.strokeRect(box[0], box[1], box[2] - box[0], box[3] - box[1]);
        context.fillStyle = '#d2f09b';
        context.font = Math.max(14, canvas.width / 60) + 'px Segoe UI';
        context.fillText('Seat ' + (index + 1), box[0] + 5, box[1] + 21);
    });
    $('editorCount').textContent = editorBoxes.length + ' seats';
}

async function openSeatEditor() {
    try {
        const [layout, response] = await Promise.all([api('/api/seats?source=' + encodeURIComponent(selectedSource)), fetch(previewUrl)]);
        if (!response.ok) {
            const result = await response.json();
            throw new Error(result.detail || 'Unable to load the preview.');
        }
        const url = URL.createObjectURL(await response.blob());
        const image = new Image();
        await new Promise((resolve, reject) => {
            image.onload = resolve;
            image.onerror = () => reject(new Error('Could not decode the preview image.'));
            image.src = url;
        });
        URL.revokeObjectURL(url);
        editorImage = image;
        $('seatCanvas').width = image.naturalWidth;
        $('seatCanvas').height = image.naturalHeight;
        editorBoxes = Object.values(layout.seats).map((seat) => seat.bbox);
        dragStart = dragEnd = null;
        drawSeats();
        $('seatDialog').showModal();
    } catch (error) { toast(error.message, true); }
}

function canvasPoint(event) {
    const canvas = $('seatCanvas');
    const bounds = canvas.getBoundingClientRect();
    return {x: Math.max(0, Math.min(canvas.width, (event.clientX - bounds.left) * canvas.width / bounds.width)), y: Math.max(0, Math.min(canvas.height, (event.clientY - bounds.top) * canvas.height / bounds.height))};
}

function bindEvents() {
    document.querySelectorAll('[data-source]').forEach((button) => button.addEventListener('click', () => selectSource(button.dataset.source).catch((error) => toast(error.message, true))));
    $('savedVideos').addEventListener('change', () => selectSource('upload', $('savedVideos').value));
    $('cameraIndex').addEventListener('change', () => selectSource('camera'));
    $('videoFile').addEventListener('change', (event) => upload(event.target.files[0]));
    $('previewCameraBtn').addEventListener('click', async () => {
        try {
            const response = await fetch(previewUrl + '&t=' + Date.now());
            if (!response.ok) { const result = await response.json(); throw new Error(result.detail); }
            const url = URL.createObjectURL(await response.blob());
            $('liveView').onload = () => { URL.revokeObjectURL(url); $('liveView').onload = null; };
            showPreview(url);
        } catch (error) { toast(error.message, true); }
    });
    $('startBtn').addEventListener('click', () => command('/api/start', {source: selectedSource}));
    $('stopBtn').addEventListener('click', () => command('/api/stop'));
    $('configSeatsBtn').addEventListener('click', openSeatEditor);
    $('closeSeatsBtn').addEventListener('click', () => $('seatDialog').close());
    $('closeEvidenceBtn').addEventListener('click', () => $('evidenceModal').close());
    $('evidenceImg').addEventListener('error', () => { $('evidenceImg').hidden = true; $('evidenceUnavailable').hidden = false; });
    $('liveView').addEventListener('error', () => {
        if (selectedSource && !streaming) {
            $('videoMessage').textContent = 'Preview unavailable. Check the selected source and try again.';
            $('videoMessage').hidden = false;
        }
    });
    $('riskFilter').addEventListener('change', () => refreshHistory().catch((error) => toast(error.message, true)));
    $('modeFilter').addEventListener('change', () => { applyStatus(latestStatus); refreshHistory().catch((error) => toast(error.message, true)); });
    $('loadMoreBtn').addEventListener('click', () => refreshHistory(true).catch((error) => toast(error.message, true)));
    $('soundEnabled').addEventListener('change', async () => {
        try {
            if ($('soundEnabled').checked) {
                if (!audioContext) audioContext = new (window.AudioContext || window.webkitAudioContext)();
                await audioContext.resume();
            }
        } catch (_) { toast('Sound is unavailable in this browser.', true); }
    });
    const canvas = $('seatCanvas');
    canvas.addEventListener('pointerdown', (event) => {
        if (event.button !== 0) return;
        dragStart = dragEnd = canvasPoint(event);
        canvas.setPointerCapture(event.pointerId);
        drawSeats();
    });
    canvas.addEventListener('pointermove', (event) => { if (dragStart) { dragEnd = canvasPoint(event); drawSeats(); } });
    canvas.addEventListener('pointerup', (event) => {
        if (!dragStart) return;
        dragEnd = canvasPoint(event);
        const box = [Math.min(dragStart.x, dragEnd.x), Math.min(dragStart.y, dragEnd.y), Math.max(dragStart.x, dragEnd.x), Math.max(dragStart.y, dragEnd.y)];
        if (box[2] - box[0] > 8 && box[3] - box[1] > 8) editorBoxes.push(box.map(Math.round));
        dragStart = dragEnd = null;
        drawSeats();
    });
    canvas.addEventListener('pointercancel', () => { dragStart = dragEnd = null; drawSeats(); });
    $('undoSeatBtn').addEventListener('click', () => { editorBoxes.pop(); drawSeats(); });
    $('clearSeatsBtn').addEventListener('click', () => { editorBoxes = []; drawSeats(); });
    $('saveSeatsBtn').addEventListener('click', async () => {
        $('saveSeatsBtn').disabled = true;
        try {
            const seats = Object.fromEntries(editorBoxes.map((box, index) => [index + 1, box]));
            await api('/api/seats', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({source: selectedSource, width: canvas.width, height: canvas.height, seats})});
            $('seatDialog').close();
            await refreshSeatCount();
            toast(editorBoxes.length + ' seats saved for this source.');
        } catch (error) { toast(error.message, true); }
        finally { $('saveSeatsBtn').disabled = false; }
    });
}

async function init() {
    bindEvents();
    try {
        const [, health, status] = await Promise.all([refreshVideos(), api('/api/health'), api('/api/status')]);
        $('visionStatus').textContent = health.vision_ready ? '? Vision models ready' : 'Vision models need setup ? simulation available';
        if (busyStates.has(status.status)) {
            const kind = status.mode === 'demo' ? 'demo' : status.mode === 'camera' ? 'camera' : 'upload';
            if (kind === 'camera') $('cameraIndex').value = status.source.split(':')[1];
            if (kind === 'upload') $('savedVideos').value = status.source;
            await selectSource(kind, status.source);
        } else await selectSource('demo');
        applyStatus(status);
        await refreshHistory();
    } catch (error) { toast(error.message, true); }
    connectWebSocket();
}

init();
