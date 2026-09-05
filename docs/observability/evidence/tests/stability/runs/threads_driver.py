import collections, sys, threading, unittest, faulthandler, time
faulthandler.enable()
sys.argv = ["x"]
t0 = time.time()
suite = unittest.defaultTestLoader.discover("tests/service", top_level_dir=".")
res = unittest.TextTestRunner(verbosity=0).run(suite)
print("SUITE", "run=%d" % res.testsRun, "errors=%d" % len(res.errors), "failures=%d" % len(res.failures))
print("WALL_SECONDS %.1f" % (time.time() - t0))
print("THREADS_ALIVE", threading.active_count())
c = collections.Counter(t.name.split("-")[0] for t in threading.enumerate())
for name, n in c.most_common():
    print("  THREADNAME %-40s %d" % (name, n))
