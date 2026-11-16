# -*- coding: utf-8 -*-
"""
features.py — Chargement des données + feature engineering 100 % "from scratch".

RÈGLE : aucun indicateur technique pré-fait (RSI, MACD, EMA, Bollinger, ATR, ADX...).
Toutes les features sont dérivées directement de l'OHLCV brut avec des opérations
élémentaires (ratios, sommes/médianes glissantes, rangs). Chaque feature à la bougie t
n'utilise que des informations disponibles À LA CLÔTURE de t (pas de look-ahead).
"""
import glob
import numpy as np
import pandas as pd

HORIZONS = [3, 6, 12, 24]          # horizons de prédiction testés (en bougies 5m)
W_FAST, W_MID, W_DAY, W_WEEK = 12, 48, 288, 2016   # 1h, 4h, 1 jour, 1 semaine


def load(data_dir: str) -> pd.DataFrame:
    """Charge et concatène les CSV mensuels Binance (klines 5m)."""
    files = sorted(glob.glob(f"{data_dir}/*.csv"))
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.drop_duplicates("ts").set_index("ts").sort_index()
    return df[["open", "high", "low", "close", "volume", "quote_volume",
               "count", "taker_buy_volume"]].astype(float)


def build_features(df: pd.DataFrame, with_taker: bool = False) -> pd.DataFrame:
    """Construit les features. Seules celles sans préfixe 'tk_' sont portables en Pine."""
    o, h, l, c, v = df.open, df.high, df.low, df.close, df.volume
    f = pd.DataFrame(index=df.index)
    rng = (h - l)
    rng_s = rng.replace(0, np.nan)
    lc = np.log(c)
    r1 = lc.diff()

    # --- 1. Anatomie de la bougie -------------------------------------------------
    f["body_ratio"] = (c - o) / rng_s                      # corps signé / range  [-1, 1]
    f["upper_wick"] = (h - np.maximum(o, c)) / rng_s       # mèche haute / range  [0, 1]
    f["lower_wick"] = (np.minimum(o, c) - l) / rng_s       # mèche basse / range  [0, 1]
    f["close_pos"] = (c - l) / rng_s                       # position du close dans le range
    f["wick_asym_12"] = (f.lower_wick - f.upper_wick).rolling(W_FAST).mean()

    # --- 2. Volatilité "maison" : médiane glissante du range relatif ----------------
    # (ce n'est PAS un ATR : pas de true range, pas de lissage de Wilder — simple médiane
    #  robuste de (high-low)/close sur 4h, insensible aux bougies extrêmes)
    rr = rng / c
    vol = rr.rolling(W_MID).median()
    f["vol_unit"] = vol                                    # sert aussi au SL/TP
    f["rng_rel"] = rr / vol                                # range de la bougie / range typique
    f["vol_ratio"] = rr.rolling(W_FAST).mean() / rr.rolling(W_DAY).mean()    # expansion/compression 1h vs 1j
    f["vol_regime"] = rr.rolling(W_MID).mean() / rr.rolling(W_WEEK).mean()   # niveau de vol 4h vs semaine

    # --- 3. Momentum normalisé par la volatilité maison --------------------------------
    for k in (1, 3, 6, 12, 48, 288):
        f[f"mom_{k}"] = lc.diff(k) / (vol * np.sqrt(k))
    # Efficacité du déplacement : |déplacement net| / chemin parcouru (0 = bruit, 1 = tendance pure)
    for k in (W_FAST, W_MID):
        f[f"eff_{k}"] = lc.diff(k).abs() / r1.abs().rolling(k).sum()
    # Position du close dans le canal haut/bas des k dernières bougies
    for k in (W_FAST, W_MID, W_DAY):
        hh, ll = h.rolling(k).max(), l.rolling(k).min()
        f[f"chan_pos_{k}"] = (c - ll) / (hh - ll).replace(0, np.nan)
    # Écart au prix moyen pondéré par le volume (recalculé à la main), en unités de vol
    tp = (h + l + c) / 3
    for k in (W_MID, W_DAY):
        vw = (tp * v).rolling(k).sum() / v.rolling(k).sum()
        f[f"vw_dev_{k}"] = (c / vw - 1) / vol

    # --- 4. Moments glissants des rendements -------------------------------------------
    f["skew_48"] = r1.rolling(W_MID).skew()
    f["kurt_48"] = r1.rolling(W_MID).kurt()

    # --- 5. Volume ---------------------------------------------------------------------
    f["rel_vol"] = v / v.rolling(W_DAY).median()           # volume relatif à la médiane 24h
    f["rel_vol_6"] = v.rolling(6).mean() / v.rolling(W_DAY).median()
    sv = v * (2 * f.close_pos - 1)                         # delta de volume signé (proxy OHLC)
    for k in (3, W_FAST, W_MID):
        f[f"imb_{k}"] = sv.rolling(k).sum() / v.rolling(k).sum()   # imbalance [-1, 1]
    # "Effort vs résultat" : rendement par unité de volume relatif
    f["effort"] = f.mom_1 / f.rel_vol.clip(lower=0.1)

    # --- 6. Séquences (n-grammes) --------------------------------------------------------
    up = (c > o).astype(int)
    f["ngram3"] = up.shift(2) * 4 + up.shift(1) * 2 + up   # code 0..7 des 3 dernières bougies
    sgn = np.sign(c - o).replace(0, 1)
    grp = (sgn != sgn.shift()).cumsum()
    f["run_len"] = sgn * (sgn.groupby(grp).cumcount() + 1)  # longueur signée de la série en cours
    f["up_frac_12"] = up.rolling(W_FAST).mean()

    # --- 7. Temps (encodage cyclique) ----------------------------------------------------
    hour = df.index.hour + df.index.minute / 60
    f["hour_sin"], f["hour_cos"] = np.sin(2 * np.pi * hour / 24), np.cos(2 * np.pi * hour / 24)
    dow = df.index.dayofweek
    f["dow_sin"], f["dow_cos"] = np.sin(2 * np.pi * dow / 7), np.cos(2 * np.pi * dow / 7)
    f["hour"] = df.index.hour

    # --- 8. Features "taker" (présentes dans le CSV Binance, NON disponibles en Pine) ----
    if with_taker:
        tb = df.taker_buy_volume / v.replace(0, np.nan)
        f["tk_imb_1"] = 2 * tb - 1
        f["tk_imb_12"] = (2 * df.taker_buy_volume - v).rolling(W_FAST).sum() / v.rolling(W_FAST).sum()
        f["tk_imb_48"] = (2 * df.taker_buy_volume - v).rolling(W_MID).sum() / v.rolling(W_MID).sum()
        ats = v / df["count"].replace(0, np.nan)
        f["tk_trade_size"] = ats / ats.rolling(W_DAY).median()
    return f


def forward_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Rendement futur RÉALISTE : entrée à l'OPEN de t+1, sortie au close de t+N (en bp)."""
    out = pd.DataFrame(index=df.index)
    entry = df.open.shift(-1)
    for n in HORIZONS:
        out[f"fwd_{n}"] = np.log(df.close.shift(-n) / entry) * 1e4
    return out
