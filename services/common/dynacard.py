"""
dynacard.py — core sucker-rod-pump card physics.

Three responsibilities, shared by the simulator and the ingest service:

  1. forward simulation:  a downhole pump condition -> a realistic SURFACE card
                          (this is what a POC/RTU would actually measure)
  2. Gibbs transform:     SURFACE card -> DOWNHOLE pump card
                          (damped wave equation, solved harmonic-by-harmonic)
  3. diagnosis:           downhole card -> scalar KPIs + a fault label

Only numpy is required.  Units: inches, pounds, seconds, psi.
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass, field

N_SAMPLES = 200                     # samples per card (fixed by the spec)
E_STEEL   = 30.5e6                  # Young's modulus, psi
ROD_SOUND = 16300.0 * 12.0         # rod sound speed, in/s  (16,300 ft/s)


# --------------------------------------------------------------------------
# Well / rod-string description
# --------------------------------------------------------------------------
@dataclass
class Well:
    well_id:      str
    stroke_in:    float = 144.0     # surface stroke length, inches
    spm:          float = 8.0       # strokes per minute
    depth_ft:     float = 6000.0    # pump setting depth
    rod_area_in2: float = 0.601     # effective rod cross-section (7/8" rod)
    rod_wt_lbft:  float = 1.63      # rod weight per foot
    buoyancy:     float = 0.87      # buoyancy factor
    plunger_in:   float = 1.5       # plunger diameter
    net_lift_psi: float = 3000.0    # differential pressure across plunger
    unit_asym:    float = 0.22      # conventional-unit kinematic asymmetry
    damping:      float = 0.13      # dimensionless rod-string damping

    # -- derived ----------------------------------------------------------
    @property
    def length_in(self) -> float:
        return self.depth_ft * 12.0

    @property
    def rod_weight(self) -> float:              # buoyant rod weight, lb
        return self.rod_wt_lbft * self.depth_ft * self.buoyancy

    @property
    def plunger_area(self) -> float:
        return np.pi / 4.0 * self.plunger_in ** 2

    @property
    def fluid_load(self) -> float:              # Fo, lb
        return self.net_lift_psi * self.plunger_area

    @property
    def period_s(self) -> float:                # one full stroke, seconds
        return 60.0 / self.spm


# --------------------------------------------------------------------------
# Pumping-unit kinematics: polished-rod position over one cycle
# --------------------------------------------------------------------------
def polished_rod_position(well: Well, n: int = N_SAMPLES) -> np.ndarray:
    """Surface position 0..stroke over one crank revolution (inches)."""
    theta = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    # crank + second-harmonic term -> conventional-unit asymmetry
    raw = (1 - np.cos(theta)) + (well.unit_asym / 2.0) * (1 - np.cos(2 * theta))
    raw = (raw - raw.min()) / (raw.max() - raw.min())
    return raw * well.stroke_in


# --------------------------------------------------------------------------
# 1. FORWARD MODEL:  downhole condition  ->  surface card
# --------------------------------------------------------------------------
CONDITIONS = (
    "full", "fluid_pound", "gas_interference",
    "gas_lock", "tv_leak", "sv_leak",
)


def _pump_fluid_profile(cond: str, up: np.ndarray, dn: np.ndarray,
                        fillage: float, rng: np.random.Generator):
    """
    Fraction (0..1) of full fluid load carried by the plunger, as a function
    of plunger position, separately on the up- and down-strokes.
    `up`/`dn` are plunger positions 0..1 (bottom..top) along each half-stroke.
    Returns (load_up, load_dn) each 0..1 -- the classic downhole signatures.
    """
    lu = np.ones_like(up)      # upstroke: valve closed -> carries fluid load
    ld = np.zeros_like(dn)     # downstroke: valve open  -> no fluid load

    if cond == "full":
        pass

    elif cond == "fluid_pound":                 # incomplete fillage + slam
        # plunger travels through fluid-free space, then slams the liquid
        hit = fillage
        ld = np.where(dn < hit, 0.0, (dn - hit) / max(1e-3, 1 - hit))
        ld = np.clip(ld * 1.15, 0, 1)           # sharp late rise = the pound
        lu = np.where(up < hit, up / max(1e-3, hit), 1.0)

    elif cond == "gas_interference":            # gradual gas expansion
        hit = fillage
        ld = np.clip((dn - hit) / max(1e-3, 1 - hit), 0, 1) ** 2.2  # rounded
        lu = np.clip(0.15 + up * 0.95, 0, 1)

    elif cond == "gas_lock":                    # almost no fluid moved
        lu = 0.12 + 0.05 * up
        ld = 0.10 * (1 - dn)

    elif cond == "tv_leak":                     # bleeds off across upstroke
        lu = np.clip(1.0 - 0.55 * up, 0.25, 1.0)
        ld = 0.18 * (1 - dn)

    elif cond == "sv_leak":                     # bottom line elevated
        lu = np.clip(0.35 + 0.65 * up, 0, 1)
        ld = np.clip(0.30 * (1 - dn), 0, 1)

    return lu, ld


def _transfer(well: Well, N: int):
    """
    Per-harmonic wave-equation transfer for the rod string.  Returns arrays
    (ch, sh, EAmu, mask) for the 2x2 propagation matrix M(k) that maps
    surface coefficients DOWN to the pump:

        [Ud; Fd] = [[ch,       sh/(EA*mu)],
                    [EA*mu*sh, ch        ]] [Up; Fp]

    det(M) = cosh^2 - sinh^2 = 1, so the inverse (used to propagate a
    downhole card UP to the surface) is obtained by flipping the sign of the
    off-diagonal terms -- which makes the simulator an exact inverse of the
    Gibbs transform.
    """
    L, a, EA = well.length_in, ROD_SOUND, E_STEEL * well.rod_area_in2
    Tc = well.period_s
    c = well.damping * (4 * np.pi / Tc)                 # damping coeff, 1/s
    w = 2 * np.pi * np.fft.fftfreq(N, d=Tc / N)         # rad/s per harmonic

    mu = np.sqrt((1j * c * w - w ** 2) / a ** 2 + 0j)
    mu = np.where(mu.real < 0, -mu, mu)
    with np.errstate(divide="ignore", invalid="ignore"):
        ch = np.cosh(mu * L)
        sh = np.sinh(mu * L)
        sh_over = np.where(np.abs(mu) < 1e-12, L / EA, sh / (EA * mu))  # n=0
        EAmu_sh = np.where(np.abs(mu) < 1e-12, 0.0, EA * mu * sh)
    return ch, sh_over, EAmu_sh, EA


def simulate_surface_card(well: Well, cond: str = "full",
                          fillage: float = 1.0, noise: float = 0.006,
                          seed: int | None = None):
    """
    Produce one realistic SURFACE dynamometer card (position_in, load_lb).

    A clean textbook DOWNHOLE pump card is built for the requested condition
    and propagated UP the rod string with the inverse wave-equation transfer.
    The surface card therefore carries the correct rod dynamics (shear, phase
    lag, inertia) automatically, and Gibbs recovers the pump card downstream.
    """
    rng = np.random.default_rng(seed)
    n = N_SAMPLES
    theta = np.linspace(0.0, 2 * np.pi, n, endpoint=False)

    # ---- clean downhole pump card ---------------------------------------
    shape = (1 - np.cos(theta)) / 2.0                   # kinematic 0..1
    plunger_stroke = well.stroke_in * 0.92
    d_pos = shape * plunger_stroke                      # downhole position
    vel = np.gradient(d_pos)
    up_idx, dn_idx = np.where(vel >= 0)[0], np.where(vel < 0)[0]
    p = (d_pos - d_pos.min()) / max(1e-6, np.ptp(d_pos))

    lu, ld = _pump_fluid_profile(cond, p[up_idx], p[dn_idx], fillage, rng)
    frac = np.zeros(n)
    frac[up_idx], frac[dn_idx] = lu, ld
    Fo = well.fluid_load
    d_load = frac * Fo                                  # downhole load 0..Fo

    # ---- propagate UP to surface (inverse transfer, off-diagonal flipped)-
    ch, sh_over, EAmu_sh, EA = _transfer(well, n)
    Ud, Fd = np.fft.fft(d_pos), np.fft.fft(d_load)
    Up = ch * Ud - sh_over * Fd
    Fp = -EAmu_sh * Ud + ch * Fd
    surf_pos = np.real(np.fft.ifft(Up))
    surf_load = np.real(np.fft.ifft(Fp)) + well.rod_weight   # add rod weight

    # ---- measurement noise ----------------------------------------------
    surf_load += rng.normal(0, noise * Fo, n)
    surf_pos += rng.normal(0, noise * well.stroke_in * 0.5, n)
    return surf_pos.astype(np.float32), surf_load.astype(np.float32)


# --------------------------------------------------------------------------
# 2. GIBBS TRANSFORM:  surface card  ->  downhole pump card
# --------------------------------------------------------------------------
def gibbs_downhole(position: np.ndarray, load: np.ndarray, well: Well,
                   n_harmonics: int = 20):
    """
    Solve the damped wave equation  u_tt + c u_t = a^2 u_xx  harmonic by
    harmonic to propagate the measured surface record DOWN to the pump.
    Rod weight is stripped first so the returned pump card is referenced to
    fluid load (0..Fo), the form used for diagnosis.  Harmonics above
    `n_harmonics` are discarded to suppress measurement noise.
    """
    pos = np.asarray(position, float)
    ld = np.asarray(load, float) - well.rod_weight
    N = len(pos)

    ch, sh_over, EAmu_sh, EA = _transfer(well, N)
    Up, Fp = np.fft.fft(pos), np.fft.fft(ld)

    freqs = np.abs(np.fft.fftfreq(N))
    keep = freqs <= (n_harmonics + 0.5) / N
    Up, Fp = Up * keep, Fp * keep

    Ud = ch * Up + sh_over * Fp
    Fd = EAmu_sh * Up + ch * Fp
    pos_dh = np.real(np.fft.ifft(Ud))
    load_dh = np.real(np.fft.ifft(Fd))
    return pos_dh.astype(np.float32), load_dh.astype(np.float32)


# --------------------------------------------------------------------------
# 3. METRICS + DIAGNOSIS  (operates on the downhole card)
# --------------------------------------------------------------------------
def _poly_area(x, y):                    # shoelace, signed loop area
    return 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)


@dataclass
class CardMetrics:
    spm: float
    stroke_in: float
    pprl: float            # peak polished-rod load
    mprl: float            # minimum polished-rod load
    card_area: float       # downhole loop area (in*lb ~ work/stroke)
    fluid_load: float      # estimated Fo
    fillage_pct: float
    pump_disp_bpd: float
    diagnosis: str
    confidence: float


def _med3(x):                            # 3-point median filter (no scipy)
    return np.median(np.stack([np.roll(x, 1), x, np.roll(x, -1)]), axis=0)


def diagnose(surf_pos, surf_load, dh_pos, dh_load, well: Well) -> CardMetrics:
    """
    Classify the downhole pump card and compute operational KPIs.  Thresholds
    were calibrated on the simulator's feature distributions; the features are
    scale-free ratios so they transfer to real cards of any magnitude.
    """
    pprl = float(np.max(surf_load))
    mprl = float(np.min(surf_load))
    dl = _med3(np.asarray(dh_load, float))
    area = abs(float(_poly_area(dh_pos, dl)))

    lo, hi = np.percentile(dl, 8), np.percentile(dl, 92)
    span = max(1.0, hi - lo)
    Fo = float(hi)                                  # top load line ~ Fo
    sspan = max(1.0, float(np.max(surf_load) - np.min(surf_load)))
    span_ratio = span / sspan                       # collapsed loop -> small
    box_area = span * max(1e-6, np.ptp(dh_pos))
    area_ratio = area / box_area                    # rectangle -> ~1

    p = (dh_pos - dh_pos.min()) / max(1e-6, np.ptp(dh_pos))
    y = (dl - lo) / span
    loaded = dl > (lo + 0.5 * span)
    fillage = float(np.clip(np.ptp(p[loaded]) if loaded.any() else 0.0, 0, 1))

    vel = np.gradient(dh_pos)
    up = vel >= 0
    droop = float(np.polyfit(p[up], dl[up], 1)[0] / span) if up.sum() > 3 else 0.0
    bottom_lvl = float((np.median(dl[~up]) - lo) / span)
    flat_top = float(np.mean(y[up] > 0.85))         # full-load plateau length

    # ---- calibrated decision tree ---------------------------------------
    if span_ratio < 0.48:                           # loop collapsed near zero
        diag, conf = "gas_lock", 0.80
    elif droop < -0.30:                             # upstroke bleeds off
        diag, conf = "tv_leak", 0.78
    elif bottom_lvl > 0.10:                         # downstroke line elevated
        diag, conf = "sv_leak", 0.74
    elif area_ratio > 0.80 and fillage > 0.90:      # full parallelogram
        diag, conf = "full", 0.90
    elif fillage < 0.88:                            # incomplete fillage
        if flat_top > 0.40:
            diag, conf = "fluid_pound", 0.76        # sharp slam, flat top
        else:
            diag, conf = "gas_interference", 0.72   # gradual, sloped
    else:
        diag, conf = "full", 0.70

    net_stroke_in = np.ptp(dh_pos) * fillage
    disp_bpd = (well.plunger_area * net_stroke_in * well.spm * 1440.0) / 9702.0

    return CardMetrics(
        spm=well.spm, stroke_in=well.stroke_in,
        pprl=pprl, mprl=mprl, card_area=area, fluid_load=Fo,
        fillage_pct=round(fillage * 100, 1),
        pump_disp_bpd=round(float(disp_bpd), 1),
        diagnosis=diag, confidence=round(conf, 2),
    )
