"""
Motor de visión de GeotaxPro (v2).

En lugar de buscar "manchas oscuras" (que confunde rayas, líneas de una hoja o la
gradilla con moscas), el detector:

1. Restringe la búsqueda al interior de los tubos, usando la calibración del usuario
   (fondo, cima, centro del primer y último tubo).
2. Construye una imagen de la escena vacía con la MEDIANA temporal de fotogramas
   muestreados de todo el video. Todo lo que no se mueve (rayas del tubo, hoja con
   líneas, gradilla, reflejos fijos) queda en esa imagen y se cancela.
3. Marca como mosca solo lo que difiere de esa escena, con un umbral derivado del
   ruido propio del video (no un valor fijo).
4. Filtra por tamaño físico de una mosca (mm, convertido con px/cm).
5. Si varias moscas se juntan en una mancha, estima cuántas son por el área
   (área de la mancha / área típica de una mosca en ese video).

Limitación: una mosca que no se mueve en todo el video forma parte de la escena
y no puede distinguirse de una mancha fija.
"""
import csv
import cv2
import numpy as np

# Dimensiones aproximadas de D. melanogaster adulta
FLY_LENGTH_CM = 0.25
FLY_WIDTH_CM = 0.10


def _tube_mask(shape, calib):
    h, w = shape
    n = int(calib["n_tubes"])
    x_first, x_last = float(calib["x_first"]), float(calib["x_last"])
    y_top, y_bottom = sorted([float(calib["y_top"]), float(calib["y_bottom"])])
    paso = (x_last - x_first) / (n - 1) if n > 1 else float(calib.get("tube_width_px", 60))
    half = max(3, int(paso * 0.38))       # ancho útil del tubo, sin las paredes del vecino
    mask = np.zeros((h, w), np.uint8)
    lanes = []
    for i in range(n):
        cx = int(round(x_first + i * paso))
        x0, x1 = max(0, cx - half), min(w, cx + half)
        mask[int(y_top):int(y_bottom) + 1, x0:x1] = 255
        lanes.append((x0, x1))
    return mask, lanes


def _background(cap, n_frames, max_samples=60, scale=1.0):
    idxs = np.linspace(0, max(0, n_frames - 1), min(max_samples, max(1, n_frames))).astype(int)
    frames = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            frames.append(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    if not frames:
        raise ValueError("No se pudieron leer fotogramas del video.")
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def process_video(video_path: str, output_csv: str, output_video_path: str, calib: dict, sensitivity: float = 1.0):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise ValueError(f"No se pudo abrir el video: {video_path}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0 or np.isnan(fps):
        fps = 30.0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1

    ppc = float(calib["pixels_per_cm"])
    mask, lanes = _tube_mask((h, w), calib)
    bg = _background(cap, n_frames).astype(np.int16)
    bg_blur = cv2.GaussianBlur(bg.astype(np.uint8), (3, 3), 0).astype(np.int16)

    # Área teórica de una mosca en píxeles (elipse)
    fly_area_theo = np.pi / 4 * (FLY_LENGTH_CM * ppc) * (FLY_WIDTH_CM * ppc)
    min_area = max(2.0, 0.25 * fly_area_theo)
    max_blob = 25 * max(fly_area_theo, 4.0)   # manchas mayores = cambio de luz / movimiento del aparato

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))

    raw = []          # (frame, x, y, area)
    frame_idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_idx += 1
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (3, 3), 0).astype(np.int16)

        # Moscas = más oscuras que la escena vacía (diferencia con signo)
        diff = np.clip(bg_blur - gray, 0, 255).astype(np.uint8)
        # Compensar cambios globales de iluminación (mediana dentro de los tubos)
        roi_vals = diff[mask > 0]
        med = float(np.median(roi_vals))
        mad = float(np.median(np.abs(roi_vals - med))) + 1e-6
        thr = max(8.0, med + (6.0 / max(sensitivity, 0.1)) * 1.4826 * mad)
        _, fg = cv2.threshold(diff, thr, 255, cv2.THRESH_BINARY)
        fg = cv2.bitwise_and(fg, mask)
        fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, kernel)

        n_lbl, _, st, cen = cv2.connectedComponentsWithStats(fg, connectivity=8)
        for j in range(1, n_lbl):
            area = float(st[j, cv2.CC_STAT_AREA])
            if area < min_area or area > max_blob:
                continue
            bw, bh = st[j, cv2.CC_STAT_WIDTH], st[j, cv2.CC_STAT_HEIGHT]
            # una mosca o grupo es compacto; una raya/borde es larga y delgada
            if max(bw, bh) > 6 * max(1, min(bw, bh)) and area < 4 * fly_area_theo:
                continue
            raw.append((frame_idx, float(cen[j][0]), float(cen[j][1]), area,
                        int(st[j, 0]), int(st[j, 1]), int(bw), int(bh)))
    total = frame_idx

    # Área típica de una mosca en ESTE video. Se usa un percentil bajo de las manchas
    # de tamaño plausible, porque la mediana se infla con pares de moscas juntas.
    areas = np.array([r[3] for r in raw]) if raw else np.array([])
    plausibles = areas[(areas >= min_area) & (areas <= 2.5 * fly_area_theo)] if len(areas) else areas
    fly_area = float(np.percentile(plausibles, 35)) if len(plausibles) >= 20 else fly_area_theo

    rows = []
    by_frame = {}
    for fr, x, y, a, bx, by, bw, bh in raw:
        n = max(1, int(round(a / fly_area)))
        rows.append({"frame": fr, "x": round(x, 1), "y": round(y, 1), "area": a, "n": n})
        by_frame.setdefault(fr, []).append((bx, by, bw, bh, n))

    # Segunda pasada: video anotado
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    out = cv2.VideoWriter(output_video_path, cv2.VideoWriter_fourcc(*"vp80"), fps, (w, h))
    y_top, y_bottom = sorted([float(calib["y_top"]), float(calib["y_bottom"])])
    y_goal = int(y_bottom - float(calib.get("target_cm", 10)) * ppc)
    fi = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        fi += 1
        for x0, x1 in lanes:
            cv2.rectangle(frame, (x0, int(y_top)), (x1, int(y_bottom)), (255, 200, 0), 1)
        cv2.line(frame, (lanes[0][0], y_goal), (lanes[-1][1], y_goal), (0, 0, 255), 1)
        count = 0
        for bx, by, bw, bh, n in by_frame.get(fi, []):
            cv2.rectangle(frame, (bx - 1, by - 1), (bx + bw + 1, by + bh + 1), (0, 255, 0), 1)
            if n > 1:
                cv2.putText(frame, str(n), (bx + bw + 2, by + bh), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
            count += n
        cv2.putText(frame, f"Moscas: {count}", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        out.write(frame)
    cap.release()
    out.release()

    with open(output_csv, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=["frame", "x", "y", "area", "n"])
        wr.writeheader()
        wr.writerows(rows)

    counts = [sum(b[4] for b in by_frame.get(i, [])) for i in range(1, total + 1)]
    return {
        "status": "success" if rows else "warning",
        "frames_processed": total,
        "detections": len(rows),
        "fps": fps,
        "fly_area_px": round(fly_area, 1),
        "moscas_por_frame_mediana": float(np.median(counts)) if counts else 0.0,
        "moscas_por_frame_p90": float(np.percentile(counts, 90)) if counts else 0.0,
        "message": None if rows else "No se detectaron moscas dentro de los tubos.",
    }
