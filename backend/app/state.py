"""app.state — Singletons partagés entre routers (swarm de découverte)."""
from app.db import db
from app.services.swarm_pipeline import Swarm

swarm = Swarm(db)
