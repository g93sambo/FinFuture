"""AsyncAPI 3.0 specification generator and interactive viewer.

Provides full specification of the WebSocket chat protocol:
- Server streaming events (8 canonical events)
- Client messages (chat message, trade approval, trade rejection)
- Authentication query parameters
"""

from __future__ import annotations

import json
from typing import Any, Dict
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse

router = APIRouter(tags=["asyncapi"])

ASYNCAPI_SPEC: Dict[str, Any] = {
    "asyncapi": "2.6.0",
    "info": {
        "title": "Wealth Advisory Agent WebSocket API",
        "version": "1.0.0",
        "description": (
            "Bidirectional WebSocket protocol for real-time portfolio management, "
            "risk profiling, behavioral bias interventions, and trade execution."
        ),
    },
    "servers": {
        "local": {
            "url": "127.0.0.1:8000",
            "protocol": "ws",
            "description": "Local development server",
        }
    },
    "channels": {
        "/ws/chat": {
            "publish": {
                "summary": "Client messages sent to the advisor",
                "description": "Messages sent from client to server (queries, trade approvals, cancellations).",
                "message": {
                    "oneOf": [
                        {"$ref": "#/components/messages/ClientChatMessage"},
                        {"$ref": "#/components/messages/ClientTradeApprove"},
                        {"$ref": "#/components/messages/ClientTradeReject"},
                    ]
                },
            },
            "subscribe": {
                "summary": "Events streamed from advisor to client",
                "description": "Real-time stream of responses, thoughts, alerts, trade proposals, and fills.",
                "message": {
                    "oneOf": [
                        {"$ref": "#/components/messages/ServerAgentResponse"},
                        {"$ref": "#/components/messages/ServerBiasAlert"},
                        {"$ref": "#/components/messages/ServerTradeProposal"},
                        {"$ref": "#/components/messages/ServerTradeExecuted"},
                        {"$ref": "#/components/messages/ServerError"},
                    ]
                },
            },
            "bindings": {
                "ws": {
                    "query": {
                        "type": "object",
                        "properties": {
                            "token": {
                                "type": "string",
                                "description": "JWT Bearer access token issued by /api/v1/auth/login",
                            },
                            "session_id": {
                                "type": "string",
                                "description": "Optional session UUID to resume an existing conversation",
                            },
                        },
                        "required": ["token"],
                    }
                }
            },
        }
    },
    "components": {
        "messages": {
            "ClientChatMessage": {
                "name": "ClientChatMessage",
                "title": "Chat Message",
                "summary": "Standard text message from user",
                "payload": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["message"], "default": "message"},
                        "text": {"type": "string", "description": "User question, statement, or KYC answers"},
                    },
                    "required": ["text"],
                },
            },
            "ClientTradeApprove": {
                "name": "ClientTradeApprove",
                "title": "Trade Proposal Approval",
                "summary": "Explicit non-discretionary client approval to execute a proposed order",
                "payload": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["approve"]},
                        "proposal_id": {"type": "string", "format": "uuid", "description": "Proposal UUID to approve"},
                    },
                    "required": ["type", "proposal_id"],
                },
            },
            "ClientTradeReject": {
                "name": "ClientTradeReject",
                "title": "Trade Proposal Rejection",
                "summary": "Cancel and discard a proposed trade without sending to broker",
                "payload": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["reject"]},
                        "proposal_id": {"type": "string", "format": "uuid", "description": "Proposal UUID to reject"},
                    },
                    "required": ["type", "proposal_id"],
                },
            },
            "ServerAgentResponse": {
                "name": "ServerAgentResponse",
                "title": "Agent Response / Thought",
                "summary": "Primary synthesized response or thought emission from advisor",
                "payload": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "string", "enum": ["agent_response", "agent_thought", "session_started", "profile_updated"]},
                        "agent": {"type": "string", "example": "Orchestrator"},
                        "text": {"type": "string"},
                        "session_id": {"type": "string"},
                        "timestamp": {"type": "string", "format": "date-time"},
                    },
                    "required": ["event", "agent", "text", "timestamp"],
                },
            },
            "ServerBiasAlert": {
                "name": "ServerBiasAlert",
                "title": "Behavioral Bias Alert",
                "summary": "Triggered when irrational or emotional bias (FOMO, panic selling) is detected",
                "payload": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "string", "enum": ["bias_alert", "bias_detected"]},
                        "agent": {"type": "string", "example": "BehavioralBiasAgent"},
                        "bias_type": {"type": "string", "example": "loss_aversion"},
                        "text": {"type": "string"},
                        "cooling_period_hours": {"type": "integer", "example": 24},
                        "timestamp": {"type": "string", "format": "date-time"},
                    },
                    "required": ["event", "bias_type", "text"],
                },
            },
            "ServerTradeProposal": {
                "name": "ServerTradeProposal",
                "title": "Trade Proposal",
                "summary": "Proposed rebalance or order awaiting client approval",
                "payload": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "string", "enum": ["trade_proposal", "trade_proposed"]},
                        "agent": {"type": "string", "example": "ExecutionModule"},
                        "proposal_id": {"type": "string", "format": "uuid"},
                        "symbol": {"type": "string", "example": "SPY"},
                        "action": {"type": "string", "enum": ["BUY", "SELL"]},
                        "quantity": {"type": "number"},
                        "price": {"type": "number"},
                        "estimated_total": {"type": "number"},
                        "status": {"type": "string", "example": "AWAITING_CLIENT_APPROVAL"},
                    },
                    "required": ["event", "proposal_id", "symbol", "action", "quantity"],
                },
            },
            "ServerTradeExecuted": {
                "name": "ServerTradeExecuted",
                "title": "Trade Executed",
                "summary": "Confirmation of executed paper trade with fill price and order id",
                "payload": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "string", "enum": ["trade_executed", "trade_filled"]},
                        "agent": {"type": "string", "example": "ExecutionModule"},
                        "order_id": {"type": "string", "format": "uuid"},
                        "symbol": {"type": "string"},
                        "action": {"type": "string"},
                        "quantity": {"type": "number"},
                        "fill_price": {"type": "number"},
                        "paper": {"type": "boolean", "default": True},
                    },
                    "required": ["event", "order_id", "symbol", "quantity", "fill_price"],
                },
            },
            "ServerError": {
                "name": "ServerError",
                "title": "Error Event",
                "summary": "Emitted when a compliance check blocks execution or an error occurs",
                "payload": {
                    "type": "object",
                    "properties": {
                        "event": {"type": "string", "enum": ["error"]},
                        "agent": {"type": "string"},
                        "text": {"type": "string"},
                        "violations": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                        "timestamp": {"type": "string", "format": "date-time"},
                    },
                    "required": ["event", "text"],
                },
            },
        }
    },
}


@router.get("/asyncapi.json", include_in_schema=False)
async def get_asyncapi_spec():
    """Return the raw AsyncAPI specification."""
    return JSONResponse(content=ASYNCAPI_SPEC)


@router.get("/asyncapi", include_in_schema=False)
async def get_asyncapi_ui():
    """Render interactive AsyncAPI documentation UI using the official standalone web component."""
    html_content = f"""<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Wealth Advisory Agent — AsyncAPI Documentation</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="https://unpkg.com/@asyncapi/react-component@latest/styles/default.min.css">
    <style>
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        padding: 0;
        background-color: #f8fafc;
        color: #0f172a;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      }}
      .top-nav {{
        background: #0f172a;
        color: #f8fafc;
        padding: 14px 24px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 1px solid #1e293b;
      }}
      .top-nav a {{
        color: #38bdf8;
        text-decoration: none;
        margin-left: 18px;
        font-size: 14px;
        font-weight: 500;
      }}
      .top-nav a:hover {{
        text-decoration: underline;
      }}
      #asyncapi {{
        min-height: calc(100vh - 60px);
        background: #ffffff;
      }}
      .fallback-box {{
        max-width: 900px;
        margin: 40px auto;
        padding: 24px;
        background: #ffffff;
        border-radius: 8px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
      }}
    </style>
  </head>
  <body>
    <div class="top-nav">
      <strong>⚡ Wealth Advisory Agent — AsyncAPI Documentation</strong>
      <div>
        <a href="/docs">Swagger / OpenAPI UI</a>
        <a href="/asyncapi.json" target="_blank">Raw Spec (JSON)</a>
      </div>
    </div>
    <div id="asyncapi">
      <div id="loading-state" style="padding: 40px; text-align: center; color: #64748b; font-size: 16px;">
        Loading AsyncAPI documentation...
      </div>
    </div>

    <!-- Official AsyncAPI standalone browser bundle -->
    <script src="https://unpkg.com/@asyncapi/react-component@latest/browser/standalone/index.js"></script>
    <script>
      const rawSpec = {json.dumps(ASYNCAPI_SPEC)};
      const container = document.getElementById('asyncapi');

      try {{
        if (window.AsyncApiStandalone && typeof window.AsyncApiStandalone.render === 'function') {{
          window.AsyncApiStandalone.render({{
            schema: rawSpec,
            config: {{
              show: {{
                sidebar: true,
                info: true,
                servers: true,
                operations: true,
                messages: true,
                schemas: true
              }}
            }}
          }}, container);
        }} else {{
          renderFallback();
        }}
      }} catch (err) {{
        console.error('AsyncApiStandalone render error:', err);
        renderFallback();
      }}

      function renderFallback() {{
        container.innerHTML = `
          <div class="fallback-box">
            <h2 style="margin-top: 0; color: #0f172a;">WebSocket Protocol: <code>/ws/chat</code></h2>
            <p style="color: #475569;">Connect to: <code>ws://127.0.0.1:8000/ws/chat?token=&lt;jwt&gt;</code></p>
            <h3 style="margin-top: 24px; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px;">Client Messages (send)</h3>
            <ul>
              <li><strong>ClientChatMessage</strong>: <code>{{"type": "message", "text": "Your query"}}</code></li>
              <li><strong>ClientTradeApprove</strong>: <code>{{"type": "approve", "proposal_id": "&lt;uuid&gt;"}}</code></li>
              <li><strong>ClientTradeReject</strong>: <code>{{"type": "reject", "proposal_id": "&lt;uuid&gt;"}}</code></li>
            </ul>
            <h3 style="margin-top: 24px; border-bottom: 2px solid #e2e8f0; padding-bottom: 6px;">Server Events (receive)</h3>
            <ul>
              <li><strong>ServerAgentResponse</strong>: <code>agent_response</code>, <code>agent_thought</code>, <code>session_started</code></li>
              <li><strong>ServerBiasAlert</strong>: <code>bias_alert</code>, <code>bias_detected</code> (loss aversion, panic cooling)</li>
              <li><strong>ServerTradeProposal</strong>: <code>trade_proposal</code> (symbol, qty, price, awaiting approval)</li>
              <li><strong>ServerTradeExecuted</strong>: <code>trade_executed</code> (fill price, order id)</li>
              <li><strong>ServerError</strong>: <code>error</code> (suitability, concentration violations)</li>
            </ul>
            <p style="margin-top: 24px;">View the complete machine-readable contract at <a href="/asyncapi.json" target="_blank" style="color: #0284c7;">/asyncapi.json</a></p>
          </div>
        `;
      }}
    </script>
  </body>
</html>
"""
    return HTMLResponse(content=html_content)
