"""
Motor estadístico de GeotaxPro.

Compara grupos experimentales usando un valor por tubo (unidad experimental).
La elección de la prueba es determinista y se basa en la revisión de supuestos:
  - Normalidad por grupo (Shapiro-Wilk)
  - Homogeneidad de varianzas (Brown-Forsythe / Levene centrado en la mediana)

  2 grupos:  t de Student | t de Welch | U de Mann-Whitney
  3+ grupos: ANOVA + Tukey HSD | ANOVA de Welch + Games-Howell | Kruskal-Wallis + Dunn (Holm)
"""
import math
from itertools import combinations

import numpy as np
from scipy import stats

ALPHA_SUPUESTOS = 0.05


def _holm(pvals):
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    adj = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        val = min(1.0, (m - rank) * pvals[i])
        running = max(running, val)
        adj[i] = running
    return adj


def _descriptivos(x):
    q1, med, q3 = np.percentile(x, [25, 50, 75])
    sd = float(np.std(x, ddof=1)) if len(x) > 1 else 0.0
    return {
        "n": int(len(x)),
        "media": float(np.mean(x)),
        "de": sd,
        "eem": sd / math.sqrt(len(x)) if len(x) > 0 else 0.0,
        "mediana": float(med),
        "q1": float(q1),
        "q3": float(q3),
        "min": float(np.min(x)),
        "max": float(np.max(x)),
    }


def _atipicos(x):
    q1, q3 = np.percentile(x, [25, 75])
    iqr = q3 - q1
    lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return [float(v) for v in x if v < lo or v > hi]


def _shapiro(x):
    if len(x) < 3:
        return None
    if np.ptp(x) == 0:
        return 0.0  # sin variación: no puede considerarse normal
    return float(stats.shapiro(x).pvalue)


def _welch_anova(groups):
    k = len(groups)
    n = np.array([len(g) for g in groups], dtype=float)
    m = np.array([np.mean(g) for g in groups])
    v = np.array([np.var(g, ddof=1) for g in groups])
    w = n / v
    sw = w.sum()
    mw = (w * m).sum() / sw
    a = (w * (m - mw) ** 2).sum() / (k - 1)
    tmp = (((1 - w / sw) ** 2) / (n - 1)).sum()
    b = 1 + 2 * (k - 2) / (k ** 2 - 1) * tmp
    f = a / b
    df1 = k - 1
    df2 = (k ** 2 - 1) / (3 * tmp)
    p = float(stats.f.sf(f, df1, df2))
    return float(f), df1, float(df2), p


def _games_howell(groups, names):
    k = len(groups)
    out = []
    for i, j in combinations(range(k), 2):
        gi, gj = groups[i], groups[j]
        ni, nj = len(gi), len(gj)
        vi, vj = np.var(gi, ddof=1), np.var(gj, ddof=1)
        diff = float(np.mean(gi) - np.mean(gj))
        se = math.sqrt(vi / ni + vj / nj)
        df = (vi / ni + vj / nj) ** 2 / ((vi / ni) ** 2 / (ni - 1) + (vj / nj) ** 2 / (nj - 1))
        q = abs(diff) / (se / math.sqrt(2))
        p = float(stats.studentized_range.sf(q, k, df))
        out.append({"comparacion": f"{names[i]} vs {names[j]}", "diferencia": diff, "p_ajustada": min(p, 1.0)})
    return out


def _dunn(groups, names):
    allv = np.concatenate(groups)
    N = len(allv)
    ranks = stats.rankdata(allv)
    _, counts = np.unique(allv, return_counts=True)
    ties = float(((counts ** 3) - counts).sum())
    base = N * (N + 1) / 12.0 - ties / (12.0 * (N - 1))
    idx, mean_ranks = 0, []
    for g in groups:
        mean_ranks.append(ranks[idx: idx + len(g)].mean())
        idx += len(g)
    pairs, raw = [], []
    for i, j in combinations(range(len(groups)), 2):
        se = math.sqrt(base * (1 / len(groups[i]) + 1 / len(groups[j])))
        z = (mean_ranks[i] - mean_ranks[j]) / se
        raw.append(float(2 * stats.norm.sf(abs(z))))
        pairs.append((i, j, float(np.median(groups[i]) - np.median(groups[j]))))
    adj = _holm(raw)
    return [
        {"comparacion": f"{names[i]} vs {names[j]}", "diferencia": d, "p_ajustada": adj[n]}
        for n, (i, j, d) in enumerate(pairs)
    ]


def _tukey(groups, names):
    res = stats.tukey_hsd(*groups)
    out = []
    for i, j in combinations(range(len(groups)), 2):
        out.append({
            "comparacion": f"{names[i]} vs {names[j]}",
            "diferencia": float(np.mean(groups[i]) - np.mean(groups[j])),
            "p_ajustada": float(res.pvalue[i, j]),
        })
    return out


def _fmt_p(p):
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def analizar(grupos: dict, alpha: float = 0.05, unidad: str = "cm"):
    """grupos: {"Control": [valores por tubo], "Mutante": [...]}"""
    names = [str(k).strip() for k in grupos.keys()]
    data = [np.asarray([float(v) for v in vals], dtype=float) for vals in grupos.values()]

    if len(data) < 2:
        raise ValueError("Se necesitan al menos 2 grupos para comparar.")
    for nm, g in zip(names, data):
        if len(g) < 3:
            raise ValueError(f"El grupo '{nm}' tiene {len(g)} valores; se necesitan al menos 3 tubos por grupo.")

    k = len(data)
    razonamiento = []
    advertencias = []

    descriptivos = {nm: _descriptivos(g) for nm, g in zip(names, data)}
    for nm, g in zip(names, data):
        at = _atipicos(g)
        if at:
            advertencias.append(f"Posibles valores atípicos en '{nm}' (criterio 1.5×RIC): {', '.join(f'{v:.2f}' for v in at)}. Revisa esos tubos antes de excluir nada.")

    # --- Supuestos ---
    shapiro = {nm: _shapiro(g) for nm, g in zip(names, data)}
    normal = all(p is not None and p > ALPHA_SUPUESTOS for p in shapiro.values())
    no_normales = [nm for nm, p in shapiro.items() if p is not None and p <= ALPHA_SUPUESTOS]
    if normal:
        razonamiento.append("Normalidad (Shapiro-Wilk): ningún grupo se aparta significativamente de la normal (todos p > 0.05).")
    else:
        razonamiento.append(f"Normalidad (Shapiro-Wilk): se rechaza en {', '.join(no_normales)} (p ≤ 0.05).")

    if all(np.ptp(g) == 0 for g in data):
        raise ValueError("Todos los valores son idénticos dentro de cada grupo; no hay variación que analizar.")
    lev_p = float(stats.levene(*data, center="median").pvalue)
    homog = lev_p > ALPHA_SUPUESTOS
    razonamiento.append(
        f"Homogeneidad de varianzas (Brown-Forsythe): {'se cumple' if homog else 'no se cumple'} ({_fmt_p(lev_p)})."
    )

    if min(len(g) for g in data) < 15:
        advertencias.append("Con menos de 15 tubos por grupo, Shapiro-Wilk tiene poca potencia: puede no detectar desviaciones moderadas de la normalidad. Si la distribución se ve asimétrica en la gráfica, considera la alternativa no paramétrica.")

    posthoc = None
    # --- Selección de prueba ---
    if k == 2:
        a, b = data
        if normal and homog:
            prueba = "t de Student (muestras independientes)"
            r = stats.ttest_ind(a, b, equal_var=True)
            razonamiento.append("Se eligió t de Student: 2 grupos independientes, datos normales y varianzas homogéneas.")
            estad = f"t({len(a)+len(b)-2}) = {r.statistic:.3f}"
        elif normal:
            prueba = "t de Welch"
            r = stats.ttest_ind(a, b, equal_var=False)
            razonamiento.append("Se eligió t de Welch: datos normales pero varianzas distintas; Welch no asume varianzas iguales.")
            estad = f"t = {r.statistic:.3f}"
        else:
            prueba = "U de Mann-Whitney"
            r = stats.mannwhitneyu(a, b, alternative="two-sided")
            razonamiento.append("Se eligió U de Mann-Whitney: al menos un grupo no es normal; la prueba compara distribuciones por rangos.")
            estad = f"U = {r.statistic:.1f}"
        p = float(r.pvalue)
        if prueba.startswith("U"):
            rbc = 1 - 2 * r.statistic / (len(a) * len(b))
            efecto = {"nombre": "correlación biserial de rangos (r)", "valor": float(rbc)}
        else:
            sp = math.sqrt(((len(a)-1)*np.var(a, ddof=1) + (len(b)-1)*np.var(b, ddof=1)) / (len(a)+len(b)-2))
            d = (np.mean(a) - np.mean(b)) / sp if sp > 0 else 0.0
            g = d * (1 - 3 / (4 * (len(a)+len(b)) - 9))
            efecto = {"nombre": "g de Hedges", "valor": float(g)}
    else:
        if normal and homog:
            prueba = "ANOVA de una vía"
            r = stats.f_oneway(*data)
            N = sum(len(g) for g in data)
            estad = f"F({k-1}, {N-k}) = {r.statistic:.3f}"
            p = float(r.pvalue)
            gm = np.mean(np.concatenate(data))
            ssb = sum(len(g) * (np.mean(g) - gm) ** 2 for g in data)
            sst = ((np.concatenate(data) - gm) ** 2).sum()
            efecto = {"nombre": "eta² (η²)", "valor": float(ssb / sst) if sst > 0 else 0.0}
            razonamiento.append(f"Se eligió ANOVA de una vía: {k} grupos, datos normales y varianzas homogéneas.")
            post_nombre, post_fn = "Tukey HSD", _tukey
        elif normal:
            prueba = "ANOVA de Welch"
            f, df1, df2, p = _welch_anova(data)
            estad = f"F({df1}, {df2:.1f}) = {f:.3f}"
            efecto = None
            razonamiento.append("Se eligió ANOVA de Welch: datos normales pero varianzas distintas.")
            post_nombre, post_fn = "Games-Howell", _games_howell
        else:
            prueba = "Kruskal-Wallis"
            r = stats.kruskal(*data)
            N = sum(len(g) for g in data)
            estad = f"H({k-1}) = {r.statistic:.3f}"
            p = float(r.pvalue)
            efecto = {"nombre": "épsilon² (ε²)", "valor": float(r.statistic / ((N ** 2 - 1) / (N + 1)))}
            razonamiento.append("Se eligió Kruskal-Wallis: al menos un grupo no es normal; alternativa no paramétrica al ANOVA.")
            post_nombre, post_fn = "Dunn con corrección de Holm", _dunn
        if p < alpha:
            posthoc = {"prueba": post_nombre, "comparaciones": post_fn(data, names)}
            razonamiento.append(f"Como la prueba global es significativa, se aplicó la prueba post hoc de {post_nombre} para identificar qué pares difieren.")
        else:
            razonamiento.append("La prueba global no es significativa, por lo que no se realizan comparaciones post hoc.")

    signif = p < alpha
    conclusion = (
        f"{prueba}: {estad}, {_fmt_p(p)}. "
        + ("Hay diferencias estadísticamente significativas entre los grupos" if signif
           else "No se detectaron diferencias estadísticamente significativas entre los grupos")
        + f" (α = {alpha})."
    )
    if efecto:
        conclusion += f" Tamaño del efecto: {efecto['nombre']} = {efecto['valor']:.2f}."
    if posthoc:
        sig_pairs = [c["comparacion"] for c in posthoc["comparaciones"] if c["p_ajustada"] < alpha]
        conclusion += (" Pares que difieren: " + "; ".join(sig_pairs) + ".") if sig_pairs else " Ningún par individual alcanzó significancia tras el ajuste."

    return {
        "grupos": names,
        "valores": {nm: [float(v) for v in g] for nm, g in zip(names, data)},
        "descriptivos": descriptivos,
        "supuestos": {"shapiro_p": shapiro, "normalidad": normal, "levene_p": lev_p, "homogeneidad": homog},
        "prueba": prueba,
        "estadistico": estad,
        "p": p,
        "significativo": signif,
        "efecto": efecto,
        "posthoc": posthoc,
        "razonamiento": razonamiento,
        "advertencias": advertencias,
        "conclusion": conclusion,
        "unidad": unidad,
    }
