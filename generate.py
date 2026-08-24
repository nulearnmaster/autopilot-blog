import sys
from autopilot.generator import run

n = int(sys.argv[1]) if len(sys.argv) > 1 else None
if n is not None:
    from autopilot.generator import load_config
    cfg = load_config()
    cfg["build"]["articles_per_run"] = n
    from autopilot import generator
    generator.load_config = lambda: cfg
run()
