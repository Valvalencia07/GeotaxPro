document.addEventListener('DOMContentLoaded', () => {
    // Tab Navigation
    const navLinks = document.querySelectorAll('.nav-links li');
    const tabContents = document.querySelectorAll('.tab-content');

    navLinks.forEach(link => {
        link.addEventListener('click', () => {
            // Remove active class from all
            navLinks.forEach(n => n.classList.remove('active'));
            tabContents.forEach(t => t.classList.remove('active'));

            // Add active class to clicked
            link.classList.add('active');
            const targetId = link.getAttribute('data-target');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // File Upload Simulation
    const uploadBox = document.getElementById('upload-box');
    const videoInput = document.getElementById('video-input');
    const previewPanel = document.getElementById('video-preview-panel');
    const terminal = document.getElementById('terminal-output');
    
    let currentSessionId = "";

    uploadBox.addEventListener('click', () => videoInput.click());

    videoInput.addEventListener('change', (e) => {
        if(e.target.files.length > 0) {
            uploadBox.classList.add('hidden');
            previewPanel.classList.remove('hidden');
            
            const file = e.target.files[0];
            const calibPanel = document.getElementById('calibration-panel');
            calibPanel.classList.remove('hidden');
            const startBtn = document.getElementById('start-processing-btn');
            
            const videoUrl = URL.createObjectURL(file);
            const hiddenVideo = document.createElement('video');
            hiddenVideo.src = videoUrl;
            hiddenVideo.muted = true;
            
            hiddenVideo.addEventListener('loadeddata', () => {
                hiddenVideo.currentTime = 0.5; // Ir a 0.5s
            });
            
            let clicks = 0;
            let y1 = 0;
            let y2 = 0;
            let xFirst = 0;
            let xLast = 0;
            const canvas = document.getElementById('calibration-canvas');
            const ctx = canvas.getContext('2d');
            
            hiddenVideo.addEventListener('seeked', () => {
                canvas.width = hiddenVideo.videoWidth;
                canvas.height = hiddenVideo.videoHeight;
                canvas.style.width = '100%';
                ctx.drawImage(hiddenVideo, 0, 0, canvas.width, canvas.height);
                terminal.innerHTML += `> [Sistema] Esperando calibración visual del usuario...<br>`;
            });

            const handleCanvasClick = (evt) => {
                const rect = canvas.getBoundingClientRect();
                const x = (evt.clientX - rect.left) * (canvas.width / rect.width);
                const y = (evt.clientY - rect.top) * (canvas.height / rect.height);
                const lw = Math.max(3, canvas.width / 300);

                if (clicks === 0) {
                    y1 = y;
                    ctx.beginPath(); ctx.moveTo(0, y1); ctx.lineTo(canvas.width, y1);
                    ctx.strokeStyle = "red"; ctx.lineWidth = lw; ctx.stroke();
                } else if (clicks === 1) {
                    y2 = y;
                    ctx.beginPath(); ctx.moveTo(0, y2); ctx.lineTo(canvas.width, y2);
                    ctx.strokeStyle = "blue"; ctx.lineWidth = lw; ctx.stroke();
                } else if (clicks === 2) {
                    xFirst = x;
                } else if (clicks === 3) {
                    xLast = x;
                    // Dibujar el centro estimado de cada tubo
                    const n = Math.max(1, parseInt(document.getElementById('n-tubes').value) || 10);
                    const paso = n > 1 ? (xLast - xFirst) / (n - 1) : 0;
                    ctx.font = `${Math.round(lw * 6)}px sans-serif`;
                    for (let i = 0; i < n; i++) {
                        const cx = xFirst + i * paso;
                        ctx.beginPath(); ctx.moveTo(cx, Math.min(y1, y2)); ctx.lineTo(cx, Math.max(y1, y2));
                        ctx.strokeStyle = "yellow"; ctx.lineWidth = lw / 2; ctx.stroke();
                        ctx.fillStyle = "yellow"; ctx.fillText(String(i + 1), cx - lw * 2, Math.min(y1, y2) - lw * 2);
                    }
                } else {
                    return;
                }
                if (clicks >= 2) {
                    ctx.beginPath(); ctx.arc(x, y, lw * 2, 0, 2 * Math.PI);
                    ctx.fillStyle = "yellow"; ctx.fill();
                }
                clicks++;
                if (clicks === 4) {
                    startBtn.disabled = false;
                    startBtn.textContent = "Iniciar Procesamiento de Geotaxis";
                    startBtn.style.background = "var(--accent)";
                    startBtn.style.color = "black";
                    startBtn.style.cursor = "pointer";
                } else {
                    startBtn.textContent = `Esperando ${4 - clicks} clic(s) de calibración...`;
                }
            };

            document.getElementById('reset-calib-btn').onclick = () => {
                clicks = 0;
                ctx.drawImage(hiddenVideo, 0, 0, canvas.width, canvas.height);
                startBtn.disabled = true;
                startBtn.textContent = "Esperando 4 clics de calibración...";
                startBtn.style.background = "#555";
                startBtn.style.color = "white";
                startBtn.style.cursor = "not-allowed";
            };
            
            canvas.addEventListener('click', handleCanvasClick);
            
            startBtn.onclick = async () => {
                canvas.removeEventListener('click', handleCanvasClick);
                calibPanel.classList.add('hidden');
                
                const tubeCm = parseFloat(document.getElementById('tube-cm').value);
                const targetCm = parseFloat(document.getElementById('target-cm').value);
                let pixelHeight = Math.abs(y2 - y1);
                if (pixelHeight === 0) pixelHeight = 1;
                
                const pixelsPerCm = pixelHeight / tubeCm;
                
                terminal.innerHTML += `> [Calibración] Calculado: ${pixelsPerCm.toFixed(2)} px/cm. Meta a ${targetCm} cm.<br>`;
                terminal.innerHTML += `> Cargando video: ${file.name}...<br>`;
                
                const formData = new FormData();
                formData.append("file", file);
                formData.append("pixels_per_cm", pixelsPerCm.toFixed(4));
                formData.append("target_cm", targetCm.toFixed(2));
                // El fondo es el clic con mayor y (más abajo en la imagen)
                formData.append("y_bottom", Math.max(y1, y2).toFixed(1));
                formData.append("y_top", Math.min(y1, y2).toFixed(1));
                formData.append("x_first", Math.min(xFirst, xLast).toFixed(1));
                formData.append("x_last", Math.max(xFirst, xLast).toFixed(1));
                formData.append("n_tubes", String(Math.max(1, parseInt(document.getElementById('n-tubes').value) || 10)));
                formData.append("flies_per_tube", String(Math.max(1, parseInt(document.getElementById('flies-per-tube').value) || 10)));
                
                try {
                    terminal.innerHTML += `> [Luis] Inicializando Pipeline OpenCV...<br>`;
                    const response = await fetch('/api/upload', {
                        method: 'POST',
                        body: formData
                    });
                    
                    const data = await response.json();
                    
                    if(response.ok) {
                        currentSessionId = data.session_id; // Save UUID
                        terminal.innerHTML += `> <span style="color:var(--accent)">[Luis] Video encolado. Procesando en segundo plano...</span><br>`;
                        
                        // Start polling
                        const pollInterval = setInterval(async () => {
                            try {
                                const statusRes = await fetch(`/api/status/${currentSessionId}`);
                                const statusData = await statusRes.json();
                                
                                if (statusData.status === 'completed') {
                                    clearInterval(pollInterval);
                                    const logs = statusData.data?.logs || [];
                                    logs.forEach(log => {
                                        terminal.innerHTML += `> ${log}<br>`;
                                    });
                                    
                                    if (statusData.data?.status === 'success') {
                                        const results = statusData.data.results;
                                        terminal.innerHTML += `> <span style="color:var(--accent)">[Luis] Procesamiento completado con éxito.</span><br>`;
                                        terminal.innerHTML += `> Frames: ${results?.frames_processed || 0} | Detecciones: ${results?.detections || 0}<br>`;
                                        terminal.innerHTML += `> [Luis] Datos guardados. Felipe ya puede analizarlos.<br>`;
                                        
                                        const badge = document.querySelector('.status-badge');
                                        if(badge) {
                                            badge.textContent = 'Completado';
                                            badge.style.background = 'var(--accent)';
                                            badge.style.color = '#000';
                                        }
                                        
                                        if(statusData.data?.video_url) {
                                            const canvasContainer = document.querySelector('.canvas-container');
                                            canvasContainer.innerHTML = `<video src="${statusData.data.video_url}" autoplay loop muted controls style="width:100%; border-radius:8px;"></video>`;
                                        }
                                        loadTubes(currentSessionId);
                                    } else {
                                        terminal.innerHTML += `> <span style="color:yellow">[Luis] Terminó con advertencias: ${statusData.data?.message}</span><br>`;
                                    }
                                    terminal.scrollTop = terminal.scrollHeight;
                                } else if (statusData.status === 'error') {
                                    clearInterval(pollInterval);
                                    terminal.innerHTML += `> <span style="color:red">Error crítico de Luis: ${statusData.message}</span><br>`;
                                } else {
                                    terminal.innerHTML += `<span style="color:#555">.</span>`;
                                    terminal.scrollTop = terminal.scrollHeight;
                                }
                            } catch (e) {
                                terminal.innerHTML += `> <span style="color:red">Error consultando estado... reconectando</span><br>`;
                            }
                        }, 3000); 
                    } else {
                        terminal.innerHTML += `> <span style="color:red">Error: ${data.message}</span><br>`;
                    }
                } catch (err) {
                    terminal.innerHTML += `> <span style="color:red">Error de red: ${err}</span><br>`;
                }
            };
        }
    });

    // Resultados por tubo
    let tubesData = null;
    let tubesSession = null;
    const sentSessions = new Set();
    const EXCLUIR = '(Excluir)';

    function groupNames() {
        return document.getElementById('tubes-group-names').value.split(',').map(s => s.trim()).filter(Boolean);
    }

    function renderTubes(assign) {
        const table = document.getElementById('tubes-table');
        const names = groupNames();
        const opts = [...names, EXCLUIR];
        const fmt = v => v === null ? '—' : v;
        const segs = tubesData.segundos;
        const totales = segs.map((_, j) => tubesData.tubos.reduce((a, t) => a + t.llegadas_por_segundo[j], 0));
        table.innerHTML = `<div style="overflow-x:auto;"><table class="stats-table"><tr><th>Tubo</th><th>Grupo</th><th>1ª llegada (s)</th>
            ${segs.map(s => `<th>${s} s</th>`).join('')}<th>Total</th></tr>
            ${tubesData.tubos.map((t, i) => `<tr><td>${t.tubo}</td><td><select class="tube-group" data-i="${i}" style="padding:3px; border-radius:4px;">
                ${opts.map(o => `<option${o === assign[i] ? ' selected' : ''}>${o.replace(/</g, '&lt;')}</option>`).join('')}</select></td>
                <td>${fmt(t.primera_llegada_s)}</td>
                ${t.llegadas_por_segundo.map(c => `<td>${c}</td>`).join('')}<td><strong>${t.total_llegadas}</strong></td></tr>`).join('')}
            <tr><td colspan="3"><strong>Todos los tubos</strong></td>${totales.map(c => `<td><strong>${c}</strong></td>`).join('')}
                <td><strong>${tubesData.tubos.reduce((a, t) => a + t.total_llegadas, 0)}</strong></td></tr></table></div>
            <div id="arrivals-plot" style="height:340px; margin-top:15px;"></div>`;
        if (window.Plotly) {
            Plotly.newPlot('arrivals-plot', tubesData.tubos.map(t => ({
                x: [0, ...segs], y: [0, ...t.llegadas_por_segundo], name: `Tubo ${t.tubo}`, mode: 'lines+markers', line: { shape: 'hv' }
            })), {
                paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)', font: { color: '#ccc' },
                xaxis: { title: { text: 'Tiempo (s)' }, gridcolor: '#3e3e42' },
                yaxis: { title: { text: 'Moscas que han llegado a la meta' }, gridcolor: '#3e3e42', rangemode: 'tozero' },
                margin: { t: 20 }
            }, { responsive: true, displaylogo: false });
        }
    }

    function splitAssign() {
        const names = groupNames();
        const n = tubesData.tubos.length;
        const k = Math.min(n, Math.max(0, parseInt(document.getElementById('tubes-split').value) || 0));
        return tubesData.tubos.map((_, i) => i < k ? (names[0] || EXCLUIR) : (names[1] || names[0] || EXCLUIR));
    }

    function currentAssign() {
        return [...document.querySelectorAll('.tube-group')].map(s => s.value);
    }

    async function loadTubes(sessionId) {
        const panel = document.getElementById('tubes-panel');
        const table = document.getElementById('tubes-table');
        panel.classList.remove('hidden');
        try {
            const res = await fetch(`/api/tubes/${sessionId}`);
            const d = await res.json();
            if (!res.ok) { table.innerHTML = `<p style="color:#e57373;">${d.message}</p>`; return; }
            tubesData = d;
            tubesSession = sessionId;
            document.getElementById('tubes-split').value = Math.floor(d.tubos.length / 2);
            const primeras = d.tubos.map(t => t.primera_llegada_s).filter(v => v !== null);
            document.getElementById('tubes-info').textContent =
                `Meta: ${d.meta_cm} cm. Duración: ${d.duracion_s} s a ${d.fps} fps. ` +
                (primeras.length ? `Primera mosca en la meta: ${Math.min(...primeras)} s. ` : 'Ninguna mosca llegó a la meta. ') +
                `Cada columna es el acumulado de moscas que han llegado hasta ese segundo (una mosca que baja y vuelve a subir no se cuenta dos veces).`;
            renderTubes(splitAssign());
        } catch (e) {
            table.innerHTML = `<p style="color:#e57373;">Error al calcular resultados por tubo: ${e}</p>`;
        }
    }

    document.getElementById('tubes-apply-split').addEventListener('click', () => { if (tubesData) renderTubes(splitAssign()); });
    document.getElementById('tubes-group-names').addEventListener('change', () => { if (tubesData) renderTubes(splitAssign()); });

    document.getElementById('tubes-send').addEventListener('click', () => {
        const msg = document.getElementById('tubes-send-msg');
        if (!tubesData) { msg.textContent = 'No hay datos por tubo.'; return; }
        if (sentSessions.has(tubesSession) && !confirm('Este video ya se envió a Estadística. ¿Enviarlo otra vez? Se duplicarían sus tubos.')) return;
        const metric = document.getElementById('stats-metric').value;
        const campo = { '%': 'pct_llegaron', 's': 'primera_llegada_s', 'cm': 'altura_media_cm' }[metric];
        const assign = currentAssign();
        const porGrupo = {};
        let omitidos = 0;
        tubesData.tubos.forEach((t, i) => {
            const g = assign[i];
            if (g === EXCLUIR) return;
            const v = t[campo];
            if (v === null || v === undefined) { omitidos++; return; }
            (porGrupo[g] = porGrupo[g] || []).push(v);
        });
        Object.entries(porGrupo).forEach(([g, vals]) => window.addStatsGroup(g, vals));
        sentSessions.add(tubesSession);
        msg.textContent = 'Enviado: ' + Object.entries(porGrupo).map(([g, v]) => `${g} (${v.length} tubos)`).join(', ')
            + (omitidos ? `. ${omitidos} tubo(s) omitidos por no tener dato${metric === 's' ? ' (ninguna mosca llegó a la meta)' : ''}.` : '.');
    });

    document.getElementById('reset-all-btn').addEventListener('click', () => {
        if (confirm('Se borrarán el video actual, los resultados por tubo y los datos de Estadística. ¿Continuar?')) {
            location.reload();
        }
    });

    document.getElementById('new-video-btn').addEventListener('click', () => {
        tubesData = null;
        tubesSession = null;
        videoInput.value = '';
        document.getElementById('tubes-panel').classList.add('hidden');
        document.getElementById('tubes-table').innerHTML = '';
        document.getElementById('tubes-send-msg').textContent = '';
        previewPanel.classList.add('hidden');
        document.querySelector('.canvas-container').innerHTML = '<canvas id="cv-canvas"></canvas>';
        const badge = document.querySelector('.status-badge');
        if (badge) { badge.textContent = 'Procesando...'; badge.style.background = ''; badge.style.color = ''; }
        const startBtn = document.getElementById('start-processing-btn');
        startBtn.disabled = true;
        startBtn.textContent = 'Esperando 4 clics de calibración...';
        startBtn.style.background = '#555'; startBtn.style.color = 'white'; startBtn.style.cursor = 'not-allowed';
        uploadBox.classList.remove('hidden');
        window.scrollTo(0, 0);
    });

});
