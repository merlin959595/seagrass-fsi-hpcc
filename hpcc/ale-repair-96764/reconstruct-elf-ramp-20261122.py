#!/usr/bin/env python3
"""Static scalar reconstruction of seagrass558RampFile::operator() from pinned ELF.

Source: user-supplied FULL 720-line objdump, sha256:
8228bf83e848bbd5217561946deaa9d2b3af762fac876e2e49d1db9f118c4720
Shared library sha256:
1032420382c07a8138f122199017013ed0aa242410f73a41330cbff199aac1a2

This is a PURE mathematical inspection of the two time/spatial multipliers
seen in the function. It does not load the .so, inspect private HPCC data,
modify any coefficients, or run CFD/FSI.

The field-level base exponentiation is inferred from the source object's
base-fileDiffusivity field and the string "exponent"; PLT relocation not
resolved in this dump, so field formula below is labelled reconstruction,
not a verified full OpenFOAM runtime substitute.
"""
import math

T0=0.5535
T1=0.5565
EXPO_START=0.925
EXPO_END=1.0
AMP_A_END=1.5
AMP_B_END=-0.35

def ss01(u):
    """Clamped cubic smoothstep: exact scalar operations in ELF."""
    u=min(1.,max(0.,u))
    return u*u*(3.-2.*u)

def time_s(t):
    return ss01((t-T0)/(T1-T0))

def window_a(x,y,z):
    """First window: near-bed x band, width/height taper; constants from ELF."""
    return (ss01((x-.032)/.038)
            *(1.-ss01((x-.165)/.085))
            *(1.-ss01((abs(y)-.018)/.045))
            *(1.-ss01((z-.004)/.042)))

def window_b(x,y,z):
    """Second window: upper-seagrass-edge band, from compiled ELF literals."""
    return (ss01((x-.035)/.025)
            *(1.-ss01((x-.108)/.037))
            *(1.-ss01((abs(abs(y)-.005)-.00045)/.01))
            *ss01((z-.088)/.020)
            *(1.-ss01((z-.132)/.024)))

def coefficients(t,x,y,z):
    """Return scalar factors of the compiled model, not a mesh displacement."""
    s=time_s(t)
    exponent=EXPO_START+(EXPO_END-EXPO_START)*s
    # ELF 0x208f4 -> early return if s EXACTLY zero:
    if s==0.:
        return {"s":s, "exponent":exponent, "a":0., "b":0.,
                "factor_a":1., "factor_b":1., "both":1.}
    a=window_a(x,y,z)
    b=window_b(x,y,z)
    # ELF 20ce0,20d11,20d16,20b31,20b44:
    positive_amplitude=2.+(AMP_A_END-2.)*s
    factor_a=1.+positive_amplitude*a
    # ELF 20cf0,20b3f/20e2,20cb8/20cbc:
    negative_amplitude=AMP_B_END*s
    factor_b=1.+negative_amplitude*b
    return {"s":s, "exponent":exponent, "a":a, "b":b,
            "factor_a":factor_a, "factor_b":factor_b,
            "both":factor_a*factor_b}

def illustrative_effective_diffusivity(dref,t,x,y,z):
    """INFERRED: Dref**exponent times exact arithmetic mask factors.

    Full Foam::pow(...) call identity is not proved from the supplied ELF
    symbol-only disassembly. Do not use this as authoritative replacement
    for native OpenFOAM.
    """
    assert dref>0
    out=coefficients(t,x,y,z)
    return dref**out["exponent"] * out["both"]

def self_test():
    p=(0.11435628214473606,-0.046203101171458344,0.009258573096591673)
    a=window_a(*p)
    b=window_b(*p)
    assert math.isclose(a,.300434964806,rel_tol=2e-8)
    assert b==0.
    at=coefficients(.5635,*p)
    assert at["s"]==1.
    assert at["exponent"]==1.
    assert math.isclose(at["factor_a"],1.450652447209,rel_tol=2e-8)
    assert at["factor_b"]==1.
    assert coefficients(T0,*p)["factor_a"]==1.
    # CRITICAL: alpha~0+ still activates 2*A without a global alpha factor.
    just_after=coefficients(T0+1e-9,*p)
    assert just_after["factor_a"]>1.60
    assert math.isclose(coefficients(.5635,.10,.005,.11)["factor_b"],.65,abs_tol=1e-12)
    for x,y,z in [p,(.1,.005,.11),(.3,.1,.2)]:
        g=coefficients(.5635,x,y,z)
        assert 1<=g["factor_a"]<=2.5
        assert .65<=g["factor_b"]<=1
    print("ELF_SCALAR_RECONSTRUCTION_SELF_TEST_PASS")
    print("RAMP_START_0P5535",coefficients(T0,*p))
    print("RAMP_AFTER_1NS",just_after)
    print("RESTART_0P5635_NEAR_BED_CELL2758_CENTRE_APPROX",at)
    print("WARNING: cell centre is illustrative, not actual face-centre coefficient")
    print("WARNING: time-window relabeling cannot provide a globally continuous restart")

if __name__=="__main__":
    self_test()
