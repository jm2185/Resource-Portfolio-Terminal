"""
Base rates — published priors that make calibration useful from day one (Forge M7 cold-start).

You make few decisions in a 4-name book, so for months the personal sample is too thin to learn from.
This module seeds the calibration loop with PUBLISHED mining base rates as Bayesian priors, then lets
personal decisions + the Ledger's REJECTs Bayesian-update them. Every estimate is reported as a value
**with a credible interval** — never a bare false-precision %.

Sourcing discipline (Build Spec Open-Decision #6 — "research this before implementing"). Each prior
carries its source + URL + a confidence grade. We separate PRIMARY/near-primary figures (seed with
moderate confidence) from FOLKLORE-grade figures (seed anchored but DELIBERATELY wide):

  * **Discovery → mine: Beta(12, 12), mean 0.50.** MinEx Consulting / Richard Schodde, dataset of
    4,676 significant discoveries since 1950 of which 2,120 became mines = 45% nominal (50–70%
    censoring-corrected). PRIMARY. https://minexconsulting.com/time-delay-between-discovery-and-development-is-it-getting-more-difficult/
  * **Time discovery → production: LogNormal(ln 15.5, 0.30) yr** (recent vintage ln 17.5). S&P Global
    Market Intelligence, n=127 mines, mean 15.7yr (range 6–32), rising to 17.9yr for 2020–23 starts.
    PRIMARY. https://www.spglobal.com/market-intelligence/en/news-insights/research/discovery-to-production-averages-15-7-years-for-127-mines
  * **Junior gold/silver takeover premium (20-day): LogNormal on (1+p), median ≈ 35%.** S&P Global
    Market Intelligence / SNL Metals & Mining (best dataset to condition on junior precious-metals
    deals); corroborated by Newmont–Newcrest 30–39% and the ~40% cross-industry average. MEDIUM-HIGH.
    https://www.spglobal.com/market-intelligence/en/news-insights/research/newmont-acquisition-of-newcrest-would-be-largest-gold-merger-in-history
  * **Stage-conditional advancement gates (PEA→PFS→FS→build→production).** Secondary explainers +
    the construction→production "rarely abandoned once built". MEDIUM → moderate variance.
  * **Grassroots anomaly → mine: Beta(1, 700), mean ~0.0014.** The classic "~1 in 1,000" — FOLKLORE
    (one source explicitly disclaims a primary statistic). Anchored but interval spans an order of
    magnitude. LOW.
  * **Lassonde-curve stage_cap multipliers.** The curve's SHAPE is canonical (discovery pop →
    "orphan period" trough → production re-rate), but NO reputable source quantifies the magnitudes —
    these are ENGINEERING priors with wide σ, meant to be overwritten by outcomes fast. LOW.

Pure stdlib (the incomplete-beta + inverse-normal are implemented here — no scipy). Fully testable.
"""
from __future__ import annotations

import math
from typing import Optional

# --------------------------------------------------------------------------- numerics (pure stdlib)
def _betacf(a: float, b: float, x: float) -> float:
    MAXIT, EPS, FPMIN = 300, 1e-12, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b) = Beta CDF at x (Numerical Recipes continued fraction)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def beta_ppf(p: float, a: float, b: float) -> float:
    """Beta quantile by bisection on the CDF — pure stdlib, ~1e-12 precision."""
    p = min(1.0, max(0.0, p))
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if betainc(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def beta_mean(a: float, b: float) -> float:
    return a / (a + b)


def beta_ci(a: float, b: float, mass: float = 0.90) -> tuple:
    tail = (1.0 - mass) / 2.0
    return (round(beta_ppf(tail, a, b), 4), round(beta_ppf(1.0 - tail, a, b), 4))


def norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (Acklam's rational approximation). |error| < 1.2e-9."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def lognormal_median(mu: float) -> float:
    return math.exp(mu)


def lognormal_ci(mu: float, sigma: float, mass: float = 0.90) -> tuple:
    tail = (1.0 - mass) / 2.0
    z = norm_ppf(1.0 - tail)
    return (round(math.exp(mu - z * sigma), 4), round(math.exp(mu + z * sigma), 4))


# --------------------------------------------------------------------------- the prior registry
#: name -> prior. Beta priors are probabilities; lognormal priors are magnitudes. ``offset=-1`` marks
#: a lognormal stated on (1+x) (a premium): report median/CI as exp(...) − 1.
PRIORS: dict = {
    "discovery_to_mine": {
        "kind": "beta", "a": 12.0, "b": 12.0, "confidence": "high",
        "source": "MinEx Consulting / Schodde (n=4,676 discoveries since 1950; 45% nominal, 50–70% corrected)",
        "url": "https://minexconsulting.com/time-delay-between-discovery-and-development-is-it-getting-more-difficult/",
        "note": "PRIMARY — the strongest anchor; gold does better than base metals (nudge a→+1).",
    },
    "grassroots_to_mine": {
        "kind": "beta", "a": 1.0, "b": 700.0, "confidence": "low",
        "source": "Folklore '~1 in 1,000 anomalies' (no primary statistic; one source disclaims it)",
        "url": "https://rangefront.com/blog/basics-of-mineral-exploration/",
        "note": "FOLKLORE — anchored, interval spans an order of magnitude on purpose.",
    },
    "deposit_to_pea": {
        "kind": "beta", "a": 4.0, "b": 3.0, "confidence": "low",
        "source": "Secondary stage-funnel explainers", "url": "https://discoveryalert.com.au/mining-company-development-stages-2025/",
        "note": "WEAK — moderate variance until a Schodde/USGS stage primary replaces it.",
    },
    "pea_to_pfs": {
        "kind": "beta", "a": 6.0, "b": 4.0, "confidence": "medium",
        "source": "PFS culls ~40% of PEA-economic projects (secondary)", "url": "https://discoveryalert.com.au/mining-company-development-stages-2025/",
        "note": "MEDIUM.",
    },
    "pfs_to_fs": {
        "kind": "beta", "a": 6.0, "b": 4.0, "confidence": "medium",
        "source": "~60% of PFS projects advance to DFS (secondary)", "url": "https://discoveryalert.com.au/mining-company-development-stages-2025/",
        "note": "MEDIUM.",
    },
    "fs_to_construction": {
        "kind": "beta", "a": 5.0, "b": 5.0, "confidence": "medium",
        "source": "~50% of viable projects clear permitting + financing (secondary)", "url": "https://discoveryalert.com.au/junior-mining-stocks-investing-2025-benefits/",
        "note": "MEDIUM.",
    },
    "construction_to_production": {
        "kind": "beta", "a": 9.0, "b": 1.5, "confidence": "medium",
        "source": "Rarely abandoned once built (~85–90%)", "url": "https://discoveryalert.com.au/mining-company-development-stages-2025/",
        "note": "MEDIUM-HIGH.",
    },
    "time_to_production_years": {
        "kind": "lognormal", "mu": math.log(15.5), "sigma": 0.30, "confidence": "high",
        "source": "S&P Global Market Intelligence (n=127 mines; mean 15.7yr, range 6–32)",
        "url": "https://www.spglobal.com/market-intelligence/en/news-insights/research/discovery-to-production-averages-15-7-years-for-127-mines",
        "note": "PRIMARY — recent vintage runs longer (≈17.5yr for 2020–23 starts).",
    },
    "time_to_production_recent_years": {
        "kind": "lognormal", "mu": math.log(17.5), "sigma": 0.28, "confidence": "high",
        "source": "S&P Global Market Intelligence — lead time ~17.9yr for mines started 2020–23",
        "url": "https://www.spglobal.com/market-intelligence/en/news-insights/research/average-lead-time-almost-18-years-for-mines-started-in-2020-23",
        "note": "Use when dating new projects.",
    },
    "ma_premium_20d": {
        "kind": "lognormal", "mu": math.log(1.35), "sigma": 0.22, "offset": -1.0, "confidence": "medium",
        "source": "S&P Global Market Intelligence / SNL Metals & Mining (junior gold/silver deals); "
                  "Newmont–Newcrest 30–39%; ~40% cross-industry avg",
        "url": "https://www.spglobal.com/market-intelligence/en/news-insights/research/newmont-acquisition-of-newcrest-would-be-largest-gold-merger-in-history",
        "note": "MEDIUM-HIGH central, HIGH dispersion. MoE → ~0–5%; contested/sole-asset → higher.",
    },
    "ma_premium_1d": {
        "kind": "lognormal", "mu": math.log(1.30), "sigma": 0.22, "offset": -1.0, "confidence": "medium",
        "source": "As ma_premium_20d; 1-day runs a few points below 20-day",
        "url": "https://www.spglobal.com/market-intelligence/en/news-insights/research/newmont-acquisition-of-newcrest-would-be-largest-gold-merger-in-history",
        "note": "Refinitiv/LSEG (SDC) is the better source for standardized 1d-vs-20d premium fields.",
    },
}

#: Lassonde-curve stage_cap: a multiplier on RESIDUAL upside that decays as the project de-risks
#: (most convexity is paid out at/after discovery). ENGINEERING prior — wide σ, overwrite with data.
STAGE_CAP: dict = {
    "grassroots": {"mean": 1.00, "sigma": 0.00},
    "concept": {"mean": 1.00, "sigma": 0.50},
    "discovery": {"mean": 0.85, "sigma": 0.50},
    "feasibility": {"mean": 0.55, "sigma": 0.45},
    "orphan": {"mean": 0.55, "sigma": 0.45},
    "development": {"mean": 0.40, "sigma": 0.40},
    "construction": {"mean": 0.40, "sigma": 0.40},
    "production": {"mean": 0.25, "sigma": 0.35},
}
STAGE_CAP_SOURCE = ("Lassonde curve (shape canonical; magnitudes are engineering priors — no source "
                    "quantifies the pop/orphan/re-rate). https://elements.visualcapitalist.com/"
                    "visualizing-the-life-cycle-of-a-mineral-discovery/")


# --------------------------------------------------------------------------- reporting + update
def estimate(name: str, mass: float = 0.90) -> Optional[dict]:
    """The prior's central estimate + credible interval + provenance. Never a bare %."""
    p = PRIORS.get(name)
    if not p:
        return None
    if p["kind"] == "beta":
        a, b = p["a"], p["b"]
        return {"name": name, "kind": "beta", "mean": round(beta_mean(a, b), 4),
                "ci90": beta_ci(a, b, mass), "a": a, "b": b,
                "confidence": p["confidence"], "source": p["source"], "url": p["url"], "note": p.get("note")}
    mu, sigma, off = p["mu"], p["sigma"], p.get("offset", 0.0)
    med = lognormal_median(mu) + off
    lo, hi = lognormal_ci(mu, sigma, mass)
    return {"name": name, "kind": "lognormal", "median": round(med, 4),
            "ci90": (round(lo + off, 4), round(hi + off, 4)), "mu": mu, "sigma": sigma,
            "offset": off, "confidence": p["confidence"], "source": p["source"], "url": p["url"],
            "note": p.get("note")}


def update_beta(name: str, successes: float, failures: float, mass: float = 0.90) -> dict:
    """Bayesian-update a Beta prior with observed successes/failures (personal decisions + Ledger
    REJECTs widen n). Returns the posterior mean + credible interval and how much data moved it."""
    p = PRIORS.get(name)
    if not p or p.get("kind") != "beta":
        raise ValueError(f"{name!r} is not a Beta prior")
    a0, b0 = p["a"], p["b"]
    a, b = a0 + max(0.0, successes), b0 + max(0.0, failures)
    n_prior, n_data = a0 + b0, successes + failures
    return {"name": name, "prior_mean": round(beta_mean(a0, b0), 4),
            "posterior_mean": round(beta_mean(a, b), 4), "ci90": beta_ci(a, b, mass),
            "a": a, "b": b, "n_prior": n_prior, "n_data": n_data,
            "shrinkage": round(n_prior / (n_prior + n_data), 3) if (n_prior + n_data) else 1.0,
            "source": p["source"], "confidence": p["confidence"]}


def update_normal(prior_mu: float, prior_sigma: float, obs: list, obs_sigma: float,
                  mass: float = 0.90) -> dict:
    """Normal-Normal conjugate update for a magnitude (e.g. realized takeover premia vs the prior).
    ``obs`` are observations on the SAME scale as prior_mu (use log-scale for the lognormal premia)."""
    obs = [float(o) for o in (obs or []) if o is not None]
    if not obs:
        return {"posterior_mu": prior_mu, "posterior_sigma": prior_sigma, "n": 0,
                "ci90": (round(prior_mu - norm_ppf(1 - (1 - mass) / 2) * prior_sigma, 4),
                         round(prior_mu + norm_ppf(1 - (1 - mass) / 2) * prior_sigma, 4))}
    n = len(obs)
    xbar = sum(obs) / n
    prior_prec = 1.0 / (prior_sigma ** 2)
    data_prec = n / (obs_sigma ** 2)
    post_prec = prior_prec + data_prec
    post_mu = (prior_prec * prior_mu + data_prec * xbar) / post_prec
    post_sigma = math.sqrt(1.0 / post_prec)
    z = norm_ppf(1 - (1 - mass) / 2)
    return {"posterior_mu": round(post_mu, 4), "posterior_sigma": round(post_sigma, 4), "n": n,
            "ci90": (round(post_mu - z * post_sigma, 4), round(post_mu + z * post_sigma, 4))}


def stage_cap(stage: Optional[str], mass: float = 0.90) -> dict:
    """The stage_cap multiplier prior for a Lassonde stage (decaying residual-upside multiplier)."""
    key = str(stage or "").strip().lower()
    s = STAGE_CAP.get(key) or STAGE_CAP.get("concept")
    mean, sigma = s["mean"], s["sigma"]
    if sigma <= 0:
        ci = (mean, mean)
    else:                                   # treat as lognormal around the mean for a one-sided-bounded CI
        mu = math.log(max(1e-6, mean))
        ci = lognormal_ci(mu, sigma, mass)
    return {"stage": key or "concept", "mean": mean, "sigma": sigma, "ci90": ci,
            "confidence": "low", "source": STAGE_CAP_SOURCE}


def report(name: str) -> str:
    """A one-line human summary: estimate + interval + confidence + source. Never a bare %."""
    e = estimate(name)
    if not e:
        return f"{name}: (no prior)"
    if e["kind"] == "beta":
        lo, hi = e["ci90"]
        return (f"{name}: {e['mean']:.1%} (90% CI {lo:.1%}–{hi:.1%}) · {e['confidence']} · {e['source']}")
    lo, hi = e["ci90"]
    return (f"{name}: median {e['median']:.2f} (90% CI {lo:.2f}–{hi:.2f}) · {e['confidence']} · {e['source']}")


def all_estimates() -> dict:
    return {k: estimate(k) for k in PRIORS}
