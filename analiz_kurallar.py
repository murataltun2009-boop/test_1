print()
print("KISA SONUC")
print("-" * 92)
for tf in ("15m", "1h", "4h"):
    pa = ozet[(tf, "entry")]["profit"]
    la = ozet[(tf, "entry")]["long"]
    sa = ozet[(tf, "entry")]["short"]
    pb = ozet[(tf, "pullback")]["profit"]
    lb = ozet[(tf, "pullback")]["long"]
    sb = ozet[(tf, "pullback")]["short"]
    print("  " + tf.ljust(5) + " entry    : LONG {}  SHORT {}  net {:+.2f}".format(la, sa, pa))
    print("        pullback : LONG {}  SHORT {}  net {:+.2f}   (fark {:+.2f})".format(lb, sb, pb, pb - pa))
