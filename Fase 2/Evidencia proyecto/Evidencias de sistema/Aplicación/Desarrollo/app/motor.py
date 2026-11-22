# -*- coding: utf-8 -*-
"""
motor.py — Motor del detector de huecos en góndolas (V4.1b), listo para usar fuera del notebook.

El código de detección y de análisis de stock está COPIADO TAL CUAL del notebook detector_huecos_gondolas_V4
(celdas 4.4, 6.2, 6.4a, 6.4b y 6.4c), para que la app web dé exactamente los mismos resultados que el notebook.
No se edita a mano: si cambias la lógica en el notebook, vuelve a generar este archivo.

Uso:
    import motor
    motor.cargar("best.pt", "parametros_v4.json")     # el JSON es opcional (si falta, se usan los valores por defecto)
    r = motor.analizar_imagen(imagen_bgr, "foto.jpg")  # dict con estado, stock, motivos, imagen anotada...
"""
import json, time
from pathlib import Path
import numpy as np
import cv2
from scipy.spatial import cKDTree
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

# ----------------------------------------------------------------------------------------------------------------------
# Parámetros (valores por defecto del notebook, celda 0.2). cargar() los reemplaza con los de parametros_v4.json.
# ----------------------------------------------------------------------------------------------------------------------
IMGSZ_DET   = 1024    # V4: antes 640 al entrenar y 960 al inferir (inconsistente); productos pequeños y densos necesitan resolución
MAX_DET     = 1500    # V4: antes 500 y una foto llegaba exactamente al tope (detecciones truncadas)
IOU_DET     = 0.55    # NMS en inferencia
TILES_N, TILES_SOLAPE, IOU_FUSION = 2, 0.25, 0.55   # rejilla TILES_N x TILES_N con 25 % de solape
TILES_ADAPTATIVO = True     # aunque se elija imagen completa, una foto con productos pequeños (vista lateral/lejana) se repasa con mosaicos
TILES_ALTO_REL   = 0.06     # "pequeños" = alto mediano de caja < 6 % del alto de la foto
IMGSZ_SEG, EPOCHS_SEG, PATIENCE_SEG, BATCH_SEG, FREEZE_SEG = 960, 200, 50, 4, 10
CONF_SEG    = 0.10    # V4.1: antes 0.25 (con 31 fotos el segmentador da confianzas bajas y no quedaba ninguna zona)
UMBRAL_STOCK     = 0.30    # < 30 % de stock => ALERTA_REPONER
MIN_PRODUCTOS    = 12      # con menos productos detectados no se calcula stock por filas...
ESTIMAR_CON_ESTANTES = True   # V4.1: ...salvo que se vean los bordes de repisa: entonces se estima con ellos (una góndola casi vacía
MIN_FILA_ABS     = 3       # V4: una fila necesita >= 3 productos...
MIN_FILA_REL     = 0.15    # ...y >= 15 % de los de la fila mayor (antes 50 %: descartaba justo las filas casi vacías)
K_HUECO          = 1.3     # hueco si el espacio entre productos > K x ancho local del producto
BORDES           = False     # V4.1b: fijado (en fotos laterales reales "estante"/"auto" hundían el stock de góndolas llenas). Cómo contar los faltantes en los EXTREMOS de cada fila:
TEX_RATIO_MAX    = 0.65    # V4: un hueco con textura > 65 % de la de un producto se considera producto no detectado
INFERIR_FILAS_VACIAS = True   # V4: una repisa sin ningún producto deja un salto grande entre filas; se cuenta como fila vacía
RATIO_FILA_VACIA = 1.7    # salto de espaciado > 1.7 veces el normal = posible fila vacía (se confirma con textura: si la franja
FRAC_TEX_FILA    = 0.5     # fracción de muestras de la franja con textura de producto para considerarla "fila no detectada"
TOL_FILA_REL     = 0.30    # tolerancia de la línea de base de una fila, relativa al alto del producto
FILAS_POR_REPISA = True    # V4.1: si se ven los bordes de repisa, las filas se toman de ellos (estructura física) en vez de ajustarlas
N_REFERENCIA     = {}      # opcional. Clave: nombre de foto o prefijo (p. ej. "gondola07_"). Valor: nº de productos con la góndola
NITIDEZ_MIN, SATURADOS_MAX, OSCURIDAD_MIN = 25.0, 0.04, 45.0   # control de calidad: nitidez, mayor mancha quemada (fracción de la foto), brillo medio (ver 6.9a)

# Valores que en el notebook se eligen en las secciones 4.5 y 6.2 (se leen de parametros_v4.json)
CONF_DET = 0.35
CONF_TILES = 0.50
USAR_TILES = False
ZONA_ACTIVA = "detecciones"   # "detecciones" (no necesita otro modelo) | False. La app no usa YOLO-seg.
BEST = None
detector = None
seg = None

# ----------------------------------------------------------------------------------------------------------------------
# Código copiado del notebook
# ----------------------------------------------------------------------------------------------------------------------
def iou_np(a, b):
    # IoU entre cajas xyxy: (n,4) x (m,4) -> (n,m)
    a = np.asarray(a, float).reshape(-1, 4); b = np.asarray(b, float).reshape(-1, 4)
    ix1 = np.maximum(a[:, None, 0], b[None, :, 0]); iy1 = np.maximum(a[:, None, 1], b[None, :, 1])
    ix2 = np.minimum(a[:, None, 2], b[None, :, 2]); iy2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]); ab = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / (aa[:, None] + ab[None, :] - inter + 1e-9)

def nms_np(b, s, thr=0.5):
    # NMS en numpy (no depende de torchvision). Devuelve los índices conservados.
    b = np.asarray(b, float).reshape(-1, 4)
    if len(b) == 0:
        return np.zeros(0, int)
    orden = np.argsort(-np.asarray(s)); area = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1]); keep = []
    while len(orden):
        i = orden[0]; keep.append(i)
        if len(orden) == 1:
            break
        r = orden[1:]
        w = np.clip(np.minimum(b[i, 2], b[r, 2]) - np.maximum(b[i, 0], b[r, 0]), 0, None)
        h = np.clip(np.minimum(b[i, 3], b[r, 3]) - np.maximum(b[i, 1], b[r, 1]), 0, None)
        orden = r[(w * h) / (area[i] + area[r] - w * h + 1e-9) <= thr]
    return np.array(keep, int)

def mascara_pred(r, W, H, s):
    m = np.zeros((max(1, int(H * s)), max(1, int(W * s))), np.uint8)
    if r.masks is not None:
        for poly in r.masks.xy:
            if len(poly) >= 3:
                cv2.fillPoly(m, [(np.asarray(poly) * s).astype(np.int32)], 1)
    return m

def zona_detecciones(b, W, H, s):
    # V4.1: zona de góndola SIN entrenar nada: se dilatan las cajas de producto, se cierran los espacios entre ellas y se rellenan
    # los agujeros (un hueco dentro de la góndola sigue siendo góndola). Se quedan solo las regiones con suficientes productos.
    m = np.zeros((max(1, int(H * s)), max(1, int(W * s))), np.uint8)
    b = np.asarray(b, float).reshape(-1, 4)
    if len(b) < 3:
        return m
    wm, hm = float(np.median(b[:, 2] - b[:, 0])), float(np.median(b[:, 3] - b[:, 1]))
    for x1, y1, x2, y2 in b:
        cv2.rectangle(m, (int((x1 - 0.5 * wm) * s), int((y1 - 0.3 * hm) * s)), (int((x2 + 0.5 * wm) * s), int((y2 + 0.3 * hm) * s)), 1, -1)
    k = max(3, int(1.5 * max(wm, hm) * s)) | 1
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    cx = np.clip(((b[:, 0] + b[:, 2]) / 2 * s).astype(int), 0, m.shape[1] - 1); cy = np.clip(((b[:, 1] + b[:, 3]) / 2 * s).astype(int), 0, m.shape[0] - 1)
    cuenta = np.bincount(lab[cy, cx], minlength=n)
    keep = [i for i in range(1, n) if cuenta[i] >= max(3, 0.10 * len(b))]
    m = np.isin(lab, keep).astype(np.uint8)
    cont, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)       # rellena agujeros
    out = np.zeros_like(m); cv2.drawContours(out, cont, -1, 1, -1)
    return out

def _firma_modelo():
    return f"{BEST}:{int(Path(BEST).stat().st_mtime)}"

USAR_TTA = False     # V4.1: la sección 4.5 decide si se usa

def _pred(img_bgr, conf, tta=False):
    r = detector.predict(img_bgr, conf=conf, iou=IOU_DET, imgsz=IMGSZ_DET, max_det=MAX_DET, augment=bool(tta), verbose=False)[0]
    return r.boxes.xyxy.cpu().numpy().reshape(-1, 4), r.boxes.conf.cpu().numpy().reshape(-1)

def _rejilla(w, h, n=2, solape=0.25):
    tw, th = w / (n - (n - 1) * solape), h / (n - (n - 1) * solape)
    xs, ys = np.linspace(0, w - tw, n), np.linspace(0, h - th, n)
    return [(int(x), int(y), int(min(w, x + tw)), int(min(h, y + th))) for y in ys for x in xs]

def detectar(img_bgr, conf, tiles=False):
    # Devuelve (cajas xyxy, confianzas) en coordenadas de la imagen original
    B, S = _pred(img_bgr, conf, USAR_TTA and not tiles)       # V4.1: TTA solo en imagen completa
    if not tiles:
        return B, S
    h, w = img_bgr.shape[:2]; todas, scs = [B], [S]; m = 3
    for x0, y0, x1, y1 in _rejilla(w, h, TILES_N, TILES_SOLAPE):
        b, s = _pred(img_bgr[y0:y1, x0:x1], conf)
        if len(b) == 0:
            continue
        corta = (((b[:, 0] <= m) & (x0 > 0)) | ((b[:, 1] <= m) & (y0 > 0)) |
                 ((b[:, 2] >= (x1 - x0) - m) & (x1 < w)) | ((b[:, 3] >= (y1 - y0) - m) & (y1 < h)))
        b, s = b[~corta], s[~corta]
        todas.append(b + np.array([x0, y0, x0, y0])); scs.append(s)
    B, S = np.vstack(todas), np.concatenate(scs)
    keep = nms_np(B, S, IOU_FUSION)
    return B[keep], S[keep]

# 6.4a Calidad de imagen, filtros y filas con líneas inclinadas (RANSAC)

PALETA = [(230, 25, 75), (60, 180, 75), (0, 130, 200), (245, 130, 48), (145, 30, 180),
          (70, 200, 200), (240, 50, 230), (160, 190, 40)]          # RGB

def calidad_img(im):
    # V4: control de calidad. Una foto borrosa, quemada por un destello o muy oscura no debe dar un "OK" silencioso.
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    s = 640 / max(g.shape)
    g2 = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else g
    nit = float(cv2.Laplacian(g2, cv2.CV_64F).var()); osc = float(g.mean())
    # Un destello es UNA mancha quemada grande; los envases blancos dan muchos puntos saturados pequeños y no deben contar.
    q = cv2.resize(g2, None, fx=320 / g2.shape[1], fy=320 / g2.shape[1], interpolation=cv2.INTER_AREA) if g2.shape[1] > 320 else g2
    nlab, _, st, _ = cv2.connectedComponentsWithStats((q > 250).astype(np.uint8), connectivity=8)
    sat = float(st[1:, cv2.CC_STAT_AREA].max() / q.size) if nlab > 1 else 0.0
    m = []
    if nit < NITIDEZ_MIN:    m.append(f"imagen borrosa (nitidez={nit:.0f})")
    if sat > SATURADOS_MAX:  m.append(f"destello o sobreexposición (mancha quemada del {sat * 100:.1f}% de la foto)")
    if osc < OSCURIDAD_MIN:  m.append(f"imagen muy oscura (brillo medio={osc:.0f})")
    return m, dict(nitidez=round(nit, 1), saturados=round(sat, 4), brillo=round(osc, 1))

def indices_sin_aislados(b, eps=3.0, rel=0.2):
    # Une cajas cercanas (distancia en tamaños de producto) y conserva solo los grupos grandes. Usa un árbol espacial:
    # V3 construía una matriz n×n que crece de forma cuadrática con las detecciones.
    n = len(b)
    if n < 6:
        return np.arange(n)
    ancho = max(float(np.median(b[:, 2] - b[:, 0])), 1.0); alto = max(float(np.median(b[:, 3] - b[:, 1])), 1.0)
    c = np.c_[(b[:, 0] + b[:, 2]) / 2 / ancho, (b[:, 1] + b[:, 3]) / 2 / alto]
    pares = cKDTree(c).query_pairs(eps, output_type="ndarray")
    if len(pares) == 0:
        return np.arange(n)
    A = coo_matrix((np.ones(len(pares)), (pares[:, 0], pares[:, 1])), shape=(n, n))
    _, lab = connected_components(A, directed=False)
    tam = np.bincount(lab)
    return np.where(np.isin(lab, np.where(tam >= rel * tam.max())[0]))[0]

def filas_ransac(b, iters=300, max_filas=16, min_pts=3, max_pend=0.8, seed=0):
    # V4: ajusta líneas y = m·x + c a las bases (centro-x, y2) de los productos, una fila a la vez (la de más puntos primero).
    # Cada fila tiene su propia pendiente, así que funciona con perspectiva lateral, donde las repisas convergen.
    n = len(b); cx = (b[:, 0] + b[:, 2]) / 2; y2 = b[:, 3]; h = np.maximum(b[:, 3] - b[:, 1], 1.0)
    tol = np.maximum(TOL_FILA_REL * h, 2.0); min_dx = 3 * float(np.median(b[:, 2] - b[:, 0]))
    fila = -np.ones(n, int); libres = np.arange(n); lineas = []; rng = np.random.default_rng(seed)
    while len(libres) >= min_pts and len(lineas) < max_filas:
        mejor = None
        for _ in range(iters):
            i, j = rng.choice(libres, 2, replace=False)
            dx = cx[j] - cx[i]
            if abs(dx) < min_dx:
                continue
            m = (y2[j] - y2[i]) / dx
            if abs(m) > max_pend:
                continue
            c = y2[i] - m * cx[i]
            cuenta = int((np.abs(y2[libres] - (m * cx[libres] + c)) < tol[libres]).sum())
            if mejor is None or cuenta > mejor[0]:
                mejor = (cuenta, m, c)
        if mejor is None or mejor[0] < min_pts:
            break
        _, m, c = mejor
        for _ in range(3):                                   # refinamiento por mínimos cuadrados
            inl = np.abs(y2[libres] - (m * cx[libres] + c)) < tol[libres]
            if inl.sum() >= 3 and np.ptp(cx[libres][inl]) > 1:
                m, c = np.polyfit(cx[libres][inl], y2[libres][inl], 1)
        inl = np.abs(y2[libres] - (m * cx[libres] + c)) < tol[libres]
        if inl.sum() < min_pts:
            break
        fila[libres[inl]] = len(lineas); lineas.append((float(m), float(c)))
        libres = libres[~inl]
    return fila, lineas

def _textura(g, x1, y1, x2, y2):
    # Gradiente medio normalizado de un recorte (a 32×32 para ser independiente de la escala): liso ≈ 0, producto ≫ 0
    x1, y1 = int(max(0, x1)), int(max(0, y1)); x2, y2 = int(min(g.shape[1], x2)), int(min(g.shape[0], y2))
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None
    mx, my = int((x2 - x1) * 0.10), int((y2 - y1) * 0.10)           # se descarta un margen: ahí caen los bordes de los vecinos
    if x2 - x1 - 2 * mx >= 4 and y2 - y1 - 2 * my >= 4:
        x1, x2, y1, y2 = x1 + mx, x2 - mx, y1 + my, y2 - my
    c = cv2.resize(g[y1:y2, x1:x2], (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    gx = cv2.Sobel(c, cv2.CV_32F, 1, 0, ksize=3)[1:-1, 1:-1]; gy = cv2.Sobel(c, cv2.CV_32F, 0, 1, ksize=3)[1:-1, 1:-1]   # sin el borde del propio Sobel
    # V4.1: se normaliza por la raíz del brillo (antes por el brillo): un reflejo SUMA luz y bajaba la textura relativa de los productos que
    # cubría hasta parecer huecos; la raíz mantiene la tolerancia a sombras (que multiplican) sin ese efecto
    return float(np.hypot(gx, gy).mean() / np.sqrt(c.mean() + 10.0))

def _quemado(g, x1, y1, x2, y2):
    # V4.1: fracción de píxeles saturados de un recorte. Un reflejo o destello borra la textura y parece una repisa vacía: un "hueco"
    # mayoritariamente quemado no se cuenta (queda como dudoso) para no dar falsas alarmas por la luz.
    x1, y1 = int(max(0, x1)), int(max(0, y1)); x2, y2 = int(min(g.shape[1], x2)), int(min(g.shape[0], y2))
    return float((g[y1:y2, x1:x2] > 240).mean()) if x2 > x1 and y2 > y1 else 0.0

def _gradiente_horizontal(g, ancho_max=1600):
    # V4.1: |∂I/∂y| suavizado: los bordes de repisa (y las tiras de precios) son líneas horizontales largas con gradiente vertical alto
    esc = min(1.0, ancho_max / g.shape[1])
    q = cv2.resize(g, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA) if esc < 1 else g
    q = cv2.GaussianBlur(q, (5, 5), 0).astype(np.float32)
    return np.abs(cv2.Sobel(q, cv2.CV_32F, 0, 1, ksize=3)), esc

def _extension_estante(gy, esc, m, c, x_lo, x_hi, alto_f, ancho_f):
    # V4.1: extensión física de la repisa de una fila. Bajo la línea de base de los productos se busca, columna a columna, el borde
    # horizontal más fuerte (el frente de la repisa). Ese borde sigue ahí aunque los productos falten, así que se extiende hacia los
    # lados mientras continúe (tolerando cortes de hasta un producto de ancho: etiquetas, reflejos) y se detiene donde la repisa termina.
    Hs, Ws = gy.shape
    xs = np.arange(Ws); yb = (m * (xs / esc) + c) * esc
    off = np.arange(int(-0.10 * alto_f * esc), int(0.60 * alto_f * esc) + 1)
    if len(off) < 2:
        return x_lo, x_hi
    Y = np.clip((yb[:, None] + off[None, :]).astype(int), 0, Hs - 1)
    prof = gy[Y, xs[:, None]].max(1)
    win = max(3, int(0.5 * ancho_f * esc)); prof = np.convolve(prof, np.ones(win) / win, mode="same")
    a, z = int(max(0, x_lo * esc)), int(min(Ws - 1, x_hi * esc))
    if z - a < 3:
        return x_lo, x_hi
    ref = float(np.median(prof[a:z + 1]))
    if ref <= 1e-6:
        return x_lo, x_hi
    thr, corte = 0.4 * ref, max(2, int(1.0 * ancho_f * esc))
    def avanzar(ini, paso):
        ult, falta, x = ini, 0, ini
        while 0 <= x + paso < Ws:
            x += paso
            if prof[x] >= thr:
                ult, falta = x, 0
            else:
                falta += 1
                if falta > corte:
                    break
        return ult
    return min(x_lo, avanzar(a, -1) / esc), max(x_hi, avanzar(z, +1) / esc)

def _bordes_repisa(g, ancho_min_rel=0.30, tramo_min_rel=0.12):
    # V4.1: líneas largas casi horizontales (frentes de repisa) con Hough. Devuelve [(m, c, x1, x2)] en coordenadas de la imagen.
    esc = min(1.0, 1000 / g.shape[1]); q = cv2.resize(g, None, fx=esc, fy=esc, interpolation=cv2.INTER_AREA) if esc < 1 else g
    e = cv2.Canny(cv2.GaussianBlur(q, (5, 5), 0), 40, 120)
    # tramos cortos (los productos y etiquetas cortan el canto de la repisa); luego se unen y se exige el largo total
    L = cv2.HoughLinesP(e, 1, np.pi / 360, threshold=40, minLineLength=int(tramo_min_rel * q.shape[1]), maxLineGap=max(5, int(0.04 * q.shape[1])))
    if L is None:
        return []
    segs = []
    for x1, y1, x2, y2 in np.asarray(L).reshape(-1, 4):
        if x2 == x1:
            continue
        m = (y2 - y1) / (x2 - x1)
        if abs(m) <= 0.8:
            segs.append((m, y1 - m * x1, min(x1, x2), max(x1, x2)))
    xc = q.shape[1] / 2; segs.sort(key=lambda s_: s_[0] * xc + s_[1]); grupos = []
    for s_ in segs:                                       # los dos cantos de una misma repisa se funden en una línea
        y = s_[0] * xc + s_[1]
        if grupos and abs(y - grupos[-1][0]) < 0.05 * q.shape[0]:
            grupos[-1][1].append(s_)
        else:
            grupos.append([y, [s_]])
    out = []
    for _, gr in grupos:
        gr = np.array(gr)
        if gr[:, 3].max() - gr[:, 2].min() < ancho_min_rel * q.shape[1]:
            continue
        L_ = gr[:, 3] - gr[:, 2]
        def _wmed(v, w):                                                      # mediana ponderada por el largo del tramo (robusta)
            o = np.argsort(v); cw = np.cumsum(w[o]); return float(v[o][np.searchsorted(cw, 0.5 * cw[-1])])
        m = _wmed(gr[:, 0], L_)
        c = _wmed((gr[:, 0] * (gr[:, 2] + gr[:, 3]) / 2 + gr[:, 1]) - m * (gr[:, 2] + gr[:, 3]) / 2, L_)   # altura en el centro de cada tramo
        out.append((m, c / esc, float(gr[:, 2].min() / esc), float(gr[:, 3].max() / esc)))
    return out

def repisas_validas(lineas, b, W):
    # V4.1: de las líneas largas, quedan solo las que pueden ser repisas: (a) no atraviesan productos (los cantos superior e inferior de
    # una fila de envases también forman líneas largas) y (b) su inclinación es coherente con la perspectiva del resto (en una góndola
    # plana la pendiente varía linealmente con la altura; se ajusta una recta robusta y se descartan las que se desvían).
    if not lineas or len(b) == 0:
        return lineas
    cx = (b[:, 0] + b[:, 2]) / 2; h = np.maximum(b[:, 3] - b[:, 1], 1.0); out = []
    for m, c, x1, x2 in lineas:
        yl = m * cx + c; enx = (cx >= x1) & (cx <= x2)
        cruza = enx & (yl > b[:, 1] + 0.15 * h) & (yl < b[:, 3] - 0.3 * h)            # pasa por dentro de los envases
        techo = enx & (np.abs(yl - b[:, 1]) <= 0.15 * h)                               # es el canto superior de una fila de envases
        if cruza.sum() < 2 and techo.sum() < 3:
            out.append((m, c, x1, x2))
    if len(out) >= 3:
        yc = np.array([m * W / 2 + c for m, c, _, _ in out]); ms = np.array([l[0] for l in out])
        pend = [(ms[j] - ms[i]) / (yc[j] - yc[i]) for i in range(len(out)) for j in range(i + 1, len(out)) if abs(yc[j] - yc[i]) > 1]
        beta = float(np.median(pend)) if pend else 0.0; alfa = float(np.median(ms - beta * yc))
        out = [l for l, y_, m_ in zip(out, yc, ms) if abs(m_ - (alfa + beta * y_)) <= 0.05]
    return sorted(out, key=lambda l: l[0] * W / 2 + l[1])

def filas_por_repisa(lineas_rep, b, tol_rel=0.35):
    # V4.1: asigna cada producto a la repisa sobre la que se apoya (su base cerca de la línea). Devuelve (fila, lineas) como
    # filas_ransac, o None si las repisas no explican la mayoría de los productos (fotos sin bordes visibles).
    if len(lineas_rep) < 1 or len(b) == 0:
        return None
    cx = (b[:, 0] + b[:, 2]) / 2; y2 = b[:, 3]; h = np.maximum(b[:, 3] - b[:, 1], 1.0)
    D = np.stack([np.abs(y2 - (m * cx + c)) for m, c, _, _ in lineas_rep], 1)       # (productos, repisas)
    j = D.argmin(1); ok = D[np.arange(len(b)), j] < tol_rel * h
    if ok.mean() < 0.5:
        return None
    fila = -np.ones(len(b), int); lineas = []; offs = []
    for k_, jj in enumerate(sorted(set(j[ok]))):
        sel = ok & (j == jj); fila[sel] = k_
        m, c, _, _ = lineas_rep[jj]
        off = float(np.median(y2[sel] - (m * cx[sel] + c))); offs.append(off)
        lineas.append((float(m), float(c + off)))                                     # la línea pasa por las bases, no por el canto
    off_med = float(np.median(offs)) if offs else 0.0
    usadas = set(j[ok])
    sin_uso = [(m, c + off_med, x1, x2) for i_, (m, c, x1, x2) in enumerate(lineas_rep) if i_ not in usadas]   # repisas sin productos
    return fila, lineas, sin_uso

# 6.4b Huecos, filas vacías y stock
def _stock_por_estantes(im, b, r):
    # V4.1: góndola con muy pocos productos. Se recorre cada repisa visible a pasos de un producto y cada posición se clasifica en:
    # ocupada (hay una caja detectada), vacía (superficie lisa) o "con textura" (producto que el detector no vio: no se cuenta).
    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY); H, W = g.shape
    w_m, h_m = float(np.median(b[:, 2] - b[:, 0])), float(np.median(b[:, 3] - b[:, 1]))
    lineas = repisas_validas(_bordes_repisa(g), b, W)
    if len(lineas) < 2:
        return None
    cx = (b[:, 0] + b[:, 2]) / 2
    sobre = np.array([np.abs(b[:, 3] - (m * cx + c)) < 0.5 * h_m for m, c, _, _ in lineas])     # (repisas, productos)
    if sobre.any(0).mean() < 0.6:                            # los productos deben apoyarse en esas líneas (si no, no son repisas)
        return None
    # Se conservan las repisas con productos y las vecinas con un espaciado coherente (otras líneas largas pueden ser piso o techo)
    ys = np.array([m * W / 2 + c for m, c, _, _ in lineas]); sop = np.where(sobre.any(1))[0]
    paso_y = float(np.median(np.diff(ys))) if len(ys) > 1 else h_m
    ini, fin = sop.min(), sop.max()
    while ini > 0 and ys[ini] - ys[ini - 1] <= 1.6 * paso_y: ini -= 1
    while fin < len(ys) - 1 and ys[fin + 1] - ys[fin] <= 1.6 * paso_y: fin += 1
    m_ref = float(np.median([lineas[i][0] for i in sop]))
    # desfase entre el canto detectado y la base real de los productos (la franja a revisar va SOBRE la repisa, no sobre su canto)
    off = float(np.median(np.concatenate([b[sobre[i], 3] - (lineas[i][0] * cx[sobre[i]] + lineas[i][1]) for i in sop])))
    lineas = [(m, c + off, x1, x2) for i, (m, c, x1, x2) in enumerate(lineas) if ini <= i <= fin and abs(m - m_ref) < 0.15]
    if len(lineas) < 2:
        return None
    tp = [t_ for t_ in (_textura(g, *bb) for bb in b) if t_ is not None]
    T = float(np.median(tp)) if tp else 0.0
    paso = 1.1 * w_m; vacias = ocupadas = textura = 0; r["virtuales"] = []
    for m, c, x1, x2 in lineas:
        n_v = 0
        for x in np.arange(x1 + paso / 2, x2 - paso / 2 + 1e-6, paso):
            yb = m * x + c
            if np.any((b[:, 0] <= x) & (b[:, 2] >= x) & (np.abs(b[:, 3] - yb) < 0.6 * h_m)):
                ocupadas += 1; continue
            tx = _textura(g, x - w_m / 2, yb - h_m, x + w_m / 2, yb)
            if (tx is not None and T > 0 and tx / T > TEX_RATIO_MAX) or _quemado(g, x - w_m / 2, yb - h_m, x + w_m / 2, yb) > 0.3:
                textura += 1
            else:
                vacias += 1; n_v += 1
        r["virtuales"].append(dict(y=float(m * W / 2 + c), x1=float(x1), x2=float(x2), linea=(float(m), float(c)), unidades=float(n_v)))
    N = len(b)
    if N + vacias == 0:
        return None
    r.update(analisis="ok", motivo="", b=b, s=np.ones(len(b)), fila=np.zeros(len(b), int), stock=float(N / (N + vacias)), n_prod=int(N),
             unidades_faltantes=float(vacias))
    r["avisos"].append(f"pocos productos: stock estimado con {len(lineas)} bordes de repisa visibles")
    if textura > 0.3 * max(textura + vacias + ocupadas, 1):
        r["avisos"].append(f"{textura} posiciones con textura de producto sin detectar: detección incompleta")
    return r

def analizar_cajas(im, b, s=None, n_ref=None, seed=0):
    r = dict(analisis="ok", motivo="", b=np.zeros((0, 4)), s=np.zeros(0), fila=np.zeros(0, int), filas=[], huecos=[], dudosos=[],
             virtuales=[], no_detectadas=[], avisos=[], stock=float("nan"), n_prod=0, unidades_faltantes=0.0)
    b = np.asarray(b, float).reshape(-1, 4); s = np.ones(len(b)) if s is None else np.asarray(s, float).reshape(-1)
    def pocos(n, bb=None):
        if ESTIMAR_CON_ESTANTES and bb is not None and len(bb) >= 3:
            est = _stock_por_estantes(im, bb, r)
            if est is not None:
                return est
        r.update(analisis="pocos_productos", motivo=f"solo {n} productos utilizables (¿góndola casi vacía o foto sin góndola?)"); return r
    if len(b) < MIN_PRODUCTOS:
        return pocos(len(b), b)
    a = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1]); med = float(np.median(a))
    k = (a > 0.1 * med) & (a < 10 * med); b, s = b[k], s[k]          # tamaños absurdos (V3 usaba 0.4–2.5×: borraba productos legítimos con perspectiva)
    b_todas = b.copy()
    k = indices_sin_aislados(b); b, s = b[k], s[k]
    if len(b) < MIN_PRODUCTOS:
        return pocos(len(b), b_todas)

    g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    por_repisa = None
    repisas_vacias = []
    if FILAS_POR_REPISA:
        lineas_rep = repisas_validas(_bordes_repisa(g), b, im.shape[1])
        por_repisa = filas_por_repisa(lineas_rep, b)
    if por_repisa is not None:
        fila, lineas, repisas_vacias = por_repisa; min_fila = 1          # la repisa ya prueba que la fila existe: basta 1 producto
        libres = np.where(fila < 0)[0]                   # productos sobre repisas que Hough no vio: se ajustan como antes
        if len(libres) >= MIN_FILA_ABS:
            f2, l2 = filas_ransac(b[libres], seed=seed)
            for k_ in range(len(l2)):
                if (f2 == k_).sum() >= MIN_FILA_ABS:
                    fila[libres[f2 == k_]] = len(lineas); lineas.append(l2[k_])
    else:
        fila, lineas = filas_ransac(b, seed=seed); min_fila = MIN_FILA_ABS
    r["filas_por"] = "repisas" if por_repisa is not None else "ajuste"
    cuentas = np.bincount(fila[fila >= 0], minlength=len(lineas)) if len(lineas) else np.zeros(0, int)
    if len(cuentas) == 0:
        return pocos(0)
    # V4: una fila casi vacía NO se descarta (V3 exigía 50 % de la fila mayor y borraba justo lo que hay que detectar)
    validas = [i for i in range(len(lineas)) if cuentas[i] >= (min_fila if por_repisa is not None else max(MIN_FILA_ABS, MIN_FILA_REL * cuentas.max()))]
    # filtro de tamaño local dentro de cada fila
    for i in validas:
        ii = np.where(fila == i)[0]; w = b[ii, 2] - b[ii, 0]; mw = np.median(w)
        fila[ii[(w > 3 * mw) | (w < 0.25 * mw)]] = -1
    validas = [i for i in validas if (fila == i).sum() >= min_fila]
    if not validas:
        return pocos(int((fila >= 0).sum()))
    xmid = (b[fila >= 0, 0].min() + b[fila >= 0, 2].max()) / 2
    orden = sorted(validas, key=lambda i: lineas[i][0] * xmid + lineas[i][1])
    nuevo = -np.ones(len(b), int)
    for rid, i in enumerate(orden):
        nuevo[fila == i] = rid
    keep = nuevo >= 0; sueltos = b[~keep]; b, s, nuevo = b[keep], s[keep], nuevo[keep]   # V4.1: los sueltos se usan en las filas casi vacías
    lineas_ord = [lineas[i] for i in orden]

    rng = np.random.default_rng(seed)
    muestra = rng.choice(len(b), min(150, len(b)), replace=False)
    tp = [t for t in (_textura(g, *b[i]) for i in muestra) if t is not None]
    T = float(np.median(tp)) if tp else 0.0
    x_ini, x_fin = float(b[:, 0].min()), float(b[:, 2].max())
    alto_med = float(np.median(b[:, 3] - b[:, 1]))
    ext = None
    if BORDES == "auto":
        # Extensión esperada de cada fila = la que muestran las filas más llenas, ajustada con la perspectiva (recta x(y) robusta)
        cn = np.bincount(nuevo, minlength=len(orden)); sanas = [i for i in range(len(orden)) if cn[i] >= max(MIN_FILA_ABS, 0.6 * cn.max())]
        ys_ = np.array([lineas_ord[i][0] * xmid + lineas_ord[i][1] for i in sanas])
        def _recta(x, q):
            pend = 0.0
            if len(ys_) >= 2 and np.ptp(ys_) > 1:
                pr = [(x[j] - x[i]) / (ys_[j] - ys_[i]) for i in range(len(ys_)) for j in range(i + 1, len(ys_)) if abs(ys_[j] - ys_[i]) > 1]
                pend = float(np.median(pr)) if pr else 0.0
            inter = float(np.percentile(x - pend * ys_, q))
            return lambda yy: pend * yy + inter
        xl_f = _recta(np.array([b[nuevo == i, 0].min() for i in sanas]), 25); xr_f = _recta(np.array([b[nuevo == i, 2].max() for i in sanas]), 75)
        ext = (xl_f, xr_f)
    elif BORDES == "estante":
        gyp, esc_g = _gradiente_horizontal(g)
    for rid in range(len(orden)):
        ii = np.where(nuevo == rid)[0]; ii = ii[np.argsort((b[ii, 0] + b[ii, 2]) / 2)]
        rr = b[ii]; med_w = float(np.median(rr[:, 2] - rr[:, 0])); unidades = 0.0
        m_, c_ = lineas_ord[rid]
        if BORDES == "auto":
            y_fila = m_ * xmid + c_
            xi_, xf_ = max(0.0, ext[0](y_fila)), min(float(im.shape[1]), ext[1](y_fila))
        elif BORDES == "estante":
            xi_, xf_ = _extension_estante(gyp, esc_g, m_, c_, float(rr[0, 0]), float(rr[-1, 2]), float(np.median(rr[:, 3] - rr[:, 1])), med_w)
        else:
            xi_, xf_ = x_ini, x_fin
        con_bordes = BORDES in ("global", "auto", "estante")
        # V4.1: paso real entre productos (ancho + separación) de ESTA fila, en múltiplos del ancho. Antes un espacio se convertía en
        # unidades dividiendo por el ancho del producto, lo que sobrecontaba los faltantes cuando los productos no van pegados.
        wr = rr[:, 2] - rr[:, 0]; cxr = 0.5 * (rr[:, 0] + rr[:, 2])
        q_ = np.diff(cxr) / np.maximum(0.5 * (wr[:-1] + wr[1:]), 1e-6) if len(rr) > 1 else np.zeros(0)
        q_ = q_[(q_ > 0.8) & (q_ < 1.6)]
        factor = float(np.clip(np.median(q_), 1.0, 1.5)) if len(q_) else 1.1
        tramos = [(xi_, rr[0, 0], rr[0], rr[0], True)] if con_bordes else []
        tramos += [(rr[i, 2], rr[i + 1, 0], rr[i], rr[i + 1], False) for i in range(len(rr) - 1)]
        if con_bordes:
            tramos.append((rr[-1, 2], xf_, rr[-1], rr[-1], True))
        for xa, xb, p1, p2, borde in tramos:
            brecha = xb - xa
            ref_w = max(0.5 * ((p1[2] - p1[0]) + (p2[2] - p2[0])), 0.5 * med_w)     # ancho local de los vecinos
            if brecha <= K_HUECO * ref_w:
                continue
            # V4.1: el espacio se revisa por TRAMOS de un producto de ancho. Antes se miraba entero: un espacio largo con una parte vacía
            # y otra con productos no detectados se clasificaba todo junto (y en los extremos, a la altura equivocada si la fila está inclinada).
            paso = factor * ref_w
            k_falt = (brecha - (0.5 if borde else 1.0) * (factor - 1.0) * ref_w) / paso     # productos que caben en el espacio
            if k_falt < 0.5:
                continue
            nch = max(1, int(round(k_falt))); u_ch = k_falt / nch
            for k in range(nch):
                xa_k, xb_k = xa + k * brecha / nch, xa + (k + 1) * brecha / nch; xm = 0.5 * (xa_k + xb_k)
                if borde:                                                   # extremo: altura según la línea de la fila
                    hb = p1[3] - p1[1]; y2k = m_ * xm + c_; y1k = y2k - hb
                else:                                                       # interior: interpolada entre los dos vecinos
                    tq = (xm - xa) / max(brecha, 1e-6)
                    y1k, y2k = p1[1] + tq * (p2[1] - p1[1]), p1[3] + tq * (p2[3] - p1[3])
                tex = _textura(g, xa_k, y1k, xb_k, y2k)
                if T > 0 and tex is not None and tex / T > TEX_RATIO_MAX:
                    r["dudosos"].append((xa_k, y1k, xb_k, y2k, rid, round(tex / T, 2)))   # producto no detectado, no hueco
                elif _quemado(g, xa_k, y1k, xb_k, y2k) > 0.3:
                    r["dudosos"].append((xa_k, y1k, xb_k, y2k, rid, -1.0))                # reflejo: no se puede saber
                else:
                    r["huecos"].append((xa_k, y1k, xb_k, y2k, rid, u_ch)); unidades += u_ch
        r["filas"].append(dict(id=rid, n=len(rr), unidades=unidades, stock=len(rr) / (len(rr) + unidades), y=m_ * xmid + c_, linea=(m_, c_),
                               x1=float(xi_ if con_bordes else rr[0, 0]), x2=float(xf_ if con_bordes else rr[-1, 2]), factor=factor))

    # V4: filas completamente vacías. Puede ser (a) una repisa vacía o (b) una repisa llena que el detector no vio. Se distingue con
    # textura a lo largo de la franja (siguiendo la inclinación de las filas vecinas): solo (a) cuenta como faltante.
    # V4.1: si las filas vienen de las repisas, las candidatas son las repisas visibles SIN productos situadas entre filas (su posición es
    # la real); si no, se infieren por un salto anómalo en el espaciado entre filas, como en V4.
    F = r["filas"]; alto = float(np.median(b[:, 3] - b[:, 1])); anch = float(np.median(b[:, 2] - b[:, 0]))
    fac = float(np.median([f_.get("factor", 1.1) for f_ in F])) if F else 1.1
    candidatas = []                                                   # (m, c, x1, x2, tolerancia vertical para productos sueltos)
    if INFERIR_FILAS_VACIAS and len(F) >= 2 and por_repisa is not None:
        ys_f = np.array([f_["y"] for f_ in F]); x_lo, x_hi = min(f_["x1"] for f_ in F), max(f_["x2"] for f_ in F)
        for m_, c_, x1l, x2l in repisas_vacias:
            y_ = m_ * xmid + c_
            if ys_f.min() + 0.5 * alto < y_ < ys_f.max() - 0.5 * alto and np.abs(ys_f - y_).min() > 0.6 * alto:
                candidatas.append((m_, c_, max(x1l, x_lo), min(x2l, x_hi), 0.4 * alto))
    elif INFERIR_FILAS_VACIAS and len(F) >= 3:
        ys = np.array([f_["y"] for f_ in F]); d = np.diff(ys)
        for i, di in enumerate(d):
            ref = max(float(np.median(np.delete(d, i))), alto)
            if di <= RATIO_FILA_VACIA * ref:
                continue
            nv = max(1, int(round(di / ref)) - 1)
            # V4.1: extensión = unión de las filas vecinas (con BORDES activo, su extensión de repisa). Antes se usaba la intersección de
            # sus productos, que en una góndola agotada quedaba reducida a los pocos productos restantes
            x1v, x2v = min(F[i]["x1"], F[i + 1]["x1"]), max(F[i]["x2"], F[i + 1]["x2"])
            (ma, ca), (mb, cb) = F[i]["linea"], F[i + 1]["linea"]
            for q in range(1, nv + 1):
                tq = q / (nv + 1); candidatas.append((ma + tq * (mb - ma), ca + tq * (cb - ca), x1v, x2v, 0.5 * di / (nv + 1)))
    for m_, c_, x1v, x2v, tol_y in candidatas:
        if x2v - x1v < anch:
            continue
        xs = np.linspace(x1v + anch / 2, x2v - anch / 2, 8)
        rt = [_textura(g, x - anch / 2, m_ * x + c_ - alto, x + anch / 2, m_ * x + c_) for x in xs]
        qm = [_quemado(g, x - anch / 2, m_ * x + c_ - alto, x + anch / 2, m_ * x + c_) > 0.3 for x in xs]
        rt = [(v / T if v is not None and T > 0 else 0.0) for v in rt]
        frac = float(np.mean([(v > TEX_RATIO_MAX) or q_ for v, q_ in zip(rt, qm)])) if rt else 0.0      # textura o reflejo: no medible
        info = dict(y=float(m_ * xmid + c_), x1=float(x1v), x2=float(x2v), linea=(float(m_), float(c_)), frac_textura=round(frac, 2))
        if frac >= FRAC_TEX_FILA:
            r["no_detectadas"].append(info)                           # productos sin detectar: no es faltante
            continue
        # V4.1: una repisa casi vacía (1–2 productos) no forma fila propia; esos productos sueltos se cuentan aquí, así la fila cuenta
        # como "casi vacía" y no se pierden ni sus productos ni sus faltantes del cálculo
        n_in = 0
        if len(sueltos):
            cxs = (sueltos[:, 0] + sueltos[:, 2]) / 2
            n_in = int(((np.abs(sueltos[:, 3] - (m_ * cxs + c_)) < tol_y) & (cxs >= x1v - anch) & (cxs <= x2v + anch)).sum())
        info["n"] = n_in
        info["unidades"] = max(0.0, max(1.0, (x2v - x1v) / (fac * anch)) - n_in); r["virtuales"].append(info)
    if r["no_detectadas"]:
        # V4.1b: es una NOTA, no un aviso: la franja tiene textura de producto (una repisa vacía es lisa), así que no cambia la decisión
        r.setdefault("notas", []).append(f"{len(r['no_detectadas'])} franja(s) con textura de producto sin detectar (no se cuentan como faltante)")
    N = sum(f["n"] for f in r["filas"]) + sum(v.get("n", 0) for v in r["virtuales"])
    U = sum(f["unidades"] for f in r["filas"]) + sum(v["unidades"] for v in r["virtuales"])
    stock = N / (N + U)
    if n_ref:                                                      # opcional: con un nº de referencia (góndola llena) se acota el stock
        stock = min(stock, min(1.0, N / float(n_ref)))
    if r["dudosos"]:
        anch_ = float(np.median(b[:, 2] - b[:, 0])); u_dud = sum((x2 - x1) / anch_ for x1, _, x2, _, _, _ in r["dudosos"])
        if u_dud > 1.0 * N:                                            # V4.1b: antes 0.5 (mandaba a revisión fotos llenas bien medidas)
            r["avisos"].append(f"muchos espacios con textura de producto (~{u_dud:.0f} productos sin detectar): detección incompleta")
    r.update(b=b, s=s, fila=nuevo, stock=float(stock), n_prod=int(N), unidades_faltantes=float(U))
    return r

# 6.4c Evaluación de una foto: calidad + detección + (máscara) + filas/huecos/stock + estado
def region_mascara(im, b=None, escala_max=400):
    H, W = im.shape[:2]; s = escala_max / max(H, W)
    if ZONA_ACTIVA == "detecciones":
        return zona_detecciones(b, W, H, s), s
    return mascara_pred(seg.predict(im, conf=CONF_SEG, imgsz=IMGSZ_SEG, verbose=False)[0], W, H, s), s

def filtrar_region(b, s, masc, esc):
    # Conserva solo los productos dentro de la zona de góndola. Si la máscara descartara más del 60 %, no es fiable: se ignora.
    if masc is None or masc.sum() == 0 or len(b) == 0:
        return b, s, "sin_mascara"
    k = max(3, int(0.03 * max(masc.shape))) | 1
    d = cv2.dilate(masc, np.ones((k, k), np.uint8))
    cx = np.clip(((b[:, 0] + b[:, 2]) / 2 * esc).astype(int), 0, d.shape[1] - 1)
    cy = np.clip(((b[:, 1] + b[:, 3]) / 2 * esc).astype(int), 0, d.shape[0] - 1)
    dentro = d[cy, cx] > 0
    if dentro.mean() < 0.4:
        return b, s, "mascara_descartada"
    return b[dentro], s[dentro], f"mascara_ok({int((~dentro).sum())} fuera)"

def detectar_filtrada(entrada, nombre=None, usar_cache=True):
    # Devuelve (im, b, s, n_det_inicial, nota_mascara)
    if isinstance(entrada, (str, Path)):
        im = cv2.imread(str(entrada))
        if im is None:
            return None, np.zeros((0, 4)), np.zeros(0), 0, "ilegible"
        b, s = detectar_foto(entrada, im) if usar_cache else detectar(im, CONF_DET, USAR_TILES)
    else:
        im = entrada; b, s = detectar(im, CONF_DET, USAR_TILES)
    nota = "sin_filtro"
    if TILES_ADAPTATIVO and not USAR_TILES and len(b) and np.median(b[:, 3] - b[:, 1]) < TILES_ALTO_REL * im.shape[0]:
        # productos pequeños (foto lateral o lejana): se repasa con mosaicos y se usa si encuentra claramente más productos
        clave = (str(entrada), "mosaico", _firma_modelo(), CONF_TILES) if isinstance(entrada, (str, Path)) and usar_cache else None
        if clave is not None and clave in CACHE_DET:
            b2, s2 = CACHE_DET[clave]
        else:
            b2, s2 = detectar(im, CONF_TILES, True)
            if clave is not None:
                CACHE_DET[clave] = (b2, s2)
        if len(b2) >= 1.15 * len(b):
            b, s, nota = b2, s2, "mosaico_adaptativo"
    n0 = len(b)
    if ZONA_ACTIVA:
        masc, esc = region_mascara(im, b); b, s, nota_m = filtrar_region(b, s, masc, esc); nota = f"{nota}|{ZONA_ACTIVA}:{nota_m}"
    return im, b, s, n0, nota

def decidir(an, cal_m):
    if an["analisis"] != "ok":
        return "REVISION_MANUAL", [an["motivo"]] + cal_m
    avisos, notas = an.get("avisos", []), an.get("notas", [])   # V4.1b: las notas se informan pero no cambian el estado
    if an["stock"] < UMBRAL_STOCK:
        return "ALERTA_REPONER", cal_m + avisos + notas  # una alerta se escala aunque la calidad sea dudosa
    if cal_m or avisos:
        return "REVISION_MANUAL", cal_m + avisos + notas
    return "OK", notas

_REF_CACHE = {}
def n_referencia(nombre):
    # V4.1: N_REFERENCIA acepta el nombre exacto o un prefijo, y como valor un número o la ruta de una foto de la góndola llena.
    # Con una foto de referencia, el conteo sale del MISMO detector: su recall limitado afecta igual a ambas fotos y se cancela.
    v = N_REFERENCIA.get(nombre)
    if v is None:
        pref = [k for k in N_REFERENCIA if str(nombre).startswith(str(k))]
        v = N_REFERENCIA[max(pref, key=len)] if pref else None
    if v is None or isinstance(v, (int, float)):
        return v
    clave = str(v)
    if clave not in _REF_CACHE:
        im_r, b_r, s_r, _, _ = detectar_filtrada(Path(v))
        if im_r is None:
            print(f"⚠️ No se pudo leer la foto de referencia {v}"); _REF_CACHE[clave] = None
        else:
            _REF_CACHE[clave] = analizar_cajas(im_r, b_r, s_r)["n_prod"] or None
    return _REF_CACHE[clave]

REPASO_MOSAICO_N = 0   # V4.1b: repaso con rejilla N×N cuando la detección quedó incompleta. 0 = desactivado: en tus fotos reales el repaso
                       # 3×3 añadía detecciones pero BAJABA el stock de góndolas llenas (más huecos falsos entre productos lejanos)

def _sin_medir(an):
    # unidades (en anchos de producto) que no se pudieron medir: espacios con textura de producto + franjas sin detectar
    if an["analisis"] != "ok" or not len(an["b"]):
        return 0.0
    w = float(np.median(an["b"][:, 2] - an["b"][:, 0]))
    return (sum((x2 - x1) / w for x1, _, x2, _, _, _ in an["dudosos"]) +
            sum((v["x2"] - v["x1"]) / w for v in an.get("no_detectadas", [])))

def evaluar_foto(entrada, nombre=None, usar_cache=True):
    global TILES_N
    t0 = time.time()
    nombre = nombre or (Path(entrada).name if isinstance(entrada, (str, Path)) else "imagen")
    im, b, s, n0, nota = detectar_filtrada(entrada, nombre, usar_cache)
    if im is None:
        return dict(foto=nombre, estado="REVISION_MANUAL", motivos=["no se pudo leer la imagen"], stock=float("nan"), n_det=0,
                    n_prod=0, filas=0, huecos=0, filas_bajas=[], mascara=nota, nitidez=np.nan, saturados=np.nan, brillo=np.nan, tiempo=0.0,
                    an=analizar_cajas(np.zeros((8, 8, 3), np.uint8), np.zeros((0, 4))), im=None)
    cal_m, cal = calidad_img(im)
    an = analizar_cajas(im, b, s, n_referencia(nombre))
    # V4.1b: si quedó mucho sin medir (el detector no vio los productos lejanos), se repasa la foto con una rejilla más fina de
    # mosaicos y se usa ese resultado si mide más góndola. Solo se hace en estas fotos: en las demás no cuesta nada.
    if REPASO_MOSAICO_N and an.get("avisos") and _sin_medir(an) > 0.3 * max(an["n_prod"], 1):
        clave = (str(entrada), "repaso", REPASO_MOSAICO_N, _firma_modelo(), CONF_TILES) if isinstance(entrada, (str, Path)) and usar_cache else None
        if clave is not None and clave in CACHE_DET:
            b2, s2 = CACHE_DET[clave]
        else:
            n_ant = TILES_N; TILES_N = REPASO_MOSAICO_N
            try:
                b2, s2 = detectar(im, CONF_TILES, True)
            finally:
                TILES_N = n_ant
            if clave is not None:
                CACHE_DET[clave] = (b2, s2)
        if ZONA_ACTIVA and len(b2):
            masc, esc = region_mascara(im, b2); b2, s2, _ = filtrar_region(b2, s2, masc, esc)
        an2 = analizar_cajas(im, b2, s2, n_referencia(nombre))
        if an2["analisis"] == "ok" and an2["n_prod"] >= an["n_prod"] and _sin_medir(an2) < _sin_medir(an):
            an, n0, nota = an2, len(b2), f"{nota}|repaso_mosaico_{REPASO_MOSAICO_N}x{REPASO_MOSAICO_N}"
    estado, motivos = decidir(an, cal_m)
    bajas = [f["id"] + 1 for f in an["filas"] if f["n"] >= MIN_FILA_ABS and f["stock"] < UMBRAL_STOCK]
    return dict(foto=nombre, estado=estado, motivos=motivos, stock=an["stock"], n_det=n0, n_prod=an["n_prod"],
                filas=len(an["filas"]) + len(an["virtuales"]), huecos=len(an["huecos"]), filas_bajas=bajas, mascara=nota,
                tiempo=round(time.time() - t0, 2), an=an, im=im, **cal)

COLOR_ESTADO = {"OK": (60, 160, 60), "ALERTA_REPONER": (220, 40, 40), "REVISION_MANUAL": (230, 150, 20)}

def dibujar_resultado(res, ancho_max=1000):
    im, an = res["im"], res["an"]
    s = min(1.0, ancho_max / max(im.shape[:2])); v = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else im.copy()
    ov = v.copy()
    for x1, y1, x2, y2, rid, u in an["huecos"]:
        cv2.rectangle(ov, (int(x1 * s), int(y1 * s)), (int(x2 * s), int(y2 * s)), (0, 0, 255), -1)       # huecos: rojo
    v = cv2.addWeighted(ov, 0.45, v, 0.55, 0)
    for (x1, y1, x2, y2), f in zip((an["b"] * s).astype(int), an["fila"]):
        cv2.rectangle(v, (x1, y1), (x2, y2), PALETA[int(f) % len(PALETA)][::-1], 2)
    for x1, y1, x2, y2, rid, rt in an["dudosos"]:                                                      # amarillo: espacio con textura (¿producto no detectado?)
        cv2.rectangle(v, (int(x1 * s), int(y1 * s)), (int(x2 * s), int(y2 * s)), (0, 220, 255), 1)
    for lista, color, txt_, grosor in ((an["virtuales"], (0, 0, 255), "fila vacia", 3), (an.get("no_detectadas", []), (0, 220, 255), "sin detectar", 1)):
        for vr in lista:
            m_, c_ = vr.get("linea", (0.0, vr["y"]))
            p1 = (int(vr["x1"] * s), int((m_ * vr["x1"] + c_) * s)); p2 = (int(vr["x2"] * s), int((m_ * vr["x2"] + c_) * s))
            cv2.line(v, p1, p2, color, grosor)
            cv2.putText(v, txt_, (p1[0] + 6, p1[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    H = v.shape[0]; texto = f"{res['estado']}  stock={res['stock']:.0%}" if res["stock"] == res["stock"] else res["estado"]
    cv2.rectangle(v, (0, 0), (v.shape[1], int(H * 0.06) + 8), COLOR_ESTADO[res["estado"]][::-1], -1)
    cv2.putText(v, texto, (10, int(H * 0.045) + 4), cv2.FONT_HERSHEY_SIMPLEX, max(0.6, v.shape[1] / 1400), (255, 255, 255), 2)
    return v[..., ::-1]


# ----------------------------------------------------------------------------------------------------------------------
# Envoltura para la app (esto no está en el notebook)
# ----------------------------------------------------------------------------------------------------------------------
CACHE_DET = {}

def detectar_foto(ruta, im=None):
    # En la app no se reutilizan detecciones entre fotos: cada imagen se procesa una vez
    return detectar(im if im is not None else cv2.imread(str(ruta)), CONF_DET, USAR_TILES)

_MAPA_JSON = {"conf_det": "CONF_DET", "usar_tiles": "USAR_TILES", "usar_tta": "USAR_TTA", "conf_tiles": "CONF_TILES",
              "tiles_adaptativo": "TILES_ADAPTATIVO", "imgsz_det": "IMGSZ_DET", "iou_det": "IOU_DET", "max_det": "MAX_DET",
              "umbral_stock": "UMBRAL_STOCK", "k_hueco": "K_HUECO", "tex_ratio_max": "TEX_RATIO_MAX",
              "ratio_fila_vacia": "RATIO_FILA_VACIA", "bordes": "BORDES", "zona": "ZONA_ACTIVA", "tiles_adaptativo": "TILES_ADAPTATIVO"}

def cargar(pesos, parametros=None, dispositivo=None):
    """Carga el detector (best.pt) y, si se indica, los parámetros guardados por el notebook (parametros_v4.json)."""
    global detector, BEST
    from ultralytics import YOLO
    BEST = str(pesos)
    if not Path(BEST).exists():
        raise FileNotFoundError(f"No se encontró el modelo: {BEST}")
    detector = YOLO(BEST)
    if dispositivo is not None:
        detector.to(dispositivo)
    usados = {}
    if parametros and Path(parametros).exists():
        p = json.loads(Path(parametros).read_text(encoding="utf-8"))
        for k, var in _MAPA_JSON.items():
            if k in p and p[k] is not None:
                usados[var] = p[k]
    if usados.get("ZONA_ACTIVA") not in ("detecciones", False):
        usados["ZONA_ACTIVA"] = "detecciones" if usados.get("ZONA_ACTIVA") else False   # YOLO-seg no se usa en la app
    globals().update(usados)
    return parametros_actuales()

def parametros_actuales():
    return {"modelo": Path(BEST).name if BEST else None, "conf_det": CONF_DET, "usar_tiles": USAR_TILES, "usar_tta": USAR_TTA,
            "zona": ZONA_ACTIVA, "umbral_stock": UMBRAL_STOCK, "bordes": BORDES, "k_hueco": K_HUECO, "tex_ratio_max": TEX_RATIO_MAX}

def ajustar(umbral_stock=None, conf_det=None):
    """Permite cambiar desde la app el umbral de alerta y la confianza mínima del detector."""
    global UMBRAL_STOCK, CONF_DET
    if umbral_stock is not None:
        UMBRAL_STOCK = float(umbral_stock)
    if conf_det is not None:
        CONF_DET = float(conf_det)

ESTADOS_TEXTO = {"OK": "OK", "ALERTA_REPONER": "REABASTECER", "REVISION_MANUAL": "REVISIÓN MANUAL"}

def dibujar_app(res, ancho_max=1600):
    """Igual que dibujar_resultado del notebook, pero SIN la franja de estado (la interfaz web la muestra aparte)
    y con trazos proporcionales al tamaño de la imagen."""
    im, an = res["im"], res["an"]
    s = min(1.0, ancho_max / max(im.shape[:2])); v = cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else im.copy()
    t = max(2, int(round(v.shape[1] / 700)))
    ov = v.copy()
    for x1, y1, x2, y2, rid, u in an["huecos"]:
        cv2.rectangle(ov, (int(x1 * s), int(y1 * s)), (int(x2 * s), int(y2 * s)), (0, 0, 255), -1)       # huecos: rojo
    v = cv2.addWeighted(ov, 0.45, v, 0.55, 0)
    for (x1, y1, x2, y2), f in zip((an["b"] * s).astype(int), an["fila"]):
        cv2.rectangle(v, (x1, y1), (x2, y2), PALETA[int(f) % len(PALETA)][::-1], t)
    for x1, y1, x2, y2, rid, rt in an["dudosos"]:
        cv2.rectangle(v, (int(x1 * s), int(y1 * s)), (int(x2 * s), int(y2 * s)), (0, 220, 255), max(1, t - 1))
    for lista, color, txt_, grosor in ((an["virtuales"], (0, 0, 255), "fila vacia", t + 2), (an.get("no_detectadas", []), (0, 220, 255), "sin detectar", max(1, t - 1))):
        for vr in lista:
            m_, c_ = vr.get("linea", (0.0, vr["y"]))
            p1 = (int(vr["x1"] * s), int((m_ * vr["x1"] + c_) * s)); p2 = (int(vr["x2"] * s), int((m_ * vr["x2"] + c_) * s))
            cv2.line(v, p1, p2, color, grosor)
            cv2.putText(v, txt_, (p1[0] + 6, p1[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5 * t / 2 + 0.2, color, max(1, t // 2))
    return v[..., ::-1]

def analizar_imagen(im_bgr, nombre="imagen", ancho_dibujo=1400, banda=True):
    """Analiza una imagen (numpy BGR). Devuelve un dict con el resultado y la imagen anotada en RGB.
    banda=False dibuja sin la franja de estado (para la interfaz web)."""
    if detector is None:
        raise RuntimeError("Primero llama a motor.cargar('best.pt')")
    if im_bgr is None:
        return {"foto": nombre, "estado": "REVISION_MANUAL", "estado_texto": ESTADOS_TEXTO["REVISION_MANUAL"], "stock_pct": None,
                "productos": 0, "detecciones": 0, "filas": 0, "huecos": 0, "filas_bajas": [], "motivos": ["no se pudo leer la imagen"],
                "tiempo_s": 0.0, "imagen": None}
    if im_bgr.ndim == 2:
        im_bgr = cv2.cvtColor(im_bgr, cv2.COLOR_GRAY2BGR)
    elif im_bgr.shape[2] == 4:
        im_bgr = cv2.cvtColor(im_bgr, cv2.COLOR_BGRA2BGR)
    r = evaluar_foto(np.ascontiguousarray(im_bgr), nombre, usar_cache=False)
    return {"foto": nombre, "estado": r["estado"], "estado_texto": ESTADOS_TEXTO.get(r["estado"], r["estado"]),
            "stock_pct": None if r["stock"] != r["stock"] else round(float(r["stock"]) * 100, 1),
            "productos": int(r["n_prod"]), "detecciones": int(r["n_det"]), "filas": int(r["filas"]), "huecos": int(r["huecos"]),
            "filas_bajas": r["filas_bajas"], "motivos": list(r["motivos"]), "tiempo_s": r["tiempo"],
            "imagen": (dibujar_resultado if banda else dibujar_app)(r, ancho_max=ancho_dibujo)}
