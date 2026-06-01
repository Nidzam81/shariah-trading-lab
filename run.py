import os
os.environ["PORT"] = "9090"
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")).read())
