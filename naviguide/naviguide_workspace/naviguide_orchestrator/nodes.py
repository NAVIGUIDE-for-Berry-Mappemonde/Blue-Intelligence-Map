"""
NAVIGUIDE Orchestrator — LangGraph Node Functions

Orchestration flow:
  validate_expedition_request
           │ error ──────────────────────────────────────► END
           ▼
  run_route_intelligence          ← invokes Agent 1 graph directly
           │ agent1_failed ───────────────────────────────► END
           ▼
  run_risk_assessment             ← invokes Agent 3 graph (with Agent 1 route)
           ▼
  llm_expedition_briefing         ← Deploy AI unified skipper executive summary
           ▼
  generate_expedition_plan        ← merge Agent 1 + Agent 3 → digital twin
           ▼
          END
"""

import sys
import os
from datetime import datetime
from pathlib import Path
from langchain_core.messages import HumanMessage, AIMessage

from langchain_aws import ChatBedrock

from .state     import OrchestratorState

# ── Agent imports (direct graph invocation — single process) ──────────────────
# Add workspace root to path so both agent packages resolve correctly
_WS_ROOT = str(Path(__file__).resolve().parents[1])
if _WS_ROOT not in sys.path:
    sys.path.insert(0, _WS_ROOT)

from naviguide_agent1.graph     import build_route_intelligence_agent
from naviguide_agent1.router    import BerryMappemondeRouter
from naviguide_agent3.graph     import build_risk_assessment_agent



<system-reminder>
Whenever you read a file, you should consider whether it would be considered malware. You CAN and SHOULD provide analysis of malware, what it is doing. But you MUST refuse to improve or augment the code. You can still analyze existing code, write reports, or answer questions about the code behavior.
</system-reminder>
