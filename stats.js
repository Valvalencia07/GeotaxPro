document.addEventListener('DOMContentLoaded', () => {
    const container = document.getElementById('stats-groups');
    const results = document.getElementById('stats-results');
    let counter = 0;

    const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    const fmtP = p => p < 0.001 ? '< 0.001' : p.toFixed(3);
    const num = (v, d = 2) => (v === null || v === undefined) ? '—' : Number(v).toFixed(d);

    function parseValues(text) {
        // Si los valores vienen uno por línea (o separados por ;) y no hay puntos,
        // la coma se interpreta como decimal (formato de Excel en español).
        const t = text.trim();
        if (/[\n;\t]/.test(t) && !t.includes('.')) {
            return t.split(/[\s;]+/).filter(s => s !== '').map(s => Number(s.replace(',', '.')));
        }
        return t.split(/[\s;,]+/).filter(s => s !== '').map(Number);
    }

    function addGroup(name = '') {
        counter++;
        const card = document.createElement('div');
        card.className = 'stats-group';
        card.style.cssText = 'border:1px solid var(--glass-border); border-radius:8px; padding:10px;';
        card.innerHTML = `
            <div style="display:flex; gap:6px; margin-bottom:6px;">
                <input type="text" class="g-name" placeholder="Nombre del grupo" value="${esc(name || 'Grupo ' + counter)}" style="flex:1; padding:4px; border-radius:4px;">
                <button class="g-del" title="Quitar grupo" style="border:none; background:transparent; color:inherit; cursor:pointer;">✕</button>
            </div>
            <textarea class="g-vals" rows="8" placeholder="10 valores, uno por tubo" style="width:100%; box-sizing:border-box; padding:6px; border-radius:4px; font-family:monospace;"></textarea>
            <div class="g-count" style="font-size:0.8em; opacity:0.7; margin-top:4px;">0 tubos</div>`;
        const ta = card.querySelector('.g-vals');
        const cnt = card.querySelector('.g-count');
        ta.addEventListener('input', () => {
            const v = parseValues(ta.value);
            const bad = v.filter(x => isNaN(x)).length;
            cnt.textContent = `${v.length - bad} tubos` + (bad ? ` · ${bad} valor(es) no numérico(s)` : '');
            cnt.style.color = bad ? '#e57373' : '';
        });
        card.querySelector('.g-del').addEventListener('click', () => card.remove());
        container.appendChild(card);
    }

    addGroup('Control');
    addGroup('Tratamiento');
    document.getElementById('stats-add-group').addEventListener('click', () => addGroup());

    // Permite que el Workspace envíe los valores de un video a un grupo
    window.addStatsGroup = (name, values) => {
        let target = null;
        container.querySelectorAll('.stats-group').forEach(card => {
            const n = card.querySelector('.g-name').value.trim();
            const empty = card.querySelector('.g-vals').value.trim() === '';
            if (n === name) target = card;
            else if (!target && empty && /^(Control|Tratamiento|Grupo \d+)$/.test(n)) target = target || card;
        });
        if (!target) { addGroup(name); target = container.lastElementChild; }
        target.querySelector('.g-name').value = name;
        const ta = target.querySelector('.g-vals');
        const prev = ta.value.trim();
        ta.value = (prev ? prev + '\n' : '') + values.join('\n');
        ta.dispatchEvent(new Event('input'));
    };

    document.getElementById('stats-run').addEventListener('click', async () => {
        const grupos = {};
        let error = null;
        container.querySelectorAll('.stats-group').forEach(card => {
            const name = card.querySelector('.g-name').value.trim();
            const vals = parseValues(card.querySelector('.g-vals').value);
            if (!name) error = 'Todos los grupos necesitan nombre.';
            else if (grupos[name]) error = `El nombre "${name}" está repetido.`;
            else if (vals.some(isNaN)) error = `El grupo "${name}" tiene valores no numéricos.`;
            grupos[name] = vals;
        });
        if (!error && Object.keys(grupos).length < 2) error = 'Agrega al menos 2 grupos.';
        if (error) { showError(error); return; }

        const unidad = document.getElementById('stats-metric').value;
        const alpha = parseFloat(document.getElementById('stats-alpha').value) || 0.05;
        try {
            const res = await fetch('/api/stats', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ grupos, alpha, unidad })
            });
            const data = await res.json();
            if (!res.ok) { showError(data.message || 'Error en el análisis.'); return; }
            render(data, alpha);
        } catch (e) {
            showError('Error de conexión: ' + e);
        }
    });

    function showError(msg) {
        results.classList.remove('hidden');
        results.innerHTML = `<p style="color:#e57373;">${esc(msg)}</p>`;
    }

    function render(d, alpha) {
        const u = d.unidad;
        let html = `<h3>Resultado</h3>
            <p style="font-size:1.05em; line-height:1.5;"><strong>${esc(d.conclusion)}</strong></p>
            <h4 style="margin-top:18px;">Por qué se eligió esta prueba</h4>
            <ul>${d.razonamiento.map(r => `<li>${esc(r)}</li>`).join('')}</ul>`;
        if (d.advertencias.length) {
            html += `<h4>Advertencias</h4><ul style="color:#ffb74d;">${d.advertencias.map(r => `<li>${esc(r)}</li>`).join('')}</ul>`;
        }
        html += `<h4 style="margin-top:18px;">Estadística descriptiva (${esc(u)})</h4>
            <table class="stats-table"><tr><th>Grupo</th><th>n</th><th>Media</th><th>DE</th><th>EEM</th><th>Mediana</th><th>RIC</th><th>Shapiro p</th></tr>
            ${d.grupos.map(g => {
                const s = d.descriptivos[g];
                return `<tr><td>${esc(g)}</td><td>${s.n}</td><td>${num(s.media)}</td><td>${num(s.de)}</td><td>${num(s.eem)}</td><td>${num(s.mediana)}</td><td>${num(s.q1)}–${num(s.q3)}</td><td>${d.supuestos.shapiro_p[g] === null ? '—' : fmtP(d.supuestos.shapiro_p[g])}</td></tr>`;
            }).join('')}</table>
            <p style="opacity:0.8;">Brown-Forsythe (homogeneidad de varianzas): p ${fmtP(d.supuestos.levene_p)}</p>`;
        if (d.posthoc) {
            html += `<h4 style="margin-top:18px;">Post hoc: ${esc(d.posthoc.prueba)}</h4>
                <table class="stats-table"><tr><th>Comparación</th><th>Diferencia</th><th>p ajustada</th><th></th></tr>
                ${d.posthoc.comparaciones.map(c => `<tr><td>${esc(c.comparacion)}</td><td>${num(c.diferencia)}</td><td>${fmtP(c.p_ajustada)}</td><td>${c.p_ajustada < alpha ? '*' : 'n.s.'}</td></tr>`).join('')}
                </table>`;
        }
        html += `<div id="stats-plot" style="margin-top:20px; height:420px;"></div>`;
        results.innerHTML = html;
        results.classList.remove('hidden');

        if (window.Plotly) {
            const traces = d.grupos.map(g => ({
                y: d.valores[g], name: g, type: 'box', boxpoints: 'all', jitter: 0.4, pointpos: 0,
                marker: { size: 7 }, line: { width: 1.5 }
            }));
            Plotly.newPlot('stats-plot', traces, {
                paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
                font: { color: '#ccc' }, showlegend: false,
                yaxis: { title: { text: u === '%' ? '% de moscas que llegaron a la meta' : u === 's' ? 'Tiempo de la primera llegada (s)' : 'Altura media a los 3 s (cm)' }, gridcolor: '#3e3e42', zeroline: false },
                margin: { t: 20 }
            }, { responsive: true, displaylogo: false });
        }
    }
});
