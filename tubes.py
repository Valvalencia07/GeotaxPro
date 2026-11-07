"""
Métricas por tubo para el ensayo RING.

Cada detección se asigna a un tubo según su coordenada x, usando los centros
del primer y último tubo marcados por el usuario (los tubos están equiespaciados).
La altura se mide desde el fondo del tubo marcado en la calibración.

Llegadas a la meta
------------------
Sin identificar individualmente a cada mosca no se puede saber si la mosca que
cruza la meta es nueva o una que ya había llegado, bajó y volvió a subir. Para no
contar dos veces a la misma mosca, el acumulado de llegadas es el MÁXIMO número de
moscas que se han visto simultáneamente sobre la meta hasta ese momento:

  - si una mosca llega y luego baja, el acumulado no disminuye;
  - si vuelve a subir, no se cuenta de nuevo;
  - el acumulado nunca supera el número de moscas por tubo.

Para evitar que un fotograma ruidoso infle el conteo, el número de moscas sobre la
meta se suaviza con una mediana móvil de ~0.2 s antes de calcular el máximo.
"""
import csv
import math
import numpy as np


def asignar_tubo(x, x_first, x_last, n_tubes):
    if n_tubes == 1:
        return 0
    paso = (x_last - x_first) / (n_tubes - 1)
    if paso == 0:
        return None
    idx = int(round((x - x_first) / paso))
    if idx < 0 or idx >= n_tubes:
        return None
    return idx


def _mediana_movil(v, k):
    if k <= 1 or len(v) == 0:
        return v.astype(float)
    pad = k // 2
    vp = np.pad(v.astype(float), (pad, pad), mode="edge")
    win = np.lib.stride_tricks.sliding_window_view(vp, k)
    return np.floor(np.median(win, axis=1))


def metricas_por_tubo(csv_path, calib, t_obj=3.0, ventana_s=0.1):
    ppc = float(calib.get("pixels_per_cm", 50.0)) or 50.0
    target = float(calib.get("target_cm", 10.0))
    fps = float(calib.get("fps", 30.0)) or 30.0
    n_tubes = int(calib.get("n_tubes", 10))
    flies = int(calib.get("flies_per_tube", 10)) or 10
    y_bottom = calib.get("y_bottom")
    x_first, x_last = calib.get("x_first"), calib.get("x_last")
    if y_bottom is None or x_first is None or x_last is None:
        raise ValueError("Este video se procesó sin marcar la posición de los tubos. Vuelve a procesarlo con la versión actual.")

    f_lo = int(round((t_obj - ventana_s) * fps))
    f_hi = int(round((t_obj + ventana_s) * fps))

    rows = []
    max_frame = int(calib.get("frames_processed") or 0)
    with open(csv_path, newline="") as f:
        for row in csv.DictReader(f):
            fr = int(row["frame"])
            max_frame = max(max_frame, fr)
            t = asignar_tubo(float(row["x"]), x_first, x_last, n_tubes)
            if t is None:
                continue
            h = max(0.0, (float(y_bottom) - float(row["y"])) / ppc)
            rows.append((fr, t, h, int(row.get("n") or 1)))

    # Moscas sobre la meta por fotograma y tubo; alturas en la ventana de 3 s
    sobre = np.zeros((n_tubes, max_frame + 1), dtype=int)
    alturas = [[] for _ in range(n_tubes)]
    for fr, t, h, n in rows:
        if h >= target:
            sobre[t, fr] += n
        if f_lo <= fr <= f_hi:
            alturas[t].extend([h] * n)

    k = max(1, int(round(0.2 * fps)) | 1)          # ventana impar de ~0.2 s
    dur = max_frame / fps
    n_seg = max(1, int(math.ceil(dur)))
    tubos = []
    for i in range(n_tubes):
        suave = _mediana_movil(sobre[i], k)
        acum = np.minimum(np.maximum.accumulate(suave), flies).astype(int)
        llegadas = np.nonzero(acum >= 1)[0]
        primera = round(float(llegadas[0]) / fps, 2) if len(llegadas) else None
        # acumulado al final de cada segundo (1, 2, ..., n_seg)
        por_seg = [int(acum[min(max_frame, int(round(s * fps)))]) for s in range(1, n_seg + 1)]
        hs = alturas[i]
        tubos.append({
            "tubo": i + 1,
            "primera_llegada_s": primera,
            "llegadas_por_segundo": por_seg,
            "total_llegadas": int(acum[-1]) if len(acum) else 0,
            "pct_llegaron": round(100.0 * (int(acum[-1]) if len(acum) else 0) / flies, 1),
            "altura_media_cm": round(float(np.mean(hs)), 2) if hs else None,
        })
    return {
        "tubos": tubos,
        "segundos": list(range(1, n_seg + 1)),
        "duracion_s": round(dur, 2),
        "fps": round(fps, 2),
        "moscas_por_tubo": flies,
        "meta_cm": target,
    }
